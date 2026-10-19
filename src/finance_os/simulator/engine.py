"""One simulated day: the AI's events, then the business rules that turn them into usage, invoices and cash.

Order each day: decide (AI) → validate → apply events → hires → usage → billing (1st) → vendor bills (5th)
→ opex (15th) → collections → payment run (Thursday) → payroll and vendor accruals (month end).
Every money movement posts a balanced journal entry through simulator/books.py.
Amounts come only from code (price book, volume tiers, contract funding); the AI picks what happens and why.
Randomness (daily noise, new-customer sizes) is seeded by the date, so a day's numbers are reproducible given
its decisions, and every decision is logged in data/live/decisions.jsonl.
"""
import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from finance_os.generator.__main__ import load_config
from finance_os.generator.events.infra import COST_DP, build_gpu_jobs
from finance_os.generator.events.ledger import rate_usage_lines
from finance_os.simulator import agent
from finance_os.generator.documents.ap_bills import render_ap_pdfs
from finance_os.paths import ROOT, SEEDS
from finance_os.simulator import memory as mem
from finance_os.simulator.books import Books, _rows, cents, month_end
from finance_os.simulator.world import LIVE, Customer, append

INBOX = ROOT / "data" / "inbox" / "ap"

TERMS = {"self_serve": 0, "mid_market": 30, "enterprise": 45}
PREFIX = {"self_serve": "SS-", "mid_market": "MM-", "enterprise": "EN-"}
CENT = Decimal("0.01")


def _rng(*key):
    return random.Random("|".join(map(str, key)))


def _q(x, step="0.0001"):
    return (Decimal(x)).quantize(Decimal(step), ROUND_HALF_UP)


class Day:
    def __init__(self, world, today, stripe, live=LIVE, inbox=INBOX, approvals=None):
        self.w, self.today, self.stripe, self.live, self.inbox = world, today, stripe, live, inbox
        self.approvals = approvals  # AP approval gate (simulator/ap_approvals.py), read once per run
        self.cfg = load_config()
        self.spikes = {}
        self.out = defaultdict(list)
        self.documents = []          # vendor bill PDFs to drop in the AP inbox today
        self.books = Books(self)

    def log(self, table, **row):
        self.out[table].append(row)

    def lifecycle(self, cid, kind, multiplier, reason):
        self.log("lifecycle_events", event_id=self.w.next_id("event", "LV", 6), customer_id=cid,
                 event_date=self.today, event_type=kind, multiplier=multiplier, reason=reason, source="ai_agent")

    # ---- events -------------------------------------------------------------------------------------------
    def apply(self, e):
        t, w = e["type"], self.w
        c = w.customers.get(e.get("customer_id") or "")
        if t in ("expansion", "contraction"):
            m = _q(str(e["multiplier"]), "0.01")
            c.daily_hours = {p: str(_q(Decimal(h) * m)) for p, h in c.daily_hours.items()}
            self.lifecycle(c.customer_id, t, m, e["reason"])
        elif t == "spike":
            self.spikes[c.customer_id] = _q(str(e["multiplier"]), "0.01")
            self.lifecycle(c.customer_id, t, self.spikes[c.customer_id], e["reason"])
        elif t == "churn":
            c.status = "churned"
            self.lifecycle(c.customer_id, t, 0, e["reason"])
        elif t == "late_payer":
            c.pays_late_days = e["days"]
        elif t == "payment_failure":
            c.payment_risk = True
        elif t == "new_customer":
            self.new_customer(e)
        elif t == "refund":
            p = w.paid[e["invoice_ref"]]
            amount = (Decimal(p["amount"]) * Decimal(str(e["pct"]))).quantize(CENT, ROUND_HALF_UP)
            refund_id = self.stripe.refund(p["charge"], amount, e["invoice_ref"]) if p.get("charge") else None
            p["refunded"] = str(amount)
            dims = {"customer_id": p["customer_id"]}
            self.books.post(self.today, "refund", f"Refund {e['invoice_ref']}",
                            [("4010", amount, 0, dims), ("1000", 0, amount, dims)], e["invoice_ref"])
            self.log("refunds", invoice_ref=e["invoice_ref"], customer_id=p["customer_id"], refund_date=self.today,
                     amount=str(amount), reason=e["reason"], stripe_refund_id=refund_id)
        elif t == "project_milestone":
            k = w.contracts[e["contract_id"]]
            remaining = Decimal(k["funded"]) - Decimal(k["invoiced"])
            amount = (remaining * Decimal(str(e["pct"]))).quantize(CENT, ROUND_HALF_UP)
            k["invoiced"] = str(Decimal(k["invoiced"]) + amount)
            ref = w.next_id("project_invoice", "PINV")
            w.open_invoices[ref] = {"customer_id": k["customer_id"], "amount": str(amount), "kind": "project",
                                    "due": (self.today + timedelta(days=k["terms_days"])).isoformat(), "stripe_id": None}
            self.log("project_invoices", invoice_id=ref, project_id=k.get("project_id"), contract_id=e["contract_id"],
                     customer_id=k["customer_id"], invoice_date=self.today, service_month=None, amount=str(amount),
                     milestone_name=e["milestone_name"])
            self.log("project_invoice_lines", invoice_id=ref, line_no=1, line_type="milestone", amount=str(amount))
            dims = {"customer_id": k["customer_id"]}
            self.books.post(self.today, "project_invoice", f"Services invoice {k.get('project_id')}",
                            [("1200", amount, 0, dims), ("4100", 0, amount, dims)], ref)
        elif t == "vendor_price_increase":
            f = self.w.ops["price_factor"]
            f[e["vendor_id"]] = str((Decimal(f[e["vendor_id"]]) * (1 + Decimal(str(e["pct"])))).quantize(Decimal("0.0001")))
        elif t == "duplicate_bill":
            self.w.ops["pending_duplicates"].append(e["vendor_id"])
        elif t in ("vendor_bill", "wrong_po_bill"):
            self.books.one_off_bill(e["category"], e["size"], wrong_po=t == "wrong_po_bill")

    def new_customer(self, e):
        seg = e["segment"]
        n = 1 + max((int(k[3:]) for k in self.w.customers if k.startswith(PREFIX[seg])), default=0)
        cid = f"{PREFIX[seg]}{n:03d}"
        r = _rng(self.cfg["seed"], cid)
        lo, hi = self.cfg["segments"][seg]["start_hours"]
        third = (hi - lo) / 3
        start = {"small": 0, "medium": 1, "large": 2}[e["size"]]
        monthly = r.uniform(lo + start * third, lo + (start + 1) * third)
        products = list(dict.fromkeys(e["products"]))
        g_lo, g_hi = map(float, self.cfg["segments"][seg]["growth"])
        self.w.customers[cid] = Customer(
            cid, f"{seg.replace('_', ' ').title()} Customer {n}", seg, "active",
            {p: str(_q(monthly / 30 / len(products))) for p in products}, f"{r.uniform(max(g_lo, 0), g_hi):.4f}")
        self.log("customers", customer_id=cid, customer_name=self.w.customers[cid].name, segment=seg,
                 signup_date=self.today, start_hours_month=int(monthly), monthly_growth=self.w.customers[cid].monthly_growth)
        share = _q(Decimal(1) / len(products))
        for n, p in enumerate(products):
            last = n == len(products) - 1
            self.log("customer_product_mix", customer_id=cid, product_id=p,
                     share=str(Decimal(1) - share * (len(products) - 1) if last else share))

    # ---- daily rules --------------------------------------------------------------------------------------
    def usage(self):
        weekend = self.today.weekday() >= 5
        for c in self.w.active():
            daily_growth = (1 + Decimal(c.monthly_growth)) ** Decimal(1 / 30)
            c.daily_hours = {p: str(_q(Decimal(h) * daily_growth)) for p, h in c.daily_hours.items()}
            for p, base in sorted(c.daily_hours.items()):
                r = _rng(self.cfg["seed"], self.today, c.customer_id, p)
                f = Decimal(str(round(r.uniform(0.85, 1.15), 4))) * (Decimal("0.6") if weekend and c.segment != "enterprise" else 1)
                hours = _q(Decimal(base) * f * self.spikes.get(c.customer_id, 1))
                if hours > 0:
                    self.log("usage_daily", usage_date=self.today, customer_id=c.customer_id, product_id=p,
                             audio_hours=str(hours), requests=max(1, int(hours * Decimal(r.uniform(3, 5)))))

    def infra(self):
        """Today's GPU job logs and cloud cost lines, from today's usage (the generator's own infra model)."""
        rows = [{"usage_date": self.today, "customer_id": u["customer_id"], "product_id": u["product_id"],
                 "audio_hours": Decimal(u["audio_hours"])} for u in self.out["usage_daily"]]
        jobs = build_gpu_jobs(self.cfg, rows, _rng(self.cfg["seed"], "jobs", self.today))
        for n, j in enumerate(jobs, 1):
            self.log("gpu_jobs", **{**j, "job_id": f"LJ{self.today:%Y%m%d}{n:05d}"})
        hours = sum((r["audio_hours"] for r in rows), Decimal(0))
        for line in self.cfg["cloud_overhead"]:
            self.log("cloud_costs_daily", usage_date=self.today, service=line["service"], sku=line["sku"],
                     label_team=line["team"], label_env=line["env"],
                     cost=str((Decimal(line["fixed"]) + Decimal(line["per_hour"]) * hours).quantize(COST_DP)))

    def month_infra(self, month):
        """GPU jobs and cloud cost lines for a month (live files plus today), typed for the vendor-bill model."""
        m = month.isoformat()[:7]
        jobs = [{**j, "job_date": date.fromisoformat(str(j["job_date"])), "gpu_seconds": int(j["gpu_seconds"])}
                for j in read(self.live, "gpu_jobs") + self.out["gpu_jobs"] if str(j["job_date"])[:7] == m]
        cloud = [{**c, "usage_date": date.fromisoformat(str(c["usage_date"])), "cost": Decimal(c["cost"])}
                 for c in read(self.live, "cloud_costs_daily") + self.out["cloud_costs_daily"] if str(c["usage_date"])[:7] == m]
        return jobs, cloud

    def bill_last_month(self):
        """On the 1st: rate last month's live usage per customer and invoice it (Stripe + ERP)."""
        month = (self.today - timedelta(days=1)).replace(day=1)
        rows = [{"usage_date": date.fromisoformat(u["usage_date"]), "customer_id": u["customer_id"],
                 "product_id": u["product_id"], "audio_hours": Decimal(u["audio_hours"])}
                for u in read(self.live, "usage_daily") if u["usage_date"][:7] == month.isoformat()[:7]]
        for (m, cid), lines in sorted(rate_usage_lines(self.cfg, None, rows).items()):
            c = self.w.customers[cid]
            amount = sum(l[3] for l in lines)
            ref = f"INV-{cid}-{m:%Y%m}"  # same reference format as the history
            due = self.today + timedelta(days=TERMS[c.segment])
            stripe_id = self.stripe.invoice(c, ref, m, self.today, lines, TERMS[c.segment])
            self.w.open_invoices[ref] = {"customer_id": cid, "amount": str(amount), "due": due.isoformat(),
                                         "stripe_id": stripe_id, "kind": "usage", "attempts": 0}
            dims = {"customer_id": cid}
            self.books.post(month_end(m), "revenue", f"Usage invoice {cid} {m:%Y-%m}",
                            [("1200", amount, 0, dims), ("4000", 0, amount, dims)], ref)
            self.log("invoices", invoice_ref=ref, customer_id=cid, service_month=m, invoice_date=self.today,
                     due_date=due, amount=str(amount), stripe_invoice_id=stripe_id,
                     lines=[{"product_id": p, "audio_hours": str(h), "unit_price": str(u), "amount": str(a)} for p, h, u, a in lines])

    def collect(self):
        """Pay what is due: cards on the invoice date (with retries on failure), invoices after terms + lateness."""
        for ref, inv in sorted(self.w.open_invoices.items()):
            c = self.w.customers.get(inv["customer_id"])
            late = c.pays_late_days if c else 0
            if self.today < date.fromisoformat(inv["due"]) + timedelta(days=late):
                continue
            if c and c.segment == "self_serve" and c.payment_risk:
                inv["attempts"] = inv.get("attempts", 0) + 1
                self.stripe.fail(c, inv["stripe_id"])
                self.log("payment_attempts", invoice_ref=ref, attempt_date=self.today, status="failed")
                if inv["attempts"] >= 3:
                    self.stripe.uncollectible(inv["stripe_id"])
                    del self.w.open_invoices[ref]
                    c.status = "churned"
                    self.lifecycle(c.customer_id, "churn", 0, "payment_failed")
                else:
                    inv["due"] = (self.today + timedelta(days=3)).isoformat()
                continue
            charge, stripe_fee = self.stripe.pay(inv["stripe_id"]) if inv["stripe_id"] else (None, None)
            self.w.paid[ref] = {"customer_id": inv["customer_id"], "amount": inv["amount"], "charge": charge, "refunded": "0"}
            del self.w.open_invoices[ref]
            amount, dims = Decimal(inv["amount"]), {"customer_id": inv["customer_id"]}
            self.log("payments", invoice_ref=ref, customer_id=inv["customer_id"], payment_date=self.today,
                     amount=inv["amount"], stripe_charge_id=charge)
            self.log("customer_payments", payment_id=self.w.next_id("payment", "LPAY", 6), customer_id=inv["customer_id"],
                     received_date=self.today, amount=inv["amount"], remittance_ref=ref, applied_ref=ref)
            if inv["kind"] == "project":
                self.books.post(self.today, "project_collection", f"Payment {ref}",
                                [("1000", amount, 0, dims), ("1200", 0, amount, dims)], ref)
                continue
            self.books.post(self.today, "collection", f"Payment {ref}", [("1000", amount, 0, dims), ("1200", 0, amount, dims)], ref)
            fee = stripe_fee if stripe_fee is not None else self.fee(c.segment if c else "enterprise", amount)
            if fee:
                self.books.post(self.today, "payment_fee", f"Processing fee {ref}",
                                [("5100", fee, 0, dims), ("1000", 0, fee, dims)], ref)

    def fee(self, segment, amount):
        """Processing fee per seeds/payment_fee_schedule.csv (used when Stripe didn't report one)."""
        f = next(r for r in _rows(SEEDS / "payment_fee_schedule.csv") if r["segment"] == segment)
        fee = cents(amount * Decimal(f["fee_pct"]) + Decimal(f["fee_fixed"]))
        return min(fee, Decimal(f["fee_cap"])) if f["fee_cap"] else fee

    def month_hours(self):
        """Audio hours served so far this month (for vendor accruals)."""
        m = self.today.isoformat()[:7]
        return sum((Decimal(u["audio_hours"]) for u in read(self.live, "usage_daily") + self.out["usage_daily"]
                    if str(u["usage_date"])[:7] == m), Decimal(0))

    # ---- the day ------------------------------------------------------------------------------------------
    def run(self, decide=agent.decide_with_provider, memory=None):
        products = {p["product_id"] for p in self.cfg["products"]}
        history = [d for d in read(self.live, "decisions") if d["status"] == "applied"]
        summary = agent.summarize(self.w, self.today, [{"ref": r, **p} for r, p in self.w.paid.items()], history)
        segment_of = {c.customer_id: c.segment for c in self.w.customers.values()}
        tools = {
            "search_memory": lambda query, k=8, **f: memory.search(query, k=k, **f) if memory else [],
            "count_events": lambda event_type, segment, days: agent.count_events(
                history, self.today, event_type, segment, days, segment_of)}
        events, usage = decide(summary, tools)
        for e in events[:agent.MAX_EVENTS]:
            why_not = agent.validate(e, self.w, self.today, self.w.paid.keys(), products, history)
            self.log("decisions", date=self.today.isoformat(), event=e, status="rejected" if why_not else "applied", note=why_not)
            if not why_not:
                self.apply(e)
                history.append({"date": self.today.isoformat(), "event": e})
        self.log("agent_calls", date=self.today, **usage)
        self.books.start_hires()
        self.books.post_uploaded_bills(self.approvals)
        self.usage()
        self.infra()
        if self.today.day == 1:
            self.bill_last_month()
        if self.today.day == 5:
            self.books.receive_cloud_bills(*self.month_infra((self.today.replace(day=1) - timedelta(days=1)).replace(day=1)))
        if self.today.day == 15:
            self.books.opex()
            self.books.remit_payroll()
        self.collect()
        if self.today.weekday() == 3:
            self.books.payment_run(self.approvals)
        if self.today == month_end(self.today):
            self.books.payroll()
            self.books.depreciate()
            self.books.accrue_vendors(*self.month_infra(self.today.replace(day=1)))
        if self.documents:
            render_ap_pdfs(self.cfg, [d for d, _ in self.documents], [l for _, ls in self.documents for l in ls],
                           self.inbox, clear=False)
        self.w.as_of = self.today.isoformat()
        if memory:
            remember(self, memory)
        for table, rows in self.out.items():
            append(table, rows, self.live)
        return self.out


def remember(self, memory):
        """Chunk today into memory: each decision, a daily digest, and on the 1st last month's summary."""
        chunks = [mem.decision_chunk({**d, "n": n}, self.w.customers.get(d["event"].get("customer_id") or "", None)
                                     and self.w.customers[d["event"]["customer_id"]].segment)
                  for n, d in enumerate(self.out["decisions"])]
        chunks.append(mem.daily_chunk(self.today, self.out))
        if self.today.day == 1:
            month = (self.today - timedelta(days=1)).replace(day=1)
            chunks.append(mem.monthly_chunk(month, read(self.live, "decisions") + self.out["decisions"], self.w,
                                            read(self.live, "invoices") + self.out["invoices"]))
        memory.add(chunks)


def read(live, name):
    import json
    path = live / f"{name}.jsonl"
    return [json.loads(l) for l in open(path, encoding="utf-8")] if path.exists() else []
