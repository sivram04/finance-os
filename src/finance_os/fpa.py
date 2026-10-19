"""FP&A calculators that take a person's inputs, not just warehouse data: business cases (NPV / IRR / payback) and
sensitivity tables. The warehouse supplies the starting point (last closed month); the math is here so the
assistant, the API and the workbook all compute the same answer.
"""
DEFAULT_DISCOUNT_RATE = 0.15  # hurdle rate for a venture-backed company: well above the cost of debt


def npv(rate, flows):
    """flows[0] is today (usually the investment, negative); flows[t] is year t."""
    return sum(f / (1 + rate) ** t for t, f in enumerate(flows))


def irr(flows, lo=-0.99, hi=10.0):
    """Internal rate of return by bisection; None when the flows never change sign."""
    if not (any(f < 0 for f in flows) and any(f > 0 for f in flows)):
        return None
    f_lo, f_hi = npv(lo, flows), npv(hi, flows)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid, flows)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return mid


def payback(flows):
    """Years until cumulative cash turns positive (interpolated within the year); None if it never does."""
    cum = 0.0
    for t, f in enumerate(flows):
        if cum + f >= 0 and t > 0 and f > 0:
            return t - 1 + (-cum / f)
        cum += f
    return None


def business_case(investment, annual_inflows, discount_rate=DEFAULT_DISCOUNT_RATE, annual_costs=None, name="Business case"):
    """Evaluate spending `investment` today for `annual_inflows` (list, years 1..n) less optional `annual_costs`."""
    costs = annual_costs or [0] * len(annual_inflows)
    net = [float(i) - float(c) for i, c in zip(annual_inflows, costs)]
    flows = [-float(investment)] + net
    v, r, p = npv(discount_rate, flows), irr(flows), payback(flows)
    cum, rows = 0.0, []
    for t, f in enumerate(flows):
        cum += f
        rows.append({"year": t, "cash_flow": round(f, 2), "discounted": round(f / (1 + discount_rate) ** t, 2),
                     "cumulative": round(cum, 2)})
    verdict = ("Invest: it earns more than the hurdle rate." if v > 0 else
               "Don't invest at these assumptions: it destroys value at the hurdle rate.")
    return {"name": name, "discount_rate": discount_rate, "npv": round(v, 2), "irr": None if r is None else round(r, 4),
            "payback_years": None if p is None else round(p, 2), "verdict": verdict, "rows": rows}


def campaign_case(spend, new_customers, arpa_monthly, gross_margin, monthly_churn, years=3,
                  discount_rate=DEFAULT_DISCOUNT_RATE):
    """A marketing campaign: `spend` now buys `new_customers` paying `arpa_monthly`, decaying by `monthly_churn`."""
    inflows, alive = [], float(new_customers)
    for _ in range(years):
        year = 0.0
        for _m in range(12):
            year += alive * arpa_monthly * gross_margin
            alive *= 1 - monthly_churn
        inflows.append(year)
    out = business_case(spend, inflows, discount_rate, name="Marketing campaign")
    out["assumptions"] = {"new_customers": new_customers, "arpa_monthly": arpa_monthly, "gross_margin": gross_margin,
                          "monthly_churn": monthly_churn, "years": years}
    return out


def runway_sensitivity(start_cash, revenue, cogs_pct, opex, growth_deltas, opex_changes, base_growth, horizon=60):
    """Months of runway for each (monthly revenue growth, opex change) pair. Revenue compounds monthly; COGS is a
    share of revenue; opex is held at the changed level. 'horizon+' when cash never runs out within `horizon`."""
    table = []
    for g in growth_deltas:
        row = {"revenue_growth_monthly": round(base_growth + g, 4)}
        for o in opex_changes:
            cash, rev, months = start_cash, revenue, None
            for m in range(1, horizon + 1):
                rev *= 1 + base_growth + g
                cash += rev * (1 - cogs_pct) - opex * (1 + o)
                if cash < 0:
                    months = m
                    break
            row[f"opex {o:+.0%}"] = months if months is not None else f"{horizon}+"
        table.append(row)
    return table
