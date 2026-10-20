"""Controller, treasury and valuation: the schedules tie to the ledger and to themselves."""
import pytest

from finance_os import corpfin as cf
from finance_os.app import tools


@pytest.fixture(scope="module")
def wh():
    return tools.Warehouse()


def test_fixed_asset_register_ties_to_the_gl(wh):
    fa = tools.get_fixed_assets(wh)
    assert fa["rows"], "every capex entry becomes an asset"
    assert all(r["status"] == "ties" for r in fa["reconciliation"])
    t = fa["totals"]
    assert t["cost"] == pytest.approx(t["accumulated_depreciation"] + t["net_book_value"], abs=0.01)


def test_leases_amortize_to_zero_and_straight_line_equals_cash(wh):
    rows = wh.query("""select lease_id, sum(cash_payment) as cash, sum(straight_line_cost) as cost, sum(cost_minus_cash) as diff,
                              min(closing_liability) as min_liab, min(closing_rou_asset) as min_rou
                       from marts.fct_lease_schedule_monthly group by 1""")
    for r in rows:
        assert abs(float(r["min_liab"])) < 1 and abs(float(r["min_rou"])) < 1, r   # both run off by the end of the term
        assert float(r["cost"]) == pytest.approx(float(r["cash"]), abs=1)        # straight-line cost = total cash over the term
    cur = tools.get_leases(wh)["totals"]
    assert cur["closing_liability"] == pytest.approx(cur["current_liability"] + cur["non_current_liability"], abs=0.01)


def test_debt_schedule_repays_in_full(wh):
    sched = [r for r in tools.get_debt_facilities(wh)["schedule"] if r["facility_id"] == "VD-01"]
    assert float(sched[-1]["pro_forma_closing_balance"]) == pytest.approx(0, abs=1)
    assert sum(float(r["pro_forma_principal"]) for r in sched) == pytest.approx(float(sched[0]["pro_forma_opening_balance"]), abs=1)


def test_hedge_ratio_is_a_share_of_exposure(wh):
    fx = tools.get_fx_hedging(wh)
    assert fx["rows"] and all(0 <= float(r["hedge_ratio"]) <= 1.5 for r in fx["rows"])
    assert all(h["status"] in ("open", "settled") for h in fx["hedges"])


def test_valuation_falls_as_the_discount_rate_rises(wh):
    v = tools.get_valuation(wh)
    col = [float(r["g 3%"]) for r in v["sensitivity_per_share"]]
    assert col == sorted(col, reverse=True)
    assert {r["method"] for r in v["rows"]} >= {"Last funding round"}
    assert cf.dcf([100, 100], 0.1, terminal_growth=0.0)["enterprise_value"] == pytest.approx(100 / 1.1 + 100 / 1.21 + 1000 / 1.21, abs=0.01)


def test_journal_entry_sample_is_flagged(wh):
    je = tools.get_journal_entry_tests(wh)
    assert je["rows"] and all(int(r["risk_score"]) >= 2 for r in je["rows"])
