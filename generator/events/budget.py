"""Annual budgets (raw_erp.budgets) by fiscal year × month × department × GL account.

Built the way a finance team builds a plan, never from the budgeted year's actuals:
- Revenue: FY2025 from a planned January figure and monthly growth; FY2026 from the run-rate of the
  base month (Q4 2025) grown at an optimistic rate.
- COGS: planned revenue × (1 − planned gross margin), split across COGS accounts.
- Payroll: the headcount plan (linear from start to end count, extended past the window at the same
  pace) × salary midpoint, plus employer tax and benefits.
- Opex: the monthly opex lines scaled by planned headcount; R&D cloud as a flat monthly amount.
Departments match how the GL posts: revenue and payment fees carry no department ('NONE').
"""
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def _cents(x):
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def _months(year):
    return [date(year, m, 1) for m in range(1, 13)]


def _month_index(cfg, month):
    start = cfg["window"]["start"]
    return (month.year - start.year) * 12 + month.month - start.month


def build_budgets(cfg, journal_entries, journal_lines):
    b = cfg["budget"]
    rows = []

    def add(fy, month, dept, account, amount):
        rows.append({"fiscal_year": fy, "month": month, "department_id": dept, "account_id": account,
                     "version": "original", "amount": _cents(amount)})

    # Actual revenue by month, only for the FY2026 base month (planned in Q4 2025).
    entry_month = {e["entry_id"]: e["entry_date"].replace(day=1) for e in journal_entries}
    actual_rev = defaultdict(Decimal)
    for l in journal_lines:
        if l["account_id"] == "4000":
            actual_rev[entry_month[l["entry_id"]]] += Decimal(l["credit"]) - Decimal(l["debit"])

    total_months = _month_index(cfg, cfg["window"]["end"])  # months from first to last in the window
    tax = Decimal(cfg["payroll"]["employer_tax_pct"])
    benefits = Decimal(cfg["payroll"]["benefits_per_month"])

    def planned_headcount(plan, month):
        return Decimal(plan["start"]) + Decimal(plan["end"] - plan["start"]) * _month_index(cfg, month) / total_months

    base_headcount = sum(p["start"] for p in cfg["headcount_plan"])

    for fy, key in ((2025, "fy2025"), (2026, "fy2026")):
        plan = b[key]
        growth = Decimal(plan["revenue_growth"])
        if fy == 2025:
            base, base_month = Decimal(plan["revenue_start"]), date(2025, 1, 1)
        else:
            base_month = plan["revenue_base_month"]
            base = actual_rev[base_month]
        for month in _months(fy):
            steps = (month.year - base_month.year) * 12 + month.month - base_month.month
            revenue = base * (1 + growth) ** steps
            add(fy, month, "NONE", "4000", revenue)

            cogs = revenue * (1 - Decimal(plan["gross_margin_pct"]))
            for account, share in b["cogs_split"].items():
                add(fy, month, "INF" if account in ("5000", "5010") else "NONE", account, cogs * Decimal(share))

            by_dept = defaultdict(lambda: [Decimal(0), Decimal(0)])  # dept -> [salary, headcount]
            for p in cfg["headcount_plan"]:
                hc = planned_headcount(p, month)
                mid = Decimal(sum(p["salary"])) / 2
                by_dept[p["department"]][0] += hc * mid / 12
                by_dept[p["department"]][1] += hc
            for dept, (salary, hc) in sorted(by_dept.items()):
                add(fy, month, dept, "6000", salary)
                add(fy, month, dept, "6010", salary * tax)
                add(fy, month, dept, "6020", hc * benefits)

            total_hc = sum(hc for _, hc in by_dept.values())
            scale = total_hc / base_headcount
            for o in cfg["opex_monthly"]:
                add(fy, month, o["department"], o["account"], Decimal(o["amount"]) * scale)
            add(fy, month, "ENG", "6100", Decimal(b["rd_cloud_monthly"][key]))

    # Several opex lines can share a department × account (e.g. SaaS in ENG and GA are different depts,
    # but guard anyway): collapse to one row per key.
    merged = defaultdict(Decimal)
    for r in rows:
        merged[(r["fiscal_year"], r["month"], r["department_id"], r["account_id"], r["version"])] += r["amount"]
    return [{"fiscal_year": k[0], "month": k[1], "department_id": k[2], "account_id": k[3], "version": k[4],
             "amount": v} for k, v in sorted(merged.items())]
