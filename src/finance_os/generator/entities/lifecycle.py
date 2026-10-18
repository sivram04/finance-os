"""Customer lifecycle events (raw_synth.lifecycle_events).

Random per-customer monthly draws after signup: churn (voluntary or involuntary = payment failed),
expansion and contraction. Involuntary churners may come back (reactivation). After a churn, no more
random events. Scripted events (named situations) and market events (e.g. a competitor price cut hitting
one segment) are added on top. Usage applies these; the warehouse measures their effect from revenue,
never from this table, so detection is real.
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

VOLUNTARY_REASONS = ["switched_to_competitor", "built_in_house", "project_ended", "price"]


def _rand_between(rng, lo, hi):
    lo, hi = Decimal(lo), Decimal(hi)
    return (lo + (hi - lo) * Decimal(rng.randint(0, 100)) / 100).quantize(Decimal("0.01"))


def build_lifecycle(cfg, customers, mixes, rng):
    lc = cfg["lifecycle"]
    end = cfg["window"]["end"]
    events = []

    def add(cid, d, etype, mult, reason, source):
        events.append({"customer_id": cid, "event_date": d, "event_type": etype,
                       "multiplier": Decimal(mult), "reason": reason, "source": source})

    for c in customers:
        seg, cid = c["segment"], c["customer_id"]
        y, m = c["signup_date"].year, c["signup_date"].month
        y, m = y + (m == 12), m % 12 + 1  # first full month after signup
        while date(y, m, 1) <= end:
            day = date(y, m, rng.randint(1, calendar.monthrange(y, m)[1]))
            draw = Decimal(rng.randint(0, 9999)) / 10000
            churn_p = Decimal(lc["churn_prob_monthly"][seg])
            exp_p = Decimal(lc["expansion_prob_monthly"][seg])
            con_p = Decimal(lc["contraction_prob_monthly"][seg])
            if draw < churn_p and day <= end:
                involuntary = Decimal(rng.randint(0, 9999)) / 10000 < Decimal(lc["involuntary_share"][seg])
                add(cid, day, "churn", 0, "payment_failed" if involuntary else rng.choice(VOLUNTARY_REASONS), "random")
                if involuntary and Decimal(rng.randint(0, 9999)) / 10000 < Decimal(lc["reactivation_prob"]):
                    back = day + timedelta(days=30 * rng.randint(*lc["reactivation_months"]))
                    if back <= end:
                        add(cid, back, "reactivation", 1, "win_back", "random")
                break
            elif draw < churn_p + exp_p:
                add(cid, day, "expansion", _rand_between(rng, *lc["expansion_multiplier"]), "organic_growth", "random")
            elif draw < churn_p + exp_p + con_p:
                add(cid, day, "contraction", _rand_between(rng, *lc["contraction_multiplier"]), "optimization", "random")
            y, m = y + (m == 12), m % 12 + 1

    for e in cfg.get("scripted_events", []):
        add(e["customer_id"], e["date"], e["event_type"], e["multiplier"], e["reason"], "scripted")

    base_share = {m["customer_id"]: m["share"] for m in mixes if m["product_id"] == "batch_base"}
    for me in cfg.get("market_events", []):
        for c in customers:
            if (c["segment"] == me["segment"] and c["signup_date"] < me["date"]
                    and base_share.get(c["customer_id"], 0) >= Decimal(me["min_base_share"])):
                add(c["customer_id"], me["date"], me["event_type"], me["multiplier"], me["reason"], "market")

    events.sort(key=lambda e: (e["customer_id"], e["event_date"], e["event_type"]))
    for i, e in enumerate(events, 1):
        e["event_id"] = f"LC{i:05d}"
    return [{"event_id": e.pop("event_id"), **e} for e in events]


class CustomerState:
    """Answers, for one customer on one day: is it active, and by how much is usage scaled?"""

    def __init__(self, events):
        self.events = sorted(events, key=lambda e: e["event_date"])

    def active(self, day):
        on = True
        for e in self.events:
            if e["event_date"] > day:
                break
            if e["event_type"] == "churn":
                on = False
            elif e["event_type"] == "reactivation":
                on = True
        return on

    def multiplier(self, day):
        mult = Decimal(1)
        for e in self.events:
            if e["event_date"] > day:
                break
            if e["event_type"] in ("expansion", "contraction"):
                mult *= e["multiplier"]
            elif e["event_type"] == "spike" and (e["event_date"].year, e["event_date"].month) == (day.year, day.month):
                mult *= e["multiplier"]
        return mult
