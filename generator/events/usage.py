"""Daily audio hours and API requests per customer and product.

Monthly volume = start_hours × (1 + growth)^months_since_signup × seasonality,
spread over days with weekday weighting and noise. Hours are Decimal to 4 dp.
A streaming_shift anomaly replaces a customer's product mix from its start date. Lifecycle events
stop usage while a customer is churned and scale it for expansion, contraction and one-off spikes.
"""
from datetime import timedelta
from decimal import Decimal

from generator.entities.lifecycle import CustomerState

# Mild seasonality: December dip, Q1 ramp.
SEASONALITY = {1: "1.02", 2: "1.00", 3: "1.04", 4: "1.00", 5: "1.00", 6: "0.98",
               7: "0.96", 8: "0.95", 9: "1.01", 10: "1.03", 11: "1.00", 12: "0.90"}
HOURS_DP = Decimal("0.0001")


def build_usage(cfg, customers, mixes, lifecycle, rng):
    end = cfg["window"]["end"]
    workload = {p["product_id"]: p["workload"] for p in cfg["products"]}
    mix_by_customer = {}
    for m in mixes:
        mix_by_customer.setdefault(m["customer_id"], []).append((m["product_id"], m["share"]))
    shifts = {a["customer_id"]: a for a in cfg.get("anomalies", []) if a["kind"] == "streaming_shift"}
    events_by_customer = {}
    for e in lifecycle:
        events_by_customer.setdefault(e["customer_id"], []).append(e)

    rows = []
    for c in customers:
        cid = c["customer_id"]
        state = CustomerState(events_by_customer.get(cid, []))
        day = c["signup_date"]
        while day <= end:
            if not state.active(day):
                day += timedelta(days=1)
                continue
            months = (day.year - c["signup_date"].year) * 12 + day.month - c["signup_date"].month
            monthly = Decimal(c["start_hours_month"]) * (1 + c["monthly_growth"]) ** months
            monthly *= Decimal(SEASONALITY[day.month])
            weekday_weight = Decimal("1.15") if day.weekday() < 5 else Decimal("0.60")
            noise = Decimal(rng.randint(85, 115)) / Decimal(100)
            daily = monthly / Decimal(30) * weekday_weight * noise * state.multiplier(day)

            mix = mix_by_customer[cid]
            if cid in shifts and day >= shifts[cid]["start"]:
                mix = [(p, Decimal(s)) for p, s in shifts[cid]["mix"].items()]

            for product_id, share in mix:
                hours = (daily * share).quantize(HOURS_DP)
                if hours > 0:
                    lo, hi = cfg["requests_per_hour"][workload[product_id]]
                    rph = Decimal(rng.randint(lo * 100, hi * 100)) / Decimal(100)
                    rows.append({
                        "usage_date": day,
                        "customer_id": cid,
                        "product_id": product_id,
                        "audio_hours": hours,
                        "requests": max(1, int(hours * rph)),
                    })
            day += timedelta(days=1)
    return rows
