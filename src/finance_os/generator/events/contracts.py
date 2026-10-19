"""Customer order forms (raw_crm.contracts, raw_crm.contract_schedule): the committed-use contracts behind sales-led
customers, as a CPQ / contract-management export shows them.

- Every mid-market and enterprise customer signs a committed-use contract when its deal closes, then renews back to
  back until it churns. Mid-market terms are 12 months; enterprise terms are 24 or 36 months with a ramp (the
  commitment steps up each contract year).
- Commitments are sized at about 80-90% of the usage the customer was expected to run (customers commit below what
  they expect to use, then pay overage above it): the billed run rate of the three months before signing (the CRM
  deal size for the first contract), grown at the customer's expected growth to the middle of each contract year.
  That growth path is the ramp: each contract year's commitment steps up.
- Billing model: 'commit_overage' (usage billed monthly in arrears, drawn against the year's commitment; any shortfall
  is trued up at the end of the contract year) or 'prepaid_credits' (the year's commitment is a credit pool drawn
  down by usage; unused credits expire at year end). Either way the year's commitment is owed, so it is contracted
  revenue (RPO) until usage consumes it.
- A customer that churns stops renewing; a contract live on the churn date is marked 'terminated'.
Its own random stream, so adding contracts changes no other generated data.
"""
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

BLENDED_PRICE = Decimal("0.30")  # per audio hour after volume tiers, as the CRM sizes deals
TERM_MONTHS = {"mid_market": [12], "enterprise": [24, 36]}


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1) if d.day == 1 else date(d.year + y, m + 1, min(d.day, 28))


def _round_k(x):
    return (Decimal(x) / 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 1000


def _month_key(d):
    return (d.year, d.month)


def build_contracts(cfg, customers, opportunities, lifecycle, billed):
    """billed: {(customer_id, (year, month)): usage amount invoiced for that month}."""
    rng = random.Random(cfg["seed"] + 53)
    end = cfg["window"]["end"]
    churned = {}
    for e in lifecycle:
        if e["event_type"] == "churn":
            churned.setdefault(e["customer_id"], e["event_date"])
    won = {o["customer_id"]: o for o in opportunities if o["stage"] == "closed_won" and o["customer_id"]}
    contracts, schedule = [], []
    for c in sorted(customers, key=lambda c: c["customer_id"]):
        seg, cid = c["segment"], c["customer_id"]
        if seg not in TERM_MONTHS or cid not in won:
            continue
        start = won[cid]["close_date"]
        growth = Decimal(str(c["monthly_growth"]))
        n = 0
        while start <= end and (cid not in churned or start <= churned[cid]):
            n += 1
            term = rng.choice(TERM_MONTHS[seg])
            stop = _add_months(start, term) - timedelta(days=1)
            trailing = [billed.get((cid, _month_key(_add_months(start.replace(day=1), -k)))) for k in (1, 2, 3)]
            trailing = [t for t in trailing if t]
            run_rate = (sum(trailing) / len(trailing) * 12 if len(trailing) == 3 else
                        Decimal(c["start_hours_month"]) * BLENDED_PRICE * 12)
            commit_pct = Decimal(rng.randint(80, 90)) / 100
            years = [_round_k(run_rate * (1 + growth) ** (12 * y + 6) * commit_pct) for y in range(term // 12)]
            model = "prepaid_credits" if seg == "enterprise" and rng.random() < 0.5 else "commit_overage"
            ended = churned.get(cid)
            status = ("terminated" if ended and start <= ended <= stop else
                      "active" if stop >= end else "renewed")
            contract_id = f"CTR-{cid}-{n:02d}"
            contracts.append({"contract_id": contract_id, "customer_id": cid, "segment": seg, "start_date": start,
                              "end_date": stop, "term_months": term, "billing_model": model,
                              "total_commitment": sum(years),
                              "renewal_of": f"CTR-{cid}-{n - 1:02d}" if n > 1 else None, "status": status,
                              "terminated_date": ended if status == "terminated" else None})
            for y, amount in enumerate(years, 1):
                p_start = _add_months(start, 12 * (y - 1))
                schedule.append({"contract_id": contract_id, "contract_year": y, "period_start": p_start,
                                 "period_end": _add_months(p_start, 12) - timedelta(days=1),
                                 "committed_amount": amount})
            start = stop + timedelta(days=1)
    return contracts, schedule
