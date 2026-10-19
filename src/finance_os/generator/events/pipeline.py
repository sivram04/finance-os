"""Sales pipeline (raw_crm.opportunities): the CRM's view of sales-led deals, as a Salesforce/HubSpot opportunity
export would show it at the end of the window.

- Every mid-market and enterprise customer was a won opportunity: created a sales cycle before signup, closed on
  the signup date, sized from the customer's starting usage (ARR = start hours × blended price × 12 after tiers).
- Lost opportunities: about 2-3 per win, spread over the window, with a loss reason.
- Open pipeline: deals created in the last six months with an expected close date in the next two quarters, at
  a stage with its usual probability. A few have close dates already passed (slipped) so stale deals show up.
Self-serve customers sign up in the product and never appear here.
Its own random stream, so adding the CRM changes no other generated data.
"""
import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

STAGES = [("discovery", Decimal("0.10")), ("evaluation", Decimal("0.25")), ("proposal", Decimal("0.50")),
          ("negotiation", Decimal("0.75"))]
CYCLE_DAYS = {"mid_market": (45, 100), "enterprise": (120, 240)}
ARR_RANGE = {"mid_market": (60_000, 320_000), "enterprise": (600_000, 2_400_000)}
LOST_PER_WIN = {"mid_market": 2.6, "enterprise": 2.0}
LOSS_REASONS = ["price", "competitor", "no decision", "accuracy on our audio", "timing / budget", "security review"]
BLENDED_PRICE = Decimal("0.30")  # per audio hour, after volume tiers


def _rep(segment, n):
    return "AE-01" if segment == "enterprise" else ("AE-02" if n % 2 == 0 else "AE-03")


def _arr(amount):
    return (Decimal(amount) / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 1000  # CRMs hold round numbers


def build_pipeline(cfg, customers):
    rng = random.Random(cfg["seed"] + 41)
    start, end = cfg["window"]["start"], cfg["window"]["end"]
    opps, n = [], 0

    def add(**o):
        nonlocal n
        n += 1
        opps.append({"opportunity_id": f"OPP-{n:04d}", "customer_id": None, "loss_reason": None, **o})

    wins = [c for c in customers if c["segment"] in CYCLE_DAYS]
    for i, c in enumerate(sorted(wins, key=lambda c: c["signup_date"])):
        lo, hi = CYCLE_DAYS[c["segment"]]
        # customers already live when the history starts signed before it: their deal closed months earlier
        close = c["signup_date"] if c["signup_date"] > start else start - timedelta(days=rng.randint(20, 420))
        arr = _arr(Decimal(c["start_hours_month"]) * BLENDED_PRICE * 12)
        add(account_name=c["customer_name"], segment=c["segment"], rep_id=_rep(c["segment"], i),
            created_date=close - timedelta(days=rng.randint(lo, hi)), close_date=close, stage="closed_won",
            probability=Decimal("1.00"), amount_arr=arr, customer_id=c["customer_id"])

    span = (end - start).days
    for seg in CYCLE_DAYS:
        seg_wins = sum(1 for c in wins if c["segment"] == seg)
        lo, hi = CYCLE_DAYS[seg]
        for k in range(round(seg_wins * LOST_PER_WIN[seg]) + 2):
            close = start + timedelta(days=rng.randint(30, span))
            add(account_name=f"Prospect {seg[:3].upper()}-{n + 1:04d}", segment=seg, rep_id=_rep(seg, k),
                created_date=close - timedelta(days=rng.randint(lo, hi)), close_date=close, stage="closed_lost",
                probability=Decimal("0.00"), amount_arr=_arr(rng.uniform(*ARR_RANGE[seg]) * 0.8),
                loss_reason=rng.choice(LOSS_REASONS))
        # open pipeline at the end of the window: next two quarters, plus a few that already slipped
        for k in range({"mid_market": 14, "enterprise": 6}[seg]):
            stage, prob = rng.choices(STAGES, weights=[4, 3, 2, 1])[0]
            slipped = rng.random() < 0.15
            close = end - timedelta(days=rng.randint(5, 40)) if slipped else end + timedelta(days=rng.randint(10, 180))
            add(account_name=f"Prospect {seg[:3].upper()}-{n + 1:04d}", segment=seg, rep_id=_rep(seg, k),
                created_date=end - timedelta(days=rng.randint(20, 180)), close_date=close, stage=stage,
                probability=prob, amount_arr=_arr(rng.uniform(*ARR_RANGE[seg])))
    return opps
