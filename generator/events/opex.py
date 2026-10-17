"""Monthly support and success cost pools (raw_erp). Placeholder until payroll exists."""
from datetime import date
from decimal import Decimal

CENTS = Decimal("0.01")


def build_opex_pools(cfg):
    start, end = cfg["window"]["start"], cfg["window"]["end"]
    rows = []
    for pool, spec in cfg["opex_pools"].items():
        y, m, i = start.year, start.month, 0
        while date(y, m, 1) <= end:
            amount = Decimal(spec["start_month_amount"]) * (1 + Decimal(spec["monthly_growth"])) ** i
            rows.append({"month": date(y, m, 1), "pool": pool, "amount": amount.quantize(CENTS)})
            y, m, i = y + (m == 12), m % 12 + 1, i + 1
    return rows
