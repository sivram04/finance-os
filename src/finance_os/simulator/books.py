"""The live company's books: every live event posts a balanced journal entry in the same shape the history
uses (same accounts, entry types and reference formats), so the warehouse cannot tell live from historical.

What runs on its own, by date:
  month end      payroll (per department) and vendor accruals (GCP, Nimbus) from this month's GPU job logs and
                 cloud cost lines, priced at contract rates (the generator's own vendor-billing model, no noise)
  5th            vendor bills arrive, as the vendor meters them (metering noise, any price increase): PDF in the
                 AP inbox (read by M16 intake), ERP bill, and a true-up for the difference from the accrual
  15th           recurring opex (software, rent, legal, marketing), scaled by headcount
  Thursday       vendor payment run: bills due within a week, or inside an early-pay discount window
  any day        planned hires start on their date (seeds/hiring_plan.csv)
What the AI can add (validated in agent.py): a vendor price increase (shows up as a true-up surprise), a
duplicate bill PDF, a one-off bill from a new vendor, a bill quoting a PO that doesn't exist.
"""
import copy
import csv
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from finance_os.generator.events.vendor_bills import build_vendor_bills
from finance_os.paths import SEEDS

CENT = Decimal("0.01")
VENDOR_PREFIX = {"gcp": "GCP", "nimbus": "NIMBUS"}
# One-off vendors the AI can send bills from: (vendor_id, account, department, $ range for a 'medium' bill)
LIVE_VENDORS = {
    "legal": ("lexpoint", "6400", "GA", (4000, 18000)),
    "consulting": ("northwind", "6400", "GA", (6000, 30000)),
    "software": ("brightstack", "6200", "ENG", (1500, 9000)),
    "marketing": ("adhaven", "6500", "SAL", (3000, 20000)),
}
SIZE = {"small": Decimal("0.4"), "medium": Decimal("1"), "large": Decimal("2.5")}
EMPLOYER_TAX, BENEFITS = Decimal("0.0765"), Decimal("950.00")


def cents(x):
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def month_end(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- starting state from the synthetic history ---------------------------------------------------------

def init_ops(world, src: Path):
    end = world.day()
    entries = {e["entry_id"]: e for e in _rows(src / "journal_entries.csv")}
    lines = _rows(src / "journal_lines.csv")
    ops = world.ops
    ops["cash"] = str(sum(Decimal(l["debit"]) - Decimal(l["credit"]) for l in lines if l["account_id"] == "1000"))

    # staff on the payroll at the end of history, and the roles still to be hired
    ops["employees"] = [{"employee_id": e["employee_id"], "department_id": e["department_id"],
                         "annual_salary": e["annual_salary"], "title": e["title"]}
                        for e in _rows(src / "employees.csv")
                        if date.fromisoformat(e["hire_date"]) <= end
                        and (not e["termination_date"] or date.fromisoformat(e["termination_date"]) > end)]
    ops["planned_hires"] = [h for h in _rows(SEEDS / "hiring_plan.csv")
                            if h["status"] in ("open", "approved") and date.fromisoformat(h["planned_start"]) > end]
    ops["employee_seq"] = len(_rows(src / "employees.csv"))
    ops["base_headcount"] = len(ops["employees"])

    # recurring opex: last month's entries are the template
    last_opex = max(e["entry_date"] for e in entries.values() if e["entry_type"] == "opex")
    ops["opex_template"] = [{"memo": entries[l["entry_id"]]["memo"], "account_id": l["account_id"],
                             "department_id": l["department_id"], "amount": l["debit"]}
                            for l in lines if entries[l["entry_id"]]["entry_type"] == "opex"
                            and entries[l["entry_id"]]["entry_date"] == last_opex and l["account_id"] != "1000"]

    # vendor cost per audio hour (last 3 months of bills ÷ usage), GPU rates, and GCP's production share
    bills = {b["bill_id"]: b for b in _rows(src / "vendor_bills.csv")}
    months = sorted({b["service_month"] for b in bills.values()})[-3:]
    hours = sum(Decimal(u["audio_hours"]) for u in _rows(src / "usage_daily.csv")
                if u["usage_date"][:7] + "-01" in months)
    per_hour = defaultdict(Decimal)
    for l in _rows(src / "vendor_bill_lines.csv"):
        b = bills[l["bill_id"]]
        if b["service_month"] in months and l["line_type"] != "commit_shortfall":
            per_hour[(b["vendor_id"], l["line_type"], l["gpu_type"])] += Decimal(l["amount"])
    ops["vendor_cost_per_hour"] = [{"vendor_id": v, "line_type": t, "gpu_type": g, "per_hour": str(a / hours)}
                                   for (v, t, g), a in sorted(per_hour.items())]
    rates = {}
    for r in sorted(_rows(SEEDS / "gpu_rates.csv"), key=lambda r: r["effective_from"]):
        rates[r["gpu_type"]] = r["rate_per_gpu_hour"]
    ops["gpu_rates"] = rates
    gcp_last = max((e for e in entries.values() if e["entry_type"] == "vendor_bill" and "GCP" in (e["source_ref"] or "")),
                   key=lambda e: e["entry_date"])
    gl = {l["account_id"]: Decimal(l["debit"]) for l in lines if l["entry_id"] == gcp_last["entry_id"]}
    cloud = gl.get("5010", 0) + gl.get("6100", 0)
    ops["gcp_prod_share"] = str(gl.get("5010", 0) / cloud) if cloud else "0.5"
    ops["price_factor"] = {"gcp": "1", "nimbus": "1"}
    ops["invoice_seq"] = {}
    for b in bills.values():
        _, year, n = b["vendor_invoice_number"].split("-")
        key = f"{b['vendor_id']}|{year}"  # vendors restart their numbering each year
        ops["invoice_seq"][key] = max(ops["invoice_seq"].get(key, 0), int(n))
    ops["accrued"] = {}
    ops["pending_duplicates"] = []

    # open AP: bills booked but not yet paid
    paid_refs = {e["source_ref"] for e in entries.values() if e["entry_type"] in ("vendor_payment", "subcontractor_payment")}
    ops["open_bills"] = {}
    for e in entries.values():
        if e["entry_type"] in ("vendor_bill", "subcontractor_bill") and e["source_ref"] not in paid_refs:
            ap = [l for l in lines if l["entry_id"] == e["entry_id"] and l["account_id"] == "2000"]
            b = bills.get(e["source_ref"])
            bill_date = b["bill_date"] if b else e["entry_date"]
            ops["open_bills"][e["source_ref"]] = {
                "vendor_id": ap[0]["vendor_id"], "amount": str(sum(Decimal(l["credit"]) for l in ap)), "bill_date": bill_date,
                "due": (date.fromisoformat(bill_date) + timedelta(days=30)).isoformat(),
                "kind": "subcontractor_payment" if e["entry_type"] == "subcontractor_bill" else "vendor_payment"}

    # open AR from history: invoices with a balance, collected by the live company on their terms
    ar = defaultdict(Decimal)
    meta = {}
    for l in lines:
        if l["account_id"] != "1200":
            continue
        e = entries[l["entry_id"]]
        ar[e["source_ref"]] += Decimal(l["debit"]) - Decimal(l["credit"])
        if Decimal(l["debit"]) > 0:
            meta[e["source_ref"]] = (l["customer_id"], e["entry_type"], e["entry_date"])
    disputed = {d["invoice_ref"] for d in _rows(src / "disputes.csv") if d["status"] == "open"}
    terms = {p["segment"]: int(p["payment_terms_days"]) for p in _rows(SEEDS / "ar_policy.csv")}
    contract_terms = {k["contract_id"]: int(k["payment_terms_days"]) for k in _rows(src / "contracts.csv")}
    pinv_contract = {i["invoice_id"]: i["contract_id"] for i in _rows(src / "project_invoices.csv")}
    for ref, bal in ar.items():
        if bal <= 0 or ref not in meta or ref in disputed:
            continue
        cid, etype, inv_date = meta[ref]
        c = world.customers.get(cid)
        days = contract_terms.get(pinv_contract.get(ref)) if etype == "project_invoice" else terms[c.segment if c else "enterprise"]
        world.open_invoices[ref] = {"customer_id": cid, "amount": str(bal), "stripe_id": None,
                                    "kind": "project" if etype == "project_invoice" else "usage",
                                    "due": (date.fromisoformat(inv_date) + timedelta(days=days or 30)).isoformat()}


# ---- posting --------------------------------------------------------------------------------------------

class Books:
    """Posts journal entries for one simulated day (rows go to data/live/journal_entries / journal_lines)."""

    def __init__(self, day):
        self.day, self.w = day, day.w

    def post(self, entry_date, entry_type, memo, lines, ref=None):
        """lines: (account_id, debit, credit, dims)."""
        debit = sum(cents(l[1]) for l in lines)
        assert debit == sum(cents(l[2]) for l in lines), (entry_type, memo)
        entry_id = self.w.next_id("journal", "LJE", 6)
        self.day.log("journal_entries", entry_id=entry_id, entry_date=entry_date, entry_type=entry_type, memo=memo, source_ref=ref)
        for n, (account, dr, cr, dims) in enumerate(lines, 1):
            self.day.log("journal_lines", entry_id=entry_id, line_no=n, account_id=account,
                         department_id=dims.get("department_id"), customer_id=dims.get("customer_id"),
                         vendor_id=dims.get("vendor_id"), debit=str(cents(dr)), credit=str(cents(cr)))
            if account == "1000":
                self.w.ops["cash"] = str(Decimal(self.w.ops["cash"]) + cents(dr) - cents(cr))
        return entry_id

    # ---- people ----
    def start_hires(self):
        today = self.day.today
        for h in list(self.w.ops["planned_hires"]):
            if date.fromisoformat(h["planned_start"]) <= today:
                self.w.ops["employee_seq"] += 1
                e = {"employee_id": f"E{self.w.ops['employee_seq']:03d}", "department_id": h["department_id"],
                     "annual_salary": h["annual_salary"], "title": h["title"]}
                self.w.ops["employees"].append(e)
                self.w.ops["planned_hires"].remove(h)
                self.day.log("employees", employee_id=e["employee_id"], employee_name=f"Employee {e['employee_id'][1:]}",
                             department_id=e["department_id"], function=None, title=e["title"], hire_date=today,
                             termination_date=None, annual_salary=e["annual_salary"])

    def payroll(self):
        today = self.day.today
        run = f"PR-{today:%Y%m}"
        self.day.log("pay_runs", pay_run_id=run, period_start=today.replace(day=1), period_end=today, pay_date=today)
        by_dept = defaultdict(lambda: [Decimal(0)] * 3)
        for e in self.w.ops["employees"]:
            gross = cents(Decimal(e["annual_salary"]) / 12)
            tax = cents(gross * EMPLOYER_TAX)
            self.day.log("pay_lines", pay_run_id=run, employee_id=e["employee_id"], department_id=e["department_id"],
                         gross_pay=str(gross), employer_tax=str(tax), benefits=str(BENEFITS))
            t = by_dept[e["department_id"]]
            t[0] += gross; t[1] += tax; t[2] += BENEFITS
        for dept, (gross, tax, ben) in sorted(by_dept.items()):
            dims = {"department_id": dept}
            self.post(today, "payroll", f"Payroll {run} {dept}",
                      [("6000", gross, 0, dims), ("6010", tax, 0, dims), ("6020", ben, 0, dims),
                       ("1000", 0, gross + tax + ben, dims)], run)

    def opex(self):
        ratio = Decimal(len(self.w.ops["employees"])) / Decimal(self.w.ops["base_headcount"])
        for o in self.w.ops["opex_template"]:
            amt = cents(Decimal(o["amount"]) * ratio)
            dims = {"department_id": o["department_id"]}
            self.post(self.day.today, "opex", o["memo"], [(o["account_id"], amt, 0, dims), ("1000", 0, amt, dims)])

    # ---- vendors ----
    def _vendor_bills(self, jobs, cloud, metered, seed_key):
        """The generator's vendor-billing model on these job logs and cost lines: {vendor: (bill, lines)}.
        metered=False prices our own logs at contract rates (the accrual); True adds the vendor's metering noise."""
        cfg = self.day.cfg
        if not metered:
            cfg = copy.deepcopy(cfg)
            cfg["vendor_billing"]["metering_noise_pct"] = "0"
        bills, lines = build_vendor_bills(cfg, jobs, cloud, random.Random(f"{cfg['seed']}|{seed_key}"))
        out = {}
        for b in bills:
            out[b["vendor_id"]] = (b, [{k: l[k] for k in ("line_type", "gpu_type", "quantity_hours", "amount")}
                                       for l in lines if l["bill_id"] == b["bill_id"]])
        return out

    def _post_vendor_cost(self, entry_date, vendor, lines, memo, ref, prod_share):
        dims = {"vendor_id": vendor}
        posting = []
        for l in lines:
            if l["line_type"] == "cloud_services":
                prod = cents(l["amount"] * prod_share)
                posting += [("5010", prod, 0, {**dims, "department_id": "INF"}),
                            ("6100", l["amount"] - prod, 0, {**dims, "department_id": "ENG"})]
            else:
                posting.append(("5000", l["amount"], 0, {**dims, "department_id": "INF"}))
        total = sum(l["amount"] for l in lines)
        if total < 0:  # a true-up that reduces cost: the same lines as credits
            posting = [(a, 0, -d, x) for a, d, _, x in posting] + [("2000", -total, 0, dims)]
        else:
            posting.append(("2000", 0, total, dims))
        self.post(entry_date, "vendor_bill", memo, posting, ref)

    @staticmethod
    def _prod_share(cloud):
        total = sum((c["cost"] for c in cloud), Decimal(0))
        prod = sum((c["cost"] for c in cloud if c["label_team"] == "infra" and c["label_env"] == "prod"), Decimal(0))
        return prod / total if total else Decimal(0)

    def accrue_vendors(self, jobs, cloud):
        """Month end: book this month's GPU and cloud cost from our own logs before the bills arrive."""
        today = self.day.today
        share = self._prod_share(cloud)
        for vendor, (bill, lines) in sorted(self._vendor_bills(jobs, cloud, False, f"accrual|{today:%Y%m}").items()):
            ref = bill["bill_id"]
            self._post_vendor_cost(today, vendor, lines, f"{vendor} {today:%Y-%m}", ref, share)
            self.w.ops["accrued"][ref] = {"vendor_id": vendor, "month": today.replace(day=1).isoformat(),
                                          "prod_share": str(share),
                                          "lines": [{**l, "amount": str(l["amount"]),
                                                     "quantity_hours": None if l["quantity_hours"] is None else str(l["quantity_hours"])}
                                                    for l in lines]}

    def receive_cloud_bills(self, jobs, cloud):
        """5th: last month's bills arrive as the vendor metered them (noise, and any price increase the AI
        introduced); the difference from the accrual is trued up on the bill date."""
        today = self.day.today
        month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        metered = self._vendor_bills(jobs, cloud, True, f"bill|{month:%Y%m}")
        for ref, acc in sorted(self.w.ops["accrued"].items()):
            if acc["month"] != month.isoformat() or acc["vendor_id"] not in metered:
                continue
            vendor = acc["vendor_id"]
            factor = Decimal(self.w.ops["price_factor"].get(vendor, "1"))
            lines = [{**l, "amount": cents(l["amount"] * factor)} for l in metered[vendor][1]]
            key = lambda l: l["line_type"] + (l["gpu_type"] or "")  # noqa: E731
            accrued = {key(l): Decimal(l["amount"]) for l in acc["lines"]}
            true_up = [{**l, "amount": l["amount"] - accrued.pop(key(l), Decimal(0))} for l in lines]
            true_up += [{**l, "amount": -Decimal(l["amount"])} for l in acc["lines"] if key(l) in accrued]
            if any(l["amount"] for l in true_up):
                self._post_vendor_cost(today, vendor, true_up, f"{vendor} {acc['month'][:7]} true-up to bill", ref,
                                       Decimal(acc["prod_share"]))
            self._receive(ref, vendor, acc["month"], lines)
            del self.w.ops["accrued"][ref]

    def _invoice_number(self, vendor, layout_prefix):
        seq, key = self.w.ops["invoice_seq"], f"{vendor}|{self.day.today:%Y}"
        seq[key] = seq.get(key, 0) + 1
        return f"{layout_prefix}-{self.day.today:%Y}-{seq[key]:04d}"

    def _receive(self, bill_id, vendor, service_month, lines, po=None, issue=None):
        """A bill arrives: ERP record, PDF in the AP inbox, open AP."""
        today = self.day.today
        layouts = self.day.cfg["ap_documents"]["layouts"]
        number = self._invoice_number(vendor, layouts[vendor]["prefix"])
        total = sum(l["amount"] for l in lines)
        self.day.log("vendor_bills", bill_id=bill_id, vendor_id=vendor, service_month=service_month, bill_date=today,
                     total_amount=str(total), vendor_invoice_number=number)
        for l in lines:
            self.day.log("vendor_bill_lines", bill_id=bill_id, line_type=l["line_type"], gpu_type=l.get("gpu_type"),
                         quantity_hours=str(l["quantity_hours"]) if l.get("quantity_hours") is not None else None,
                         amount=str(l["amount"]))
        doc_lines = [{"description": l.get("description") or l["line_type"].replace("_", " ").capitalize()
                      + (f" ({l['gpu_type']})" if l.get("gpu_type") else ""),
                      "quantity": l.get("quantity_hours"), "amount": l["amount"]} for l in lines]
        copies = 2 if vendor in self.w.ops["pending_duplicates"] else 1
        if copies == 2:
            self.w.ops["pending_duplicates"].remove(vendor)
        for copy in range(1, copies + 1):
            doc = f"{number}" + (f"_copy{copy}" if copy > 1 else "") + ".pdf"
            self.day.documents.append(({"doc_file": doc, "vendor_id": vendor, "vendor_invoice_number": number,
                                        "invoice_date": today, "po_number": po, "total": total},
                                       [{"doc_file": doc, "line_no": n, **l} for n, l in enumerate(doc_lines, 1)]))
            self.day.log("ap_documents", doc_file=doc, bill_id=bill_id, vendor_id=vendor, total=str(total),
                         issue=issue if copy == 1 else "duplicate_submission")
        self.w.ops["open_bills"][bill_id] = {"vendor_id": vendor, "amount": str(total), "bill_date": today.isoformat(),
                                             "due": (today + timedelta(days=30)).isoformat(), "kind": "vendor_payment"}
        return number

    def one_off_bill(self, category, size, wrong_po=False):
        today = self.day.today
        vendor, account, dept, (lo, hi) = LIVE_VENDORS[category]
        r = random.Random(f"{self.day.cfg['seed']}|{today}|{category}|{size}")
        amount = cents(Decimal(str(r.uniform(lo, hi))) * SIZE[size])
        bill_id = f"BILL-{vendor.upper()}-{today:%Y%m%d}"
        dims = {"vendor_id": vendor}
        self.post(today, "vendor_bill", f"{vendor} {category}",
                  [(account, amount, 0, {**dims, "department_id": dept}), ("2000", 0, amount, dims)], bill_id)
        po = f"PO{r.randint(90000, 99999)}" if wrong_po else None
        line = {"line_type": "services", "description": f"{category.capitalize()} services {today:%B %Y}",
                "quantity_hours": None, "amount": amount}
        return self._receive(bill_id, vendor, today.replace(day=1), [line], po=po, issue="wrong_po" if wrong_po else "new_vendor")

    def payment_run(self):
        """Thursday: pay bills due within the next 7 days, and bills inside an early-pay discount window."""
        today = self.day.today
        terms = {t["vendor_id"]: t for t in _rows(SEEDS / "vendor_payment_terms.csv")}
        for bill_id, b in sorted(self.w.ops["open_bills"].items()):
            t = terms.get(b["vendor_id"], terms["default"])
            pct, window = Decimal(t["early_pay_discount_pct"]), int(t["discount_days"])
            in_window = pct > 0 and today <= date.fromisoformat(b["bill_date"]) + timedelta(days=window)
            if not (in_window or date.fromisoformat(b["due"]) <= today + timedelta(days=7)):
                continue
            amount = Decimal(b["amount"])
            discount = cents(amount * pct) if in_window else Decimal(0)
            dims = {"vendor_id": b["vendor_id"]}
            lines = [("2000", amount, 0, dims), ("1000", 0, amount - discount, dims)]
            if discount:
                lines.append(("5000", 0, discount, {**dims, "department_id": "INF"}))
            self.post(today, b["kind"], f"Pay {bill_id}", lines, bill_id)
            self.day.log("ap_payments", bill_id=bill_id, vendor_id=b["vendor_id"], payment_date=today,
                         amount=str(amount - discount), discount=str(discount))
            del self.w.ops["open_bills"][bill_id]
