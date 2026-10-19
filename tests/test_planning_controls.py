"""Contracts, the driver engine, workforce, deal desk risk, commissions, the CEO one-pager, the driver tree and the
evidence block: each reads the built warehouse and must hold its own invariants."""
import pytest

from finance_os import fpa
from finance_os.app import tools
from finance_os.app.tools import WAREHOUSE, Warehouse

pytestmark = pytest.mark.skipif(not WAREHOUSE.exists(), reason="build the warehouse first")


@pytest.fixture(scope="module")
def wh():
    return Warehouse()


def test_contracts_rpo_and_crpo(wh):
    s = tools.get_contracts(wh)["summary"]
    assert s["contracts"] > 0 and s["contracted_arr"] > 0
    assert 0 < s["crpo"] <= s["rpo"]
    assert s["revenue_at_risk"] <= s["renewal_base_180d"]


def test_one_engine_one_runway(wh):
    base = tools._stress_base(wh)
    for sm in tools.get_forecast(wh)["scenarios"]:
        out = fpa.project(base, tools._scenario_levers(wh, sm["scenario"]), 18)
        assert sm["runway_months"] == out["summary"]["runway_months_no_raise"]
        assert sm["revenue_next_12m"] == round(sum(r["revenue"] for r in out["rows"][:12]), 2)


def test_engine_runway_is_months_until_cash_goes_negative():
    base = {"start_month": "2026-09", "mrr": 100.0, "services": 0.0, "cash": 1000.0, "cogs_pct": 0.0,
            "existing_net_monthly": 0.0, "self_serve_new_mrr": 0.0, "pipeline": [], "bookings_arr_monthly": 0.0,
            "payroll": [200.0], "other_opex": [0.0], "payroll_now": 200.0, "other_opex_now": 0.0}
    sm = fpa.project(base, {}, 24)["summary"]
    assert sm["runway_months"] == 11  # burns 100 a month from 1,000: below zero in the 11th month


def test_forecast_changes_explain_the_starting_point(wh):
    c = tools.get_forecast_changes(wh)
    assert c["prior_as_of"] < c["as_of"]
    assert {r["driver"] for r in c["starting_point"]} >= {"cash", "mrr"}


def test_workforce_adds_up(wh):
    w = tools.get_headcount_plan(wh)["workforce_next_12m"]
    assert w["expected_people_cost"] > 0 and w["recruiting_cost"] >= 0


def test_deal_risk_view(wh):
    r = tools.price_deal(wh, "New Co", [{"product_id": "stream", "hours_per_month": 30000}], discount_pct=0.1)
    risk = r["risk"]
    for c in risk["cost_to_serve"]:
        assert c["p10"] <= c["p50"] <= c["p90"]
    assert risk["credit"]["peak_exposure"] > 0 and risk["commission"]["first_year_commission"] > 0


def test_commissions_deferred_balance(wh):
    d = tools.get_commissions_dashboard(wh)
    assert d["deferred_summary"]["balance"] > 0
    assert d["deferred_summary"]["current_portion"] <= d["deferred_summary"]["balance"]


def test_ceo_one_pager_ranked(wh):
    r = tools.get_ceo_one_pager(wh)
    for lst in (r["opportunities"], r["risks"]):
        assert 0 < len(lst) <= 5
        assert [x["amount"] for x in lst] == sorted((x["amount"] for x in lst), reverse=True)


def test_driver_tree_ebitda_identity(wh):
    rows = {r["node"]: r["value"] for r in tools.get_driver_tree(wh)["rows"]}
    assert abs(rows["ebitda"] - (rows["revenue"] - rows["cost_of_revenue"] - rows["opex"])) < 0.01
    assert abs(rows["usage_revenue"] - rows["audio_hours"] * rows["revenue_per_hour"]) < rows["usage_revenue"] * 0.001  # rate held to 4 dp


def test_evidence_block(wh):
    ev = tools.answer_evidence(wh, "Run-rate ARR rose", [("get_kpis", {"month": "2026-09"}, tools.get_kpis(wh))], [])
    assert ev["freshness"]["closed_through"] and ev["sources"]
    assert any(m["metric"] == "arr" and m["version"] == 2 for m in ev["metrics"])
