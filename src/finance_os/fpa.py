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


RUNWAY_HORIZON = 60  # months the engine looks ahead to find when cash runs out


def stress_test(base, levers, months=24):
    """The driver engine: month-by-month revenue, costs and cash under a set of levers, from the last closed month.
    Every forward-looking number (scenario forecast, runway, sensitivity grid, stress test, forecast snapshots) comes
    from this one function, so a scenario has one runway everywhere: the months until projected cash goes below zero
    (looked for over RUNWAY_HORIZON months; None = not within it).

    base: start_month (YYYY-MM), mrr, services, cash, cogs_pct, existing_net_monthly (net change of existing customers'
          revenue per month, trailing 6 months), self_serve_new_mrr (per month), pipeline [{close_month, arr, prob}],
          bookings_arr_monthly (historical sales-led ARR won per month), payroll [per month], other_opex [per month],
          payroll_now.
    levers (all optional, 0 = baseline): nrr_pts (annual NRR change, e.g. -0.05), win_rate_pct (e.g. -0.2 = 20% fewer
          wins), cycle_days (+30 = deals close a month later), price_pct (applies to all usage revenue), cogs_pts
          (cost to serve as share of revenue), hiring_pct (share of planned new payroll that happens, 1 = plan),
          opex_pct (other opex change), opex_growth_monthly (when set, other opex grows from today's run rate at this
          rate instead of following the plan), services_pct (services revenue change), raise_amount and raise_month (YYYY-MM).
    New sales-led customers ramp usage over three months (1/3, 2/3, full) starting the month after close.
    """
    lv = {"nrr_pts": 0.0, "win_rate_pct": 0.0, "cycle_days": 0, "price_pct": 0.0, "cogs_pts": 0.0, "hiring_pct": 1.0,
          "opex_pct": 0.0, "opex_growth_monthly": None, "services_pct": 0.0, "raise_amount": 0.0, "raise_month": None, **{k: v for k, v in (levers or {}).items() if v is not None}}
    shown, months = months, max(months, RUNWAY_HORIZON)
    y, m = int(base["start_month"][:4]), int(base["start_month"][5:7])
    labels = []
    for i in range(1, months + 1):
        mm = m - 1 + i
        labels.append(f"{y + mm // 12:04d}-{mm % 12 + 1:02d}")
    idx = {lab: i for i, lab in enumerate(labels)}
    shift = round(lv["cycle_days"] / 30)
    win = max(0.0, 1 + lv["win_rate_pct"])
    new_arr = [0.0] * months  # sales-led ARR booked per month
    last_pipe = base["start_month"]
    for o in base["pipeline"]:
        cm = o["close_month"]
        if cm <= base["start_month"]:  # slipped deals: assume they close next month at half the odds
            cm, p = labels[0], o["prob"] * 0.5
        else:
            p = o["prob"]
        last_pipe = max(last_pipe, cm)
        j = idx.get(cm)
        if j is not None and j + shift < months:
            new_arr[max(0, j + shift)] += o["arr"] * min(1.0, p * win)
    for lab in labels:  # beyond the open pipeline, the historical bookings rate
        if lab > last_pipe and idx[lab] + shift < months:
            new_arr[idx[lab] + shift] += base["bookings_arr_monthly"] * win
    monthly_net = (1 + base["existing_net_monthly"]) * (1 + lv["nrr_pts"]) ** (1 / 12) - 1
    existing, cash = base["mrr"], base["cash"]
    rows, cohort = [], []
    for i, lab in enumerate(labels):
        existing *= 1 + monthly_net
        existing += base["self_serve_new_mrr"]
        cohort.append(new_arr[i] / 12)
        sales_led = sum(c * min(1.0, (i - k) / 3) for k, c in enumerate(cohort) if i - k >= 1)
        usage = (existing + sales_led) * (1 + lv["price_pct"])
        revenue = usage + base["services"] * (1 + lv["services_pct"])
        cogs = revenue * (base["cogs_pct"] + lv["cogs_pts"])
        planned = base["payroll"][min(i, len(base["payroll"]) - 1)]
        payroll = base["payroll_now"] + (planned - base["payroll_now"]) * lv["hiring_pct"]
        if lv["opex_growth_monthly"] is None:
            opex_other = base["other_opex"][min(i, len(base["other_opex"]) - 1)] * (1 + lv["opex_pct"])
        else:
            opex_other = base["other_opex_now"] * (1 + lv["opex_growth_monthly"]) ** (i + 1) * (1 + lv["opex_pct"])
        ebitda = revenue - cogs - payroll - opex_other
        financing = lv["raise_amount"] if lv["raise_month"] == lab else 0.0
        cash += ebitda + financing
        cash_no_raise = (rows[-1]["cash_no_raise"] if rows else base["cash"]) + ebitda
        rows.append({"month": lab, "revenue": round(revenue, 2), "arr": round(usage * 12, 2), "new_arr_booked": round(new_arr[i], 2),
                     "cogs": round(cogs, 2), "payroll": round(payroll, 2), "other_opex": round(opex_other, 2),
                     "ebitda": round(ebitda, 2), "financing": financing, "cash": round(cash, 2),
                     "cash_no_raise": round(cash_no_raise, 2)})
    out = next((i for i, r in enumerate(rows) if r["cash"] < 0), None)
    out_month = rows[out]["month"] if out is not None else None
    out_nr = next((i for i, r in enumerate(rows) if r["cash_no_raise"] < 0), None)
    full, rows = rows, rows[:shown]
    return {"rows": rows, "levers": lv, "summary": {
        "revenue_12m": round(sum(r["revenue"] for r in rows[:12]), 2), "ebitda_12m": round(sum(r["ebitda"] for r in rows[:12]), 2),
        "arr_end": rows[-1]["arr"], "arr_12m": rows[min(11, months - 1)]["arr"], "min_cash": min(r["cash"] for r in rows),
        "cash_end": rows[-1]["cash"], "cash_out_month": out_month,
        "runway_months": out + 1 if out is not None else None,
        "runway_months_no_raise": out_nr + 1 if out_nr is not None else None,
        "cash_out_month_no_raise": full[out_nr]["month"] if out_nr is not None else None,
        "runway_horizon": RUNWAY_HORIZON,
        "first_ebitda_positive": next((r["month"] for r in full if r["ebitda"] > 0), None)}}


project = stress_test  # the driver engine by its general name
