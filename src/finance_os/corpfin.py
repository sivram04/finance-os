"""Corporate finance formulas, kept pure so the warehouse tools, the calculators page and the tests share one version.

Company analysis: ratios and the DuPont identity, corporate income tax (marginal vs average, bands, loss carryforward),
percent-of-sales projection with external financing needed (EFN) and the internal / sustainable growth rates, project
cash flows (depreciation tax shield, salvage value after tax, working capital) with NPV, IRR, payback and discounted
payback, accounting / cash / financial break-even, and WACC with the cost of equity from CAPM.

Calculators (textbook): time value of money, annuities, perpetuities, loan amortization, bond price / yield to
maturity / interest-rate risk, dividend discount model, straight vs cumulative voting, CAPM and the security market
line, two-asset portfolio risk, arithmetic vs geometric returns, variance and standard deviation, M&M propositions,
homemade leverage, dividends vs repurchases, stock splits and stock dividends, flotation cost, rights offerings, bid
price and the crossover rate between two projects.
"""
from math import floor, sqrt

from finance_os.fpa import irr, npv, payback


def _r(x, n=4):
    return None if x is None else round(x, n)


# ---- ratios ---------------------------------------------------------------------------------------------------

def ratios(s):
    """s: revenue, cogs, ebit, ebitda, net_income, interest, depreciation, cash, receivables, current_assets,
    total_assets, current_liabilities, total_liabilities, equity, payables, (optional) shares, price, ttm flags."""
    div = lambda a, b: None if not b else a / b  # noqa: E731
    pm = div(s["net_income"], s["revenue"])
    tat = div(s["revenue"], s["total_assets"])
    em = div(s["total_assets"], s["equity"])
    out = {
        "liquidity": {"current_ratio": div(s["current_assets"], s["current_liabilities"]),
                      "quick_ratio": div(s["current_assets"] - s.get("inventory", 0), s["current_liabilities"]),
                      "cash_ratio": div(s["cash"], s["current_liabilities"])},
        "leverage": {"total_debt_ratio": div(s["total_liabilities"], s["total_assets"]),
                     "debt_equity": div(s["total_liabilities"], s["equity"]), "equity_multiplier": em,
                     "times_interest_earned": div(s["ebit"], s.get("interest") or 0),
                     "cash_coverage": div(s["ebitda"], s.get("interest") or 0)},
        "turnover": {"receivables_turnover": div(s["revenue"], s["receivables"]),
                     "days_sales_in_receivables": div(365, div(s["revenue"], s["receivables"]) or 0),
                     "payables_turnover": div(s["cogs"], s["payables"]),
                     "total_asset_turnover": tat, "capital_intensity": div(s["total_assets"], s["revenue"])},
        "profitability": {"profit_margin": pm, "ebitda_margin": div(s["ebitda"], s["revenue"]),
                          "return_on_assets": div(s["net_income"], s["total_assets"]),
                          "return_on_equity": div(s["net_income"], s["equity"])},
        "dupont": {"profit_margin": pm, "total_asset_turnover": tat, "equity_multiplier": em,
                   "return_on_equity": None if None in (pm, tat, em) else pm * tat * em},
    }
    if s.get("shares") and s.get("price"):
        eps = s["net_income"] / s["shares"]
        out["market_value"] = {"eps": eps, "pe_ratio": div(s["price"], eps), "market_to_book": div(s["price"] * s["shares"], s["equity"]),
                               "price_sales": div(s["price"] * s["shares"], s["revenue"])}
    return {g: {k: _r(v) for k, v in d.items()} for g, d in out.items()}


# ---- tax --------------------------------------------------------------------------------------------------------

def tax_on(income, bands):
    """bands: [(upper_limit or None, rate)] in order. Returns tax, average and marginal rate."""
    if income <= 0:
        return {"taxable_income": income, "tax": 0.0, "average_rate": 0.0, "marginal_rate": bands[0][1]}
    tax, lower, marginal = 0.0, 0.0, bands[0][1]
    for upper, rate in bands:
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (top - lower) * rate
            marginal = rate
        if upper is None or income <= upper:
            break
        lower = upper
    return {"taxable_income": income, "tax": round(tax, 2), "average_rate": round(tax / income, 4), "marginal_rate": marginal}


US_BRACKETS_2025 = {  # federal ordinary income brackets (upper limit of each band, rate) and the standard deduction
    "single": ([(11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24), (250_525, 0.32), (626_350, 0.35), (None, 0.37)], 15_000),
    "married": ([(23_850, 0.10), (96_950, 0.12), (206_700, 0.22), (394_600, 0.24), (501_050, 0.32), (751_600, 0.35), (None, 0.37)], 30_000),
}


def us_personal_tax(income, filing="single", deduction=None):
    """US federal income tax on wages (2025 brackets): taxable income after the standard deduction (or the one given),
    the tax by bracket, the marginal rate (on the next dollar) and the average rate on gross and on taxable income."""
    bands, std = US_BRACKETS_2025[filing]
    taxable = max(0.0, float(income) - float(std if deduction is None else deduction))
    by_band, lower, tax, marginal = [], 0.0, 0.0, bands[0][1]
    for upper, rate in bands:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            t = (top - lower) * rate
            by_band.append({"band": f"{lower:,.0f} to {'and above' if upper is None else f'{upper:,.0f}'}", "rate": rate,
                            "taxed": round(top - lower, 2), "tax": round(t, 2)})
            tax += t
            marginal = rate
        if upper is None or taxable <= upper:
            break
        lower = upper
    return {"gross_income": float(income), "deduction": float(std if deduction is None else deduction), "taxable_income": round(taxable, 2),
            "tax": round(tax, 2), "marginal_rate": marginal, "average_rate_on_gross": _r(tax / float(income)) if income else 0.0,
            "average_rate_on_taxable": _r(tax / taxable) if taxable else 0.0, "rows": by_band}


def uk_corporation_tax(profit):
    """UK from April 2023: 19% up to £50,000, 25% above £250,000, marginal relief in between (fraction 3/200), which
    makes the marginal rate 26.5% inside the band."""
    if profit <= 50_000:
        tax = profit * 0.19
        marginal = 0.19
    elif profit >= 250_000:
        tax, marginal = profit * 0.25, 0.25
    else:
        tax, marginal = profit * 0.25 - (250_000 - profit) * 3 / 200, 0.265
    tax = max(tax, 0)
    return {"taxable_income": profit, "tax": round(tax, 2), "average_rate": round(tax / profit, 4) if profit > 0 else 0.0,
            "marginal_rate": marginal}


def with_carryforward(income, nol_opening, limit=0.80):
    """US federal rules since 2018: losses carry forward indefinitely and offset up to 80% of taxable income."""
    if income <= 0:
        return {"taxable_after_nol": 0.0, "nol_used": 0.0, "nol_closing": nol_opening - income}
    used = min(nol_opening, income * limit)
    return {"taxable_after_nol": income - used, "nol_used": used, "nol_closing": nol_opening - used}


# ---- projection, EFN, growth ------------------------------------------------------------------------------------

def percent_of_sales(bs, income, sales, growth, payout=0.0, spontaneous=("accounts_payable", "accrued"), fixed_at_capacity=1.0):
    """Pro forma balance sheet by the percent-of-sales method.
    bs: {assets: {name: value}, liabilities: {name: value}, equity: value}; income: net income this year; sales: revenue.
    Assets grow with sales (fixed assets only past capacity: fixed_at_capacity = share of capacity used); spontaneous
    liabilities grow with sales; equity grows by retained earnings at the projected margin. EFN = projected assets -
    projected liabilities and equity."""
    g = growth
    pm = income / sales if sales else 0
    new_sales = sales * (1 + g)
    assets = {}
    for k, v in bs["assets"].items():
        if k.startswith("fixed") and fixed_at_capacity < 1:
            needed = new_sales / (sales / fixed_at_capacity) * v
            assets[k] = max(v, needed)
        else:
            assets[k] = v * (1 + g)
    liabilities = {k: (v * (1 + g) if any(t in k for t in spontaneous) else v) for k, v in bs["liabilities"].items()}
    added_re = new_sales * pm * (1 - payout)
    equity = bs["equity"] + added_re
    ta, tl = sum(assets.values()), sum(liabilities.values())
    efn = ta - tl - equity
    return {"projected_sales": round(new_sales, 2), "projected_assets": {k: round(v, 2) for k, v in assets.items()},
            "projected_liabilities": {k: round(v, 2) for k, v in liabilities.items()}, "projected_equity": round(equity, 2),
            "addition_to_retained_earnings": round(added_re, 2), "total_assets": round(ta, 2),
            "total_liabilities_and_equity": round(tl + equity, 2), "efn": round(efn, 2)}


def growth_rates(net_income, total_assets, equity, payout=0.0):
    """Internal growth rate (no outside financing) = ROA x b / (1 - ROA x b); sustainable growth rate (keeps the
    debt-equity ratio) = ROE x b / (1 - ROE x b); b = retention ratio. Negative when the company loses money."""
    b = 1 - payout
    roa, roe = net_income / total_assets, net_income / equity
    return {"retention_ratio": b, "roa": _r(roa), "roe": _r(roe),
            "internal_growth_rate": _r(roa * b / (1 - roa * b)), "sustainable_growth_rate": _r(roe * b / (1 - roe * b))}


# ---- project cash flows -----------------------------------------------------------------------------------------

def discounted_payback(flows, rate):
    disc = [f / (1 + rate) ** t for t, f in enumerate(flows)]
    return payback(disc)


def project_cash_flows(investment, life, annual_revenue, annual_costs, tax_rate, rate, salvage=0.0, nwc=0.0,
                       depreciation="straight_line"):
    """Project cash flows the textbook way: OCF = (revenue - costs - depreciation)(1 - t) + depreciation, i.e.
    (revenue - costs)(1 - t) + depreciation x t (the depreciation tax shield). Year 0: -investment - NWC. Final year:
    + after-tax salvage (salvage - (salvage - book value) x t) + NWC recovered."""
    dep = investment / life if depreciation == "straight_line" else None
    rows, flows = [], [-(investment + nwc)]
    book = investment
    for y in range(1, life + 1):
        d = dep if dep is not None else book * 2 / life  # double-declining
        d = min(d, book)
        book -= d
        ebit = annual_revenue - annual_costs - d
        tax = ebit * tax_rate
        ocf = ebit - tax + d
        shield = d * tax_rate
        terminal = 0.0
        if y == life:
            terminal = salvage - (salvage - book) * tax_rate + nwc
        flows.append(ocf + terminal)
        rows.append({"year": y, "revenue": annual_revenue, "costs": annual_costs, "depreciation": round(d, 2),
                     "ebit": round(ebit, 2), "taxes": round(tax, 2), "ocf": round(ocf, 2), "depreciation_tax_shield": round(shield, 2),
                     "after_tax_salvage_and_nwc": round(terminal, 2), "cash_flow": round(ocf + terminal, 2)})
    r = irr(flows)
    return {"rows": rows, "flows": [round(f, 2) for f in flows], "npv": round(npv(rate, flows), 2), "irr": _r(r),
            "payback_years": _r(payback(flows), 2), "discounted_payback_years": _r(discounted_payback(flows, rate), 2),
            "profitability_index": _r(sum(f / (1 + rate) ** t for t, f in enumerate(flows) if t) / -flows[0]) if flows[0] else None,
            "total_tax_shield": round(sum(x["depreciation_tax_shield"] for x in rows), 2)}


def crossover_rate(flows_a, flows_b):
    """The discount rate where two projects have the same NPV: the IRR of the difference in their cash flows."""
    n = max(len(flows_a), len(flows_b))
    a, b = flows_a + [0] * (n - len(flows_a)), flows_b + [0] * (n - len(flows_b))
    return _r(irr([x - y for x, y in zip(a, b)]))


def bid_price(investment, life, units, variable_cost, fixed_costs, tax_rate, rate, salvage=0.0, nwc=0.0):
    """Lowest price per unit that gives NPV = 0: the OCF needed (an annuity that recovers the investment net of the
    after-tax salvage and NWC), then price = (OCF - D x t ... ) solved back through the OCF formula."""
    dep = investment / life
    terminal = salvage * (1 - tax_rate) + nwc  # book value is zero at the end of straight-line life
    pv_terminal = terminal / (1 + rate) ** life
    annuity = (1 - (1 + rate) ** -life) / rate
    ocf = (investment + nwc - pv_terminal) / annuity
    # OCF = (P x Q - VC x Q - FC)(1 - t) + D x t  →  P
    sales = (ocf - dep * tax_rate) / (1 - tax_rate) + variable_cost * units + fixed_costs
    return {"required_ocf": round(ocf, 2), "required_sales": round(sales, 2), "bid_price_per_unit": round(sales / units, 4)}


# ---- break-even -------------------------------------------------------------------------------------------------

def break_even(fixed_cash_costs, depreciation, cm_ratio, investment=0.0, life=1, rate=0.0, tax_rate=0.0):
    """Revenue break-evens with a contribution-margin ratio (revenue form of the unit formulas):
    accounting   (fixed + depreciation) / CM ratio       net income = 0
    cash         fixed / CM ratio                        operating cash flow = 0
    financial    (fixed + EAC) / CM ratio                NPV = 0, where the equivalent annual cost of the investment
                 (an annuity at the discount rate) replaces depreciation (pre-tax approximation when t = 0)."""
    acc = (fixed_cash_costs + depreciation) / cm_ratio if cm_ratio else None
    cash = fixed_cash_costs / cm_ratio if cm_ratio else None
    eac = investment * rate / (1 - (1 + rate) ** -life) if investment and rate else depreciation
    # after tax: OCF needed = EAC; OCF = (S x cm - FC)(1 - t) + D x t → S
    fin = ((eac - depreciation * tax_rate) / (1 - tax_rate) + fixed_cash_costs) / cm_ratio if cm_ratio else None
    return {"accounting": _r(acc, 2), "cash": _r(cash, 2), "financial": _r(fin, 2), "equivalent_annual_cost": _r(eac, 2)}


def degree_of_operating_leverage(contribution, operating_income):
    """DOL = contribution margin / operating income: % change in operating income for a 1% change in revenue."""
    return None if not operating_income else _r(contribution / operating_income)


# ---- cost of capital --------------------------------------------------------------------------------------------

def capm(rf, beta, mrp):
    return rf + beta * mrp


def relever_beta(unlevered, debt_equity, tax_rate):
    """Hamada: levered beta = unlevered x (1 + (1 - t) D/E)."""
    return unlevered * (1 + (1 - tax_rate) * debt_equity)


def wacc(equity_value, debt_value, cost_of_equity, cost_of_debt, tax_rate, preferred_value=0.0, cost_of_preferred=0.0):
    v = equity_value + debt_value + preferred_value
    return {"weights": {"equity": _r(equity_value / v), "debt": _r(debt_value / v), "preferred": _r(preferred_value / v)},
            "after_tax_cost_of_debt": _r(cost_of_debt * (1 - tax_rate)),
            "wacc": _r(equity_value / v * cost_of_equity + debt_value / v * cost_of_debt * (1 - tax_rate)
                       + preferred_value / v * cost_of_preferred)}


def flotation_adjusted(investment, weights_flotation):
    """weights_flotation: [(weight, flotation cost %)] → true cost = investment / (1 - weighted flotation cost)."""
    fa = sum(w * f for w, f in weights_flotation)
    return {"weighted_flotation_cost": _r(fa), "amount_to_raise": round(investment / (1 - fa), 2)}


def rights_offering(price_now, subscription_price, shares_outstanding, funds_needed):
    new_shares = funds_needed / subscription_price
    rights_per_share = shares_outstanding / new_shares
    ex_rights = (price_now * shares_outstanding + funds_needed) / (shares_outstanding + new_shares)
    return {"new_shares": round(new_shares, 2), "rights_needed_per_new_share": _r(rights_per_share),
            "ex_rights_price": _r(ex_rights), "value_of_a_right": _r(price_now - ex_rights)}


# ---- time value of money ----------------------------------------------------------------------------------------

def tvm(rate, periods, pv=None, fv=None):
    if pv is not None:
        return {"future_value": round(pv * (1 + rate) ** periods, 2)}
    return {"present_value": round(fv / (1 + rate) ** periods, 2)}


def annuity(rate, periods, payment, due=False, growth=0.0):
    if growth:
        pv = payment / (rate - growth) * (1 - ((1 + growth) / (1 + rate)) ** periods)
    else:
        pv = payment * (1 - (1 + rate) ** -periods) / rate
    fv = pv * (1 + rate) ** periods
    k = (1 + rate) if due else 1
    return {"present_value": round(pv * k, 2), "future_value": round(fv * k, 2)}


def perpetuity(rate, payment, growth=0.0):
    return {"present_value": round(payment / (rate - growth), 2)} if rate > growth else {"error": "rate must exceed growth"}


def loan_schedule(principal, annual_rate, years, periods_per_year=12, kind="amortized"):
    """amortized: level payments; interest_only: interest each period, principal at the end; fixed_principal: equal
    principal each period."""
    n, r = int(years * periods_per_year), annual_rate / periods_per_year
    bal, rows = principal, []
    pay = principal * r / (1 - (1 + r) ** -n) if kind == "amortized" else None
    for t in range(1, n + 1):
        interest = bal * r
        if kind == "amortized":
            princ = pay - interest
        elif kind == "interest_only":
            princ = bal if t == n else 0.0
        else:
            princ = principal / n
        bal -= princ
        rows.append({"period": t, "payment": round(interest + princ, 2), "interest": round(interest, 2),
                     "principal": round(princ, 2), "balance": round(max(bal, 0), 2)})
    return {"payment": round(pay, 2) if pay else None, "total_interest": round(sum(x["interest"] for x in rows), 2), "rows": rows}


# ---- bonds ------------------------------------------------------------------------------------------------------

def bond_price(face, coupon_rate, ytm, years, freq=2):
    n, c, y = int(years * freq), face * coupon_rate / freq, ytm / freq
    return round(c * (1 - (1 + y) ** -n) / y + face / (1 + y) ** n, 4) if y else round(c * n + face, 4)


def bond_ytm(price, face, coupon_rate, years, freq=2):
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if bond_price(face, coupon_rate, mid, years, freq) > price:
            lo = mid
        else:
            hi = mid
    return round(mid, 6)


def interest_rate_risk(face, coupon_rate, ytm, years, shock=0.01, freq=2):
    p0 = bond_price(face, coupon_rate, ytm, years, freq)
    up, down = bond_price(face, coupon_rate, ytm + shock, years, freq), bond_price(face, coupon_rate, ytm - shock, years, freq)
    return {"price": p0, "price_if_rates_up": up, "price_if_rates_down": down,
            "pct_change_up": _r(up / p0 - 1), "pct_change_down": _r(down / p0 - 1),
            "current_yield": _r(face * coupon_rate / p0), "premium_or_discount": "premium" if p0 > face else "discount" if p0 < face else "par"}


# ---- stocks -----------------------------------------------------------------------------------------------------

def ddm(dividend_next, required_return, growth=0.0, supernormal=None):
    """Constant growth: P0 = D1 / (R - g). supernormal: [(years, growth)] before the constant growth phase."""
    if not supernormal:
        if required_return <= growth:
            return {"error": "required return must exceed growth"}
        return {"price": round(dividend_next / (required_return - growth), 4),
                "dividend_yield": _r(dividend_next / (dividend_next / (required_return - growth))), "capital_gains_yield": growth}
    pv, d, t = 0.0, dividend_next, 0
    for years, g in supernormal:
        for _ in range(years):
            t += 1
            pv += d / (1 + required_return) ** t
            d *= 1 + g
    terminal = d / (required_return - growth)
    return {"price": round(pv + terminal / (1 + required_return) ** t, 4)}


def voting(shares_owned, shares_total, seats, cumulative=True):
    """Shares needed to be sure of electing seats: cumulative = floor(total / (seats + 1)) + 1 per seat wanted;
    straight voting needs a majority to win every seat."""
    if cumulative:
        per_seat = floor(shares_total / (seats + 1)) + 1
        return {"shares_needed_for_one_seat": per_seat, "seats_you_can_guarantee": min(seats, shares_owned // per_seat)}
    need = floor(shares_total / 2) + 1
    return {"shares_needed_for_one_seat": need, "seats_you_can_guarantee": seats if shares_owned >= need else 0}


# ---- risk and return --------------------------------------------------------------------------------------------

def return_stats(returns):
    n = len(returns)
    arith = sum(returns) / n
    geo = 1.0
    for r in returns:
        geo *= 1 + r
    var = sum((r - arith) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
    return {"arithmetic_average": _r(arith), "geometric_average": _r(geo ** (1 / n) - 1), "variance": _r(var, 6),
            "standard_deviation": _r(sqrt(var))}


def holding_return(price_begin, price_end, dividend):
    return {"dividend_yield": _r(dividend / price_begin), "capital_gains_yield": _r((price_end - price_begin) / price_begin),
            "total_return": _r((dividend + price_end - price_begin) / price_begin)}


def portfolio(w1, r1, s1, r2, s2, corr):
    w2 = 1 - w1
    var = (w1 * s1) ** 2 + (w2 * s2) ** 2 + 2 * w1 * w2 * s1 * s2 * corr
    return {"expected_return": _r(w1 * r1 + w2 * r2), "standard_deviation": _r(sqrt(var)), "variance": _r(var, 6)}


def sml(rf, mrp, beta, expected_return=None):
    req = capm(rf, beta, mrp)
    out = {"required_return": _r(req), "reward_to_risk": _r(mrp)}
    if expected_return is not None:
        out["verdict"] = "undervalued (above the SML)" if expected_return > req else "overvalued (below the SML)" if expected_return < req else "on the SML"
    return out


# ---- capital structure and payout -------------------------------------------------------------------------------

def mm(unlevered_value_or_ebit, debt, cost_of_debt, unlevered_cost_of_equity, tax_rate=0.0, ebit=None):
    """M&M. Without taxes: V_L = V_U; R_E = R_U + (R_U - R_D) D/E. With taxes: V_L = V_U + T_C D;
    R_E = R_U + (R_U - R_D)(1 - T_C) D/E. Pass ebit to value the unlevered firm as a perpetuity."""
    vu = (ebit * (1 - tax_rate) / unlevered_cost_of_equity) if ebit is not None else unlevered_value_or_ebit
    vl = vu + tax_rate * debt
    e = vl - debt
    re = unlevered_cost_of_equity + (unlevered_cost_of_equity - cost_of_debt) * (1 - tax_rate) * (debt / e) if e else None
    w = wacc(e, debt, re, cost_of_debt, tax_rate)["wacc"] if e and re is not None else None
    return {"unlevered_value": round(vu, 2), "levered_value": round(vl, 2), "equity_value": round(e, 2),
            "interest_tax_shield_value": round(tax_rate * debt, 2), "cost_of_equity": _r(re), "wacc": w}


def homemade_leverage(shares, price, borrow, rate, eps_unlevered):
    """An investor replicates corporate leverage: buy extra shares with personal borrowing."""
    total_shares = shares + borrow / price
    payoff = total_shares * eps_unlevered - borrow * rate
    return {"shares_held": round(total_shares, 4), "net_payoff": round(payoff, 2), "own_money": round(shares * price, 2),
            "return_on_own_money": _r(payoff / (shares * price))}


def payout(net_income, shares, price, cash_distributed):
    """Cash dividend vs repurchase of the same cash (no taxes, perfect markets): same shareholder wealth."""
    eps = net_income / shares
    div_ps = cash_distributed / shares
    rep_shares = cash_distributed / price
    eps_after = net_income / (shares - rep_shares)
    return {"cash_dividend": {"dividend_per_share": _r(div_ps), "ex_dividend_price": _r(price - div_ps), "eps": _r(eps),
                              "pe": _r((price - div_ps) / eps)},
            "repurchase": {"shares_bought": round(rep_shares, 2), "price_after": _r(price), "eps": _r(eps_after),
                           "pe": _r(price / eps_after)}}


def split(shares, price, ratio=None, stock_dividend_pct=None):
    """A split (e.g. 2 for 1 → ratio 2) or stock dividend (0.10 = 10%): more shares, lower price, same value."""
    k = ratio if ratio else 1 + (stock_dividend_pct or 0)
    return {"shares_after": round(shares * k, 2), "price_after": _r(price / k), "market_value": round(shares * price, 2)}
