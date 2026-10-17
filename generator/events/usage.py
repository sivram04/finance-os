"""Daily audio hours per customer and product.

Monthly volume = start_hours × (1 + growth)^months_since_signup × seasonality,
spread over days with weekday weighting and noise. Hours are Decimal to 4 dp.
"""
from datetime import timedelta
from decimal import Decimal

# Mild seasonality: December dip, Q1 ramp.
SEASONALITY = {1: "1.02", 2: "1.00", 3: "1.04", 4: "1.00", 5: "1.00", 6: "0.98",
               7: "0.96", 8: "0.95", 9: "1.01", 10: "1.03", 11: "1.00", 12: "0.90"}
HOURS_DP = Decimal("0.0001")


def build_usage(cfg, customers, mixes, rng):
    end = cfg["window"]["end"]
    mix_by_customer = {}
    for m in mixes:
        mix_by_customer.setdefault(m["customer_id"], []).append(m)

    rows = []
    for c in customers:
        day = c["signup_date"]
        while day <= end:
            months = (day.year - c["signup_date"].year) * 12 + day.month - c["signup_date"].month
            monthly = Decimal(c["start_hours_month"]) * (1 + c["monthly_growth"]) ** months
            monthly *= Decimal(SEASONALITY[day.month])
            weekday_weight = Decimal("1.15") if day.weekday() < 5 else Decimal("0.60")
            noise = Decimal(rng.randint(85, 115)) / Decimal(100)
            daily = monthly / Decimal(30) * weekday_weight * noise
            for m in mix_by_customer[c["customer_id"]]:
                hours = (daily * m["share"]).quantize(HOURS_DP)
                if hours > 0:
                    rows.append({
                        "usage_date": day,
                        "customer_id": c["customer_id"],
                        "product_id": m["product_id"],
                        "audio_hours": hours,
                    })
            day += timedelta(days=1)
    return rows
