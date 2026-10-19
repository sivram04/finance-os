"""Google Cloud's detailed billing export (raw_gcp.gcp_billing_export_v1), in the shape Google writes it.

One row per project × service × SKU × hour, with Google's nested fields: service{id, description},
sku{id, description}, project{id, number, name, labels[]}, labels[] (key/value), location{...}, usage{amount,
unit, amount_in_pricing_units, pricing_unit}, credits[] (name, amount, full_name, id, type), invoice{month}, cost
(FLOAT64, 6 places), cost_type, export_time. Untagged resources have no labels, as in a real export.

The export is the vendor's meter, so it ties to the vendor's invoice, not to our own logs: for every invoice
month, sum(cost) + sum(credits) equals each GCP bill line (GPU usage, cloud services) to the cent. Hours are
spread with a daily usage curve weighted by our cost lines and L4 job logs. Compute Engine VM SKUs carry a
sustained-use discount credit (gross cost is shown in `cost`, the discount in `credits`), as Google bills them.
"""
import hashlib
import math
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

BILLING_ACCOUNT = "01A2B3-C4D5E6-F7G8H9"
PROJECTS = {"prod": ("echo-labs-prod", 418309207645), "dev": ("echo-labs-dev", 418309207646), None: ("echo-labs-shared", 418309207647)}
SERVICES = {"Cloud Storage": "95FF-2EF5-5EA1", "Networking": "E505-1604-58F8", "Cloud Logging": "5490-F7B7-8DF6",
            "Compute Engine": "6F81-5844-456A"}
USAGE_UNIT = {"Cloud Storage": ("byte-seconds", "gibibyte month", 1 / (2 ** 30 * 730 * 3600)),
              "Networking": ("bytes", "gibibyte", 1 / 2 ** 30), "Cloud Logging": ("bytes", "gibibyte", 1 / 2 ** 30),
              "Compute Engine": ("seconds", "hour", 1 / 3600)}
SUD_RATE = Decimal("0.20")  # sustained-use discount on Compute Engine VM cores (not GPUs)
SIX = Decimal("0.000001")


def _id(text):
    h = hashlib.sha256(text.encode()).hexdigest().upper()
    return f"{h[:4]}-{h[4:8]}-{h[8:12]}"


def _hour_weights():
    """Diurnal usage curve (UTC): busier in US business hours."""
    w = [1 + 0.6 * math.sin((h - 9) / 24 * 2 * math.pi) for h in range(24)]
    s = sum(w)
    return [Decimal(str(x / s)) for x in w]


HOURS = _hour_weights()


def _spread(amount, weights):
    """Split amount (Decimal) across weights at 6 places, remainder on the largest share: exact total."""
    parts = [(amount * w).quantize(SIX, ROUND_HALF_UP) for w in weights]
    if parts:
        i = max(range(len(weights)), key=lambda k: weights[k])
        parts[i] += amount - sum(parts)
    return parts


def _row(hour_start, service, sku, team, env, cost, credit, usage_amount):
    project_id, project_number = PROJECTS.get(env, PROJECTS[None])
    unit, pricing_unit, to_pricing = USAGE_UNIT.get(service, ("seconds", "hour", 1 / 3600))
    labels = [{"key": "team", "value": team}, {"key": "env", "value": env}] if team else []
    month = hour_start.strftime("%Y%m")
    credits = [{"name": "Sustained Usage Discount", "amount": float(credit), "full_name": None,
                "id": f"SUD-{_id(sku)}", "type": "SUSTAINED_USAGE_DISCOUNT"}] if credit else []
    return {
        "billing_account_id": BILLING_ACCOUNT,
        "service": {"id": SERVICES.get(service, _id(service)), "description": service},
        "sku": {"id": _id(service + sku), "description": sku},
        "usage_start_time": hour_start.isoformat(),
        "usage_end_time": (hour_start + timedelta(hours=1)).isoformat(),
        "project": {"id": project_id, "number": str(project_number), "name": project_id,
                    "labels": [{"key": "cost-center", "value": "echo-labs"}],
                    "ancestry_numbers": "/615284970111/"},
        "labels": labels,
        "system_labels": [],
        "location": {"location": "us-central1", "country": "US", "region": "us-central1", "zone": None},
        "export_time": (hour_start + timedelta(hours=7)).isoformat(),
        "cost": float(cost),
        "currency": "USD",
        "currency_conversion_rate": 1.0,
        "usage": {"amount": round(usage_amount, 3), "unit": unit,
                  "amount_in_pricing_units": round(usage_amount * to_pricing, 6), "pricing_unit": pricing_unit},
        "credits": credits,
        "invoice": {"month": month, "publisher_type": "GOOGLE"},
        "cost_type": "regular",
        "transaction_type": "GOOGLE",
        "seller_name": "Google",
    }


def build_gcp_export(gcp_bill_lines, cloud_costs, gpu_jobs):
    """gcp_bill_lines: {month (date, 1st): {"gpu_usage": Decimal, "cloud_services": Decimal}} from the GCP bills.
    cloud_costs: daily cost lines (usage_date, service, sku, label_team, label_env, cost); gpu_jobs: job logs
    (job_date, gpu_type, gpu_seconds, label_team, label_env). Returns export rows for those bill months."""
    rows = []
    cloud_by_month = defaultdict(list)
    for c in cloud_costs:
        cloud_by_month[c["usage_date"].replace(day=1)].append(c)
    l4_by_day = defaultdict(int)
    for j in gpu_jobs:
        if j["gpu_type"] == "L4":
            l4_by_day[j["job_date"]] += int(j["gpu_seconds"])
    for month, lines in sorted(gcp_bill_lines.items()):
        # cloud services: each (day, line) weighted by its cost, then by the hour curve
        items = [c for c in cloud_by_month[month] if c["cost"] > 0]
        target = Decimal(lines.get("cloud_services", 0))
        if items and target:
            weights = []
            total = sum(Decimal(c["cost"]) for c in items)
            for c in items:
                for h in HOURS:
                    weights.append(Decimal(c["cost"]) / total * h)
            nets = _spread(target, weights)
            k = 0
            for c in items:
                day = datetime.combine(c["usage_date"], time(), tzinfo=timezone.utc)
                vm = c["service"] == "Compute Engine"
                for h in range(24):
                    net = nets[k]
                    k += 1
                    gross = (net / (1 - SUD_RATE)).quantize(SIX, ROUND_HALF_UP) if vm else net
                    usage = float(net) * 3600 * 4 if vm else float(net) * 2 ** 30 * 8
                    rows.append(_row(day + timedelta(hours=h), c["service"], c["sku"], c["label_team"], c["label_env"],
                                     gross, net - gross, usage))
        # GPU: L4 seconds per day from our job logs, by hour
        days = sorted(d for d in l4_by_day if d.replace(day=1) == month)
        target = Decimal(lines.get("gpu_usage", 0))
        if days and target:
            secs = sum(l4_by_day[d] for d in days)
            weights = [Decimal(l4_by_day[d]) / secs * h for d in days for h in HOURS]
            nets = _spread(target, weights)
            k = 0
            for d in days:
                day = datetime.combine(d, time(), tzinfo=timezone.utc)
                for h in range(24):
                    rows.append(_row(day + timedelta(hours=h), "Compute Engine", "Nvidia L4 GPU running in Americas",
                                     "infra", "prod", nets[k], Decimal(0), float(weights[k] * secs)))
                    k += 1
    return rows


def gcp_bill_lines(bills, bill_lines):
    """{month: {line_type: amount}} for the GCP bills."""
    month_of = {b["bill_id"]: b["service_month"] for b in bills if b["vendor_id"] == "gcp"}
    out = defaultdict(lambda: defaultdict(Decimal))
    for l in bill_lines:
        if l["bill_id"] in month_of:
            out[month_of[l["bill_id"]]][l["line_type"]] += Decimal(l["amount"])
    return out
