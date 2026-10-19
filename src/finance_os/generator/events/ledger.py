"""General ledger (raw_erp): journal entries and lines, double-entry, accrual basis.

Postings:
- revenue        month end: Dr AR / Cr usage revenue, per customer (usage rated like the billing system)
- collection     invoice + segment days: Dr cash / Cr AR (left open if after the window, or if the
                 customer churned on a failed payment: the last two invoices are never collected).
                 Every customer payment is also recorded in a payments table with the invoice the customer
                 referenced (remittance) and the invoice AR applied it to; misapplications are configured.
- payment_fee    on collection: Dr payment processing / Cr cash (fee schedule seed)
- vendor_bill    service month end: Dr GPU / cloud COGS or R&D cloud / Cr AP
- vendor_payment bill date + N days: Dr AP / Cr cash
- payroll        month end, per department, from the line-item register: Dr salaries, employer taxes,
                 employer benefits / Cr cash (net pay), payroll taxes payable, benefits payable; the
                 liabilities are remitted on the 15th of the next month (payroll_remittance)
- opex           15th: Dr expense / Cr cash, scaled with headcount
- refund         a few paid self-serve invoices are refunded later: Dr refunds and credits (4010) / Cr cash
- one_off        on the date: Dr expense / Cr cash (e.g. unbudgeted legal fees)
- project_invoice     invoice date: Dr AR / Cr services revenue; project_collection after terms
- subcontractor_bill  bill date: Dr project subcontractor COGS / Cr AP; subcontractor_payment +N days
- project_odc         expense date: Dr project ODC COGS / Cr cash
- funding        Dr cash / Cr equity
"""
import calendar
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from finance_os.generator.seeds import read_seed

CENTS = Decimal("0.01")


def _cents(x):
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _month_end(d):
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


class Ledger:
    def __init__(self):
        self.entries, self.lines = [], []

    def post(self, entry_date, entry_type, memo, lines, source_ref=None):
        """lines: (account_id, debit, credit, dims) with dims a dict of department_id/customer_id/vendor_id."""
        assert sum(l[1] for l in lines) == sum(l[2] for l in lines), (entry_type, memo)
        entry_id = f"JE{len(self.entries) + 1:06d}"
        self.entries.append({"entry_id": entry_id, "entry_date": entry_date, "entry_type": entry_type,
                             "memo": memo, "source_ref": source_ref})
        for n, (account, debit, credit, dims) in enumerate(lines, 1):
            self.lines.append({"entry_id": entry_id, "line_no": n, "account_id": account,
                               "department_id": dims.get("department_id"), "customer_id": dims.get("customer_id"),
                               "vendor_id": dims.get("vendor_id"), "debit": debit, "credit": credit})


def rate_usage_lines(cfg, customers, usage):
    """Invoice lines per customer-month: (product_id, hours, unit price after tier discount, amount), rated
    exactly like int_usage_rated_monthly."""
    price = {p["product_id"]: Decimal(p["list_price_per_hour"]) for p in cfg["products"]}
    tiers = sorted(((t["min_hours_month"], Decimal(t["discount_pct"])) for t in cfg["volume_tiers"]), reverse=True)
    hours = defaultdict(Decimal)
    for u in usage:
        hours[(u["usage_date"].replace(day=1), u["customer_id"], u["product_id"])] += u["audio_hours"]
    customer_hours = defaultdict(Decimal)
    for (m, c, _), h in hours.items():
        customer_hours[(m, c)] += h
    lines = defaultdict(list)
    for (m, c, p), h in sorted(hours.items()):
        discount = next(d for floor, d in tiers if customer_hours[(m, c)] >= floor)
        lines[(m, c)].append((p, h, price[p] * (1 - discount), _cents(h * price[p] * (1 - discount))))
    return lines


def rate_usage(cfg, customers, usage):
    """Invoice amount per customer-month."""
    return {k: sum(l[3] for l in v) for k, v in rate_usage_lines(cfg, customers, usage).items()}


def post_payroll(gl, pay_register, end):
    """Payroll journal per run × department from the register, and the remittance of what it owes."""
    by_run_dept = defaultdict(lambda: defaultdict(Decimal))
    for r in pay_register:
        by_run_dept[(r["pay_run_id"], r["department_id"])][r["line_type"]] += r["amount"]
    owed = defaultdict(lambda: [Decimal(0), Decimal(0)])  # run -> [taxes payable, benefits payable]
    for (run, dept), t in sorted(by_run_dept.items()):
        y, m = int(run[3:7]), int(run[7:9])
        dims = {"department_id": dept}
        taxes = t["employee_tax"] + t["employer_tax"]
        benefits = t["employee_deduction"] + t["employer_benefit"]
        gl.post(_month_end(date(y, m, 1)), "payroll", f"Payroll {run} {dept}",
                [("6000", t["earning"], 0, dims), ("6010", t["employer_tax"], 0, dims), ("6020", t["employer_benefit"], 0, dims),
                 ("1000", 0, t["net_pay"], dims), ("2100", 0, taxes, dims), ("2110", 0, benefits, dims)], run)
        owed[run][0] += taxes
        owed[run][1] += benefits
    for run, (taxes, benefits) in sorted(owed.items()):
        y, m = int(run[3:7]), int(run[7:9])
        pay = date(y + (m == 12), m % 12 + 1, 15)
        if pay <= end:
            gl.post(pay, "payroll_remittance", f"Remit payroll taxes and benefits {run}",
                    [("2100", taxes, 0, {}), ("2110", benefits, 0, {}), ("1000", 0, taxes + benefits, {})], run)


def build_ledger(cfg, customers, usage, lifecycle, cloud_costs, bills, bill_lines, pay_register, employees,
                 projects, rng):
    end = cfg["window"]["end"]
    gl = Ledger()
    segment = {c["customer_id"]: c["segment"] for c in customers}
    fees = {f["segment"]: f for f in read_seed("payment_fee_schedule")}
    payments, disputes, billing = [], [], []
    refund_rng = random.Random(cfg["seed"] + 7)  # own stream: adding refunds doesn't shift other generated data
    stripe_cfg = cfg["stripe"]
    misapplied = {(m["customer_id"], m["remittance_month"]) for m in cfg["ar"]["misapplied_payments"]}

    def record_payment(cid, received, amount, remittance_ref, applied_ref):
        payments.append({"payment_id": f"PAY{len(payments) + 1:06d}", "customer_id": cid, "received_date": received,
                         "amount": amount, "remittance_ref": remittance_ref, "applied_ref": applied_ref})

    uncollectible = set()
    for e in lifecycle:
        if e["event_type"] == "churn" and e["reason"] == "payment_failed":
            churn_month = e["event_date"].replace(day=1)
            prior_month = (churn_month - timedelta(days=1)).replace(day=1)
            uncollectible |= {(e["customer_id"], churn_month), (e["customer_id"], prior_month)}

    for f in cfg["funding"]:
        amt = Decimal(f["amount"])
        gl.post(f["date"], "funding", f["memo"], [("1000", amt, 0, {}), ("3000", 0, amt, {})])

    # Revenue, collections and payment fees.
    for (month, cid), inv_lines in sorted(rate_usage_lines(cfg, customers, usage).items()):
        amount = sum(l[3] for l in inv_lines)
        if amount == 0:
            continue
        inv_date = _month_end(month)
        ref = f"INV-{cid}-{month:%Y%m}"
        dims = {"customer_id": cid}
        gl.post(inv_date, "revenue", f"Usage invoice {cid} {month:%Y-%m}",
                [("1200", amount, 0, dims), ("4000", 0, amount, dims)], ref)
        lo, hi = cfg["collections_days"][segment[cid]]
        paid = inv_date + timedelta(days=rng.randint(lo, hi))
        record = {"customer_id": cid, "segment": segment[cid], "month": month, "invoice_ref": ref, "invoice_date": inv_date,
                  "amount": amount, "lines": inv_lines, "status": "open", "paid_date": None, "fee": None, "refund": None}
        billing.append(record)
        if (cid, month) in uncollectible:
            record["status"] = "uncollectible"
        if paid > end or (cid, month) in uncollectible:
            continue
        record.update(status="paid", paid_date=paid)
        applied = ref
        if (cid, month) in misapplied:
            prior = (month - timedelta(days=1)).replace(day=1)
            applied = f"INV-{cid}-{prior:%Y%m}"
        record_payment(cid, paid, amount, ref, applied)
        gl.post(paid, "collection", f"Payment {ref}", [("1000", amount, 0, dims), ("1200", 0, amount, dims)], applied)
        f = fees[segment[cid]]
        fee = _cents(amount * Decimal(f["fee_pct"]) + Decimal(f["fee_fixed"]))
        if f["fee_cap"]:
            fee = min(fee, Decimal(f["fee_cap"]))
        gl.post(paid, "payment_fee", f"Processing fee {ref}", [("5100", fee, 0, dims), ("1000", 0, fee, dims)], ref)
        record["fee"] = fee
        if segment[cid] == "self_serve" and refund_rng.random() < float(stripe_cfg["refund_rate"]):
            refunded = paid + timedelta(days=refund_rng.randint(*stripe_cfg["refund_days"]))
            if refunded <= end:
                record["refund"] = {"date": refunded, "amount": amount, "reason": "requested_by_customer"}
                gl.post(refunded, "refund", f"Refund {ref}", [("4010", amount, 0, dims), ("1000", 0, amount, dims)], ref)

    # Vendor bills: GPU lines to GPU COGS; GCP cloud split by the share that is prod infra (hosting COGS).
    prod_share = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for c in cloud_costs:
        s = prod_share[c["usage_date"].replace(day=1)]
        s[1] += c["cost"]
        if c["label_team"] == "infra" and c["label_env"] == "prod":
            s[0] += c["cost"]
    lines_by_bill = defaultdict(list)
    for l in bill_lines:
        lines_by_bill[l["bill_id"]].append(l)
    for b in bills:
        dims = {"vendor_id": b["vendor_id"]}
        posting = []
        for l in lines_by_bill[b["bill_id"]]:
            if l["line_type"] == "cloud_services":
                prod, total = prod_share[b["service_month"]]
                cogs = _cents(l["amount"] * prod / total)
                posting += [("5010", cogs, 0, {**dims, "department_id": "INF"}),
                            ("6100", l["amount"] - cogs, 0, {**dims, "department_id": "ENG"})]
            else:
                posting.append(("5000", l["amount"], 0, {**dims, "department_id": "INF"}))
        posting.append(("2000", 0, b["total_amount"], dims))
        gl.post(_month_end(b["service_month"]), "vendor_bill", f"{b['vendor_id']} {b['service_month']:%Y-%m}", posting, b["bill_id"])
        pay = b["bill_date"] + timedelta(days=cfg["vendor_payment_days"])
        if pay <= end:
            gl.post(pay, "vendor_payment", f"Pay {b['bill_id']}",
                    [("2000", b["total_amount"], 0, dims), ("1000", 0, b["total_amount"], dims)], b["bill_id"])

    # Payroll, per department per pay run.
    post_payroll(gl, pay_register, end)

    # Opex scaled by headcount relative to the first month.
    def headcount(d):
        return sum(1 for e in employees if e["hire_date"] <= d and (e["termination_date"] is None or e["termination_date"] >= d))
    base = headcount(cfg["window"]["start"])
    y, m = cfg["window"]["start"].year, cfg["window"]["start"].month
    while date(y, m, 1) <= end:
        d = date(y, m, 15)
        scale = Decimal(headcount(d)) / Decimal(base)
        for o in cfg["opex_monthly"]:
            amt = _cents(Decimal(o["amount"]) * scale)
            dims = {"department_id": o["department"]}
            gl.post(d, "opex", o["memo"], [(o["account"], amt, 0, dims), ("1000", 0, amt, dims)])
        y, m = y + (m == 12), m % 12 + 1

    # Projects: services invoices, subcontractor bills, ODCs.
    collection_days = {p["project_id"]: p.get("collection_days") for p in cfg["projects"]}
    terms = {c["contract_id"]: c["payment_terms_days"] for c in projects["contracts"]}
    disputed = {(d["project_id"], d["service_month"]): d for d in cfg["ar"]["disputes"]}
    for inv in projects["project_invoices"]:
        dims = {"customer_id": inv["customer_id"]}
        d = disputed.get((inv["project_id"], inv["service_month"]))
        if d:
            disputes.append({"dispute_id": f"DSP{len(disputes) + 1:04d}", "customer_id": inv["customer_id"],
                             "invoice_ref": inv["invoice_id"], "project_id": inv["project_id"], "opened_date": d["opened"],
                             "amount": inv["amount"], "status": "open", "root_cause": d["root_cause"],
                             "resolved_date": None, "note": d["note"]})
        gl.post(inv["invoice_date"], "project_invoice", f"Services invoice {inv['project_id']}",
                [("1200", inv["amount"], 0, dims), ("4100", 0, inv["amount"], dims)], inv["invoice_id"])
        days = collection_days[inv["project_id"]]
        paid = inv["invoice_date"] + timedelta(days=rng.randint(*days) if days else terms[inv["contract_id"]] + rng.randint(-3, 10))
        if paid <= end and not d:
            record_payment(inv["customer_id"], paid, inv["amount"], inv["invoice_id"], inv["invoice_id"])
            gl.post(paid, "project_collection", f"Payment {inv['invoice_id']}",
                    [("1000", inv["amount"], 0, dims), ("1200", 0, inv["amount"], dims)], inv["invoice_id"])
    for b in projects["subcontractor_bills"]:
        dims = {"vendor_id": b["vendor_id"], "department_id": "PS"}
        gl.post(b["bill_date"], "subcontractor_bill", f"{b['vendor_id']} {b['project_id']}",
                [("5200", b["amount"], 0, dims), ("2000", 0, b["amount"], {"vendor_id": b["vendor_id"]})], b["bill_id"])
        pay = b["bill_date"] + timedelta(days=cfg["vendor_payment_days"])
        if pay <= end:
            gl.post(pay, "subcontractor_payment", f"Pay {b['bill_id']}",
                    [("2000", b["amount"], 0, {"vendor_id": b["vendor_id"]}), ("1000", 0, b["amount"], {"vendor_id": b["vendor_id"]})],
                    b["bill_id"])
    for o in projects["odc_expenses"]:
        dims = {"department_id": "PS"}
        gl.post(o["expense_date"], "project_odc", f"ODC {o['project_id']}",
                [("5210", o["amount"], 0, dims), ("1000", 0, o["amount"], dims)], o["expense_id"])

    for o in cfg.get("one_off_expenses", []):
        amt = Decimal(o["amount"])
        dims = {"department_id": o["department"]}
        gl.post(o["date"], "one_off", o["memo"], [(o["account"], amt, 0, dims), ("1000", 0, amt, dims)])

    return gl.entries, gl.lines, payments, disputes, billing
