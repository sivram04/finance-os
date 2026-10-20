"""Corporate finance formulas against textbook answers, and the company view against its own statements."""
import pytest

from finance_os import corpfin as cf
from finance_os.app import tools
from finance_os.app.tools import WAREHOUSE, Warehouse


def test_time_value_and_annuities():
    assert cf.tvm(0.08, 10, pv=1000)["future_value"] == 2158.92
    assert cf.annuity(0.06, 20, 5000)["present_value"] == 57349.61
    assert cf.perpetuity(0.08, 100, growth=0.02)["present_value"] == 1666.67
    loan = cf.loan_schedule(100000, 0.08, 5)
    assert loan["payment"] == 2027.64 and loan["rows"][-1]["balance"] == 0


def test_bonds():
    assert cf.bond_price(1000, 0.06, 0.08, 10) == pytest.approx(864.10, abs=0.01)
    assert cf.bond_ytm(864.0967, 1000, 0.06, 10) == pytest.approx(0.08, abs=1e-5)
    long, short = cf.interest_rate_risk(1000, 0.05, 0.05, 30), cf.interest_rate_risk(1000, 0.05, 0.05, 2)
    assert abs(long["pct_change_up"]) > abs(short["pct_change_up"])  # long bonds carry more rate risk


def test_stocks_and_voting():
    assert cf.ddm(2, 0.12, 0.05)["price"] == pytest.approx(28.5714, abs=1e-3)
    assert cf.voting(300, 1000, 4)["shares_needed_for_one_seat"] == 201
    assert cf.voting(300, 1000, 4, cumulative=False)["seats_you_can_guarantee"] == 0


def test_capital_budgeting():
    flows = [-1000, 450, 450, 450]
    assert cf.discounted_payback(flows, 0.10) > 2.5 > 2.0  # discounted payback is always later than payback
    p = cf.project_cash_flows(500000, 5, 300000, 120000, 0.21, 0.12, salvage=50000, nwc=20000)
    assert p["total_tax_shield"] == round(500000 * 0.21, 2)
    assert p["rows"][0]["ocf"] == round((300000 - 120000) * 0.79 + 100000 * 0.21, 2)
    assert p["discounted_payback_years"] > p["payback_years"]


def test_break_even_order():
    be = cf.break_even(100000, 500000 / 60, 0.5, investment=500000, life=60, rate=0.01)
    assert be["cash"] < be["accounting"] < be["financial"]


def test_tax_bands_and_uk_relief():
    t = cf.tax_on(100000, [(50000, 0.15), (75000, 0.25), (None, 0.34)])
    assert t["tax"] == 22250 and t["marginal_rate"] == 0.34 and t["average_rate"] == 0.2225
    uk = cf.uk_corporation_tax(150000)
    assert uk["tax"] == 36000 and uk["marginal_rate"] == 0.265


def test_capm_wacc_mm():
    assert cf.capm(0.04, 1.5, 0.06) == pytest.approx(0.13)
    w = cf.wacc(800, 200, 0.14, 0.07, 0.21)
    assert w["wacc"] == pytest.approx(0.8 * 0.14 + 0.2 * 0.07 * 0.79, abs=1e-4)
    m = cf.mm(0, 400000, 0.08, 0.12, 0.21, ebit=150000)
    assert m["levered_value"] - m["unlevered_value"] == pytest.approx(0.21 * 400000)


def test_payout_policy_is_neutral():
    p = cf.payout(49000, 100000, 10, 300000)
    # shareholder wealth is the same: ex-dividend price + dividend = repurchase price
    assert p["cash_dividend"]["ex_dividend_price"] + p["cash_dividend"]["dividend_per_share"] == p["repurchase"]["price_after"]
    assert cf.split(1000, 60, ratio=3)["price_after"] == 20


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="build the warehouse first")
def test_company_corporate_finance():
    wh = Warehouse()
    r = tools.get_corporate_finance(wh)
    d = r["ratios"]["dupont"]
    assert d["return_on_equity"] == pytest.approx(d["profit_margin"] * d["total_asset_turnover"] * d["equity_multiplier"], abs=1e-3)
    cfa = r["cash_flow"]
    assert cfa["cash_flow_from_assets"] == pytest.approx(cfa["operating_cash_flow"] - cfa["net_capital_spending"] - cfa["change_in_nwc"], abs=0.02)
    assert r["proforma"]["total_assets"] - r["proforma"]["total_liabilities_and_equity"] == pytest.approx(r["proforma"]["efn"], abs=0.05)
    assert r["break_even"]["cash"] < r["break_even"]["accounting"] < r["break_even"]["financial"]
    assert 0.08 < r["cost_of_capital"]["wacc"] < 0.25
    assert tools.finance_calculator(wh, "bond_price", {"face": 1000, "coupon_rate": 0.06, "ytm": 0.08, "years": 10})["result"]["value"] == pytest.approx(864.10, abs=0.01)


def test_personal_tax_marginal_vs_average():
    t = cf.us_personal_tax(185000, "single")
    assert t["taxable_income"] == 170000 and t["tax"] == 33647 and t["marginal_rate"] == 0.24
    assert t["average_rate_on_gross"] < t["marginal_rate"]  # average is always below marginal in a progressive system
    assert cf.us_personal_tax(10000)["tax"] == 0  # under the standard deduction


@pytest.mark.skipif(not WAREHOUSE.exists(), reason="build the warehouse first")
def test_market_value_ratios_use_last_round_price():
    mv = tools.get_corporate_finance(Warehouse())["ratios"]["market_value"]
    assert mv["price_per_share"] == 4.5 and mv["implied_equity_value"] == mv["price_per_share"] * mv["fully_diluted_shares"]
    assert "private-company estimate" in mv["basis"]
