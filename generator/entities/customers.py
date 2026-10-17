"""Usage customers in three segments, each with its own workload mix."""
from datetime import timedelta
from decimal import Decimal

SEGMENT_PREFIX = {"self_serve": "SS", "mid_market": "MM", "enterprise": "EN"}

# Share of hours per product. Enterprise leans pro/streaming; self-serve leans base.
MIX_CHOICES = {
    "self_serve": [{"batch_base": "1.00"}, {"batch_base": "0.70", "batch_pro": "0.30"}, {"batch_base": "0.60", "stream": "0.40"}],
    "mid_market": [{"batch_base": "0.50", "batch_pro": "0.50"}, {"batch_pro": "0.60", "stream": "0.40"}, {"batch_base": "0.30", "batch_pro": "0.30", "stream": "0.40"}],
    "enterprise": [{"batch_pro": "0.70", "stream": "0.30"}, {"batch_pro": "0.40", "stream": "0.60"}],
}


def build_customers(cfg, rng):
    start = cfg["window"]["start"]
    end = cfg["window"]["end"]
    span_days = (end - start).days
    customers, mixes = [], []
    for segment, spec in cfg["segments"].items():
        for i in range(1, spec["count"] + 1):
            cid = f"{SEGMENT_PREFIX[segment]}-{i:03d}"
            # Self-serve sign-ups spread through the window; larger accounts exist from the start or join in year one.
            if segment == "self_serve":
                signup = start + timedelta(days=rng.randint(0, int(span_days * 0.8)))
            elif segment == "mid_market":
                signup = start + timedelta(days=rng.randint(0, 270))
            else:
                signup = start
            lo, hi = spec["start_hours"]
            g_lo, g_hi = (Decimal(x) for x in spec["growth"])
            growth = g_lo + (g_hi - g_lo) * Decimal(rng.randint(0, 1000)) / Decimal(1000)
            customers.append({
                "customer_id": cid,
                "customer_name": f"{segment.replace('_', ' ').title()} Customer {i}",
                "segment": segment,
                "signup_date": signup,
                "start_hours_month": rng.randint(lo, hi),
                "monthly_growth": growth.quantize(Decimal("0.0001")),
            })
            for product_id, share in rng.choice(MIX_CHOICES[segment]).items():
                mixes.append({"customer_id": cid, "product_id": product_id, "share": Decimal(share)})
    return customers, mixes

