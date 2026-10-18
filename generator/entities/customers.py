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
    # Customers named in scripted events or anomalies must exist well before their first event.
    story_dates = {}
    for e in cfg.get("scripted_events", []) + cfg.get("anomalies", []) + cfg.get("projects", []):
        cid = e.get("customer_id") or e.get("entity_id")
        when = e.get("date") or e.get("start")
        story_dates[cid] = min(story_dates.get(cid, when), when)
    for segment, spec in cfg["segments"].items():
        for i in range(1, spec["count"] + 1):
            cid = f"{SEGMENT_PREFIX[segment]}-{i:03d}"
            # Self-serve sign-ups keep coming through the whole window; mid-market is sold through most of it;
            # enterprise accounts exist from the start.
            if segment == "self_serve":
                signup = start + timedelta(days=rng.randint(0, span_days - 20))
            elif segment == "mid_market":
                signup = start + timedelta(days=rng.randint(0, int(span_days * 0.85)))
            else:
                signup = start
            if cid in story_dates:
                signup = min(signup, max(start, story_dates[cid] - timedelta(days=90)))
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

