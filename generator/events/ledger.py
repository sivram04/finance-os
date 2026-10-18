"""General ledger (raw_erp): journal entries and lines, double-entry, accrual basis.

Postings:
- revenue        month end: Dr AR / Cr usage revenue, per customer (usage rated like the billing system)
- collection     invoice + segment days: Dr cash / Cr AR (left open if after the window, or if the
                 customer churned on a failed payment: the last two invoices are never collected)
- payment_fee    on collection: Dr payment processing / Cr cash (fee schedule seed)
- vendor_bill    service month end: Dr GPU / cloud COGS or R&D cloud / Cr AP
- vendor_payment bill date + N days: Dr AP / Cr cash
- payroll        month end, per department: Dr salaries, taxes, benefits / Cr cash
- opex           15th: Dr expense / Cr cash, scaled with headcount
- funding        Dr cash / Cr equity
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from generator.seeds import read_seed

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


def rate_usage(cfg, customers, usage):
    """Invoice amount per customer-month, rated exactly like int_usage_rated_monthly."""
    price = {p["product_id"]: Decimal(p["list_price_per_hour"]) for p in cfg["products"]}
    tiers = sorted(((t["min_hours_month"], Decimal(t["discount_pct"])) for t in cfg["volume_tiers"]), reverse=True)
    hours = defaultdict(Decimal)
    for u in usage:
        hours[(u["usage_date"].replace(day=1), u["customer_id"], u["product_id"])] += u["audio_hours"]
    customer_hours = defaultdict(Decimal)
    for (m, c, _), h in hours.items():
        customer_hours[(m, c)] += h
    invoices = defaultdict(Decimal)
    for (m, c, p), h in hours.items():
        discount = next(d for floor, d in tiers if customer_hours[(m, c)] >= floor)
        invoices[(m, c)] += _cents(h * price[p] * (1 - discount))
    return invoices


def build_ledger(cfg, customers, usage, lifecycle, cloud_costs, bills, bill_lines, pay_lines, employees, rng):
    end = cfg["window"]["end"]
    gl = Ledger()
    segment = {c["customer_id"]: c["segment"] for c in customers}
    fees = {f["segment"]: f for f in read_seed("payment_fee_schedule")}
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
    for (month, cid), amount in sorted(rate_usage(cfg, customers, usage).items()):
        if amount == 0:
            continue
        inv_date = _month_end(month)
        ref = f"INV-{cid}-{month:%Y%m}"
        dims = {"customer_id": cid}
        gl.post(inv_date, "revenue", f"Usage invoice {cid} {month:%Y-%m}",
                [("1200", amount, 0, dims), ("4000", 0, amount, dims)], ref)
        lo, hi = cfg["collections_days"][segment[cid]]
        paid = inv_date + timedelta(days=rng.randint(lo, hi))
        if paid > end or (cid, month) in uncollectible:
            continue
        gl.post(paid, "collection", f"Payment {ref}", [("1000", amount, 0, dims), ("1200", 0, amount, dims)], ref)
        f = fees[segment[cid]]
        fee = _cents(amount * Decimal(f["fee_pct"]) + Decimal(f["fee_fixed"]))
        if f["fee_cap"]:
            fee = min(fee, Decimal(f["fee_cap"]))
        gl.post(paid, "payment_fee", f"Processing fee {ref}", [("5100", fee, 0, dims), ("1000", 0, fee, dims)], ref)

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
    by_run_dept = defaultdict(lambda: [Decimal(0), Decimal(0), Decimal(0)])
    for p in pay_lines:
        t = by_run_dept[(p["pay_run_id"], p["department_id"])]
        t[0] += p["gross_pay"]; t[1] += p["employer_tax"]; t[2] += p["benefits"]
    for (run, dept), (gross, tax, ben) in sorted(by_run_dept.items()):
        y, m = int(run[3:7]), int(run[7:9])
        dims = {"department_id": dept}
        gl.post(_month_end(date(y, m, 1)), "payroll", f"Payroll {run} {dept}",
                [("6000", gross, 0, dims), ("6010", tax, 0, dims), ("6020", ben, 0, dims),
                 ("1000", 0, gross + tax + ben, dims)], run)

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

    return gl.entries, gl.lines
