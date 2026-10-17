"""Monthly pay runs and pay lines (raw_payroll). Pay is prorated by days employed in the month."""
import calendar
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def _cents(x):
    return x.quantize(CENTS, rounding=ROUND_HALF_UP)


def build_payroll(cfg, employees):
    tax_pct = Decimal(cfg["payroll"]["employer_tax_pct"])
    benefits = Decimal(cfg["payroll"]["benefits_per_month"])
    start, end = cfg["window"]["start"], cfg["window"]["end"]

    runs, lines = [], []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        days = calendar.monthrange(y, m)[1]
        first, last = date(y, m, 1), date(y, m, days)
        run_id = f"PR-{y}{m:02d}"
        runs.append({"pay_run_id": run_id, "period_start": first, "period_end": last, "pay_date": last})
        for e in employees:
            active_from = max(e["hire_date"], first)
            active_to = min(e["termination_date"] or last, last)
            if active_from > active_to:
                continue
            factor = Decimal((active_to - active_from).days + 1) / Decimal(days)
            gross = _cents(e["annual_salary"] / 12 * factor)
            tax = _cents(gross * tax_pct)
            ben = _cents(benefits * factor)
            lines.append({
                "pay_run_id": run_id,
                "employee_id": e["employee_id"],
                "department_id": e["department_id"],
                "gross_pay": gross,
                "employer_tax": tax,
                "benefits": ben,
            })
        y, m = y + (m == 12), m % 12 + 1
    return runs, lines
