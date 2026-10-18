"""Monthly vendor invoices (raw_erp), built from what the vendor meters, not from our models.

GPU usage is billed per GPU type at the seed rate on vendor-metered hours (job seconds ± metering noise).
A contract with committed GPU hours bills any shortfall below the commit at the committed type's rate.
GCP also bills the cloud service lines. M3 reconciles these invoices to the modeled cost within 1%.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from finance_os.generator.seeds import read_seed

CENTS = Decimal("0.01")


def _rate(rates, gpu_type, day):
    for r in rates:
        start = date.fromisoformat(r["effective_from"])
        end = date.fromisoformat(r["effective_to"]) if r["effective_to"] else date.max
        if r["gpu_type"] == gpu_type and start <= day <= end:
            return r["vendor_id"], Decimal(r["rate_per_gpu_hour"])
    raise KeyError((gpu_type, day))


def _next_month(m):
    return date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def build_vendor_bills(cfg, gpu_jobs, cloud_costs, rng):
    rates = read_seed("gpu_rates")
    contracts = {c["vendor_id"]: c for c in read_seed("vendor_contracts")}
    noise = Decimal(cfg["vendor_billing"]["metering_noise_pct"])

    # (vendor, month, gpu_type) -> [seconds, rate]; rate is constant within a month in the seed
    gpu = defaultdict(lambda: [0, None])
    for j in gpu_jobs:
        month = j["job_date"].replace(day=1)
        vendor, rate = _rate(rates, j["gpu_type"], j["job_date"])
        key = (vendor, month, j["gpu_type"])
        gpu[key][0] += j["gpu_seconds"]
        gpu[key][1] = rate

    cloud = defaultdict(Decimal)
    for c in cloud_costs:
        cloud[c["usage_date"].replace(day=1)] += c["cost"]

    lines = []
    for (vendor, month, gpu_type), (seconds, rate) in sorted(gpu.items()):
        factor = 1 + noise * Decimal(rng.randint(-100, 100)) / 100
        hours = (Decimal(seconds) / 3600 * factor).quantize(Decimal("0.0001"))
        lines.append((vendor, month, "gpu_usage", gpu_type, hours, (hours * rate).quantize(CENTS)))

    for month, cost in sorted(cloud.items()):
        factor = 1 + noise / 2 * Decimal(rng.randint(-100, 100)) / 100
        lines.append(("gcp", month, "cloud_services", None, None, (cost * factor).quantize(CENTS)))

    for vendor, c in contracts.items():
        if not c["committed_gpu_hours_month"]:
            continue
        committed = Decimal(c["committed_gpu_hours_month"])
        start = date.fromisoformat(c["start_date"])
        end = date.fromisoformat(c["end_date"]) if c["end_date"] else date.max
        months = sorted({m for (v, m, t) in gpu if v == vendor and start <= m <= end})
        for month in months:
            used = next((h for (v, m, ln, t, h, a) in lines
                         if v == vendor and m == month and ln == "gpu_usage" and t == c["committed_gpu_type"]), Decimal(0))
            if used < committed:
                _, rate = _rate(rates, c["committed_gpu_type"], month)
                short = committed - used
                lines.append((vendor, month, "commit_shortfall", c["committed_gpu_type"], short, (short * rate).quantize(CENTS)))

    bills, bill_lines, totals = [], [], defaultdict(Decimal)
    for vendor, month, line_type, gpu_type, hours, amount in lines:
        bill_id = f"BILL-{vendor.upper()}-{month:%Y%m}"
        totals[(bill_id, vendor, month)] += amount
        bill_lines.append({"bill_id": bill_id, "line_type": line_type, "gpu_type": gpu_type,
                           "quantity_hours": hours, "amount": amount})
    for (bill_id, vendor, month), total in sorted(totals.items()):
        bill_date = _next_month(month).replace(day=cfg["vendor_billing"]["bill_day"])
        bills.append({"bill_id": bill_id, "vendor_id": vendor, "service_month": month,
                      "bill_date": bill_date, "total_amount": total})
    return bills, bill_lines
