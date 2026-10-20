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


def test_explore_ledger_totals_tie(wh):
    by_acct = tools.explore_ledger(wh, start_month="2026-04", end_month="2026-06", account_type="opex", department="ENG")
    by_month = tools.explore_ledger(wh, start_month="2026-04", end_month="2026-06", account_type="opex", department="ENG", group_by="month")
    assert by_acct["total"] == by_month["total"] > 0
    assert [r["month"] for r in by_month["rows"]] == ["2026-04", "2026-05", "2026-06"]
    assert tools.explore_ledger(wh, group_by="nope")["rows"] == []


def test_new_stress_presets(wh):
    churn = tools.run_stress_test(wh, preset="largest_customer_churn")
    assert churn["preset_detail"]["customer_id"] and churn["scenario"]["revenue_12m"] < churn["baseline"]["revenue_12m"]
    late = tools.run_stress_test(wh, preset="fundraise_delayed")
    assert late["preset_detail"]["delayed_close"] > late["preset_detail"]["planned_close"]
    for p in ("severe_downside", "gpu_price_shock"):
        r = tools.run_stress_test(wh, preset=p)
        assert r["scenario"]["ebitda_12m"] < r["baseline"]["ebitda_12m"]


def test_employee_workforce_ties_to_department_plan(wh):
    first = wh.query("""select (select sum(expected_loaded_cost) from marts.fct_workforce_employee_monthly
                                where month = (select min(month) from marts.fct_workforce_employee_monthly)) as emp,
                               (select sum(expected_payroll) from marts.fct_workforce_plan_monthly
                                where month = (select min(month) from marts.fct_workforce_plan_monthly)) as dept""")[0]
    assert abs(first["emp"] - first["dept"]) < 1
    assert tools.get_headcount_plan(wh)["workforce_next_12m"]["promotion_cost"] > 0


def test_deal_desk_non_standard_terms(wh):
    r = tools.price_deal(wh, "New Co", [{"product_id": "stream", "hours_per_month": 30000}], payment_terms_days=90,
                         unlimited_usage=True, prepaid_credits=True)
    failed = {c["rule"] for c in r["checks"] if not c["passed"]}
    assert {"PAYMENT-TERMS", "UNLIMITED"} <= failed and "CFO" in r["approvers"]
    assert {f["flag"] for f in r["revrec_flags"]} >= {"Stand-ready obligation", "Breakage on prepaid credits"}


def test_forecast_error_by_driver_adds_up(wh):
    r = tools.get_forecast_error_by_driver(wh)
    assert r["rows"]
    for x in r["rows"]:
        assert abs(x["existing_customers"] + x["new_customers"] + x["services"] - x["revenue"]) < 1


def test_vendor_concentration_and_correlation(wh):
    v = tools.get_vendor_concentration(wh)["summary"]
    assert 0 < v["top1_share"] <= 1 and 0 < v["hhi"] <= 10000
    c = tools.get_driver_correlation(wh)
    assert all(-1 <= p["correlation"] <= 1 for p in c["strongest_pairs"])


def test_decisions_and_evidence_drill(wh):
    d = tools.get_decisions_needed(wh)["rows"]
    assert d and all(x["owner"] and x["evidence"] and "options" not in x for x in d)
    ev = tools.answer_evidence(wh, "Revenue rose", [("get_customer_detail", {"customer_id": "EN-001"}, {})], [])
    assert any(x["args"].get("customer_id") == "EN-001" for x in ev["drill"])


def test_variance_case_end_to_end(wh):
    r = tools.get_variance_case(wh, "BVA-202609-NONE-4000")
    c = r["case"]
    assert abs(r["source_lines_total"] - c["actual"]) < 0.01  # source lines tie to the reported actual
    assert all(s["status"] == "pass" for s in r["reconciliation_chain"])
    comps = {x["driver"]: x["amount"] for x in r["root_cause_components"]}
    budget_growth = comps.pop("Budget assumed growth since the December base")
    # the bridge closes: budget - growth not delivered + delivered growth = actual
    assert abs(c["budget"] - budget_growth + sum(comps.values()) - c["actual"]) < 1
    assert "actions" not in r and r["decision_options"] and r["owner"]
    other = tools.get_variance_case(wh, "BVA-202609-INF-6600")
    assert other["root_cause"]["classification"].startswith("Planning gap")


def test_decision_kpis_carry_the_full_contract(wh):
    k = tools.get_decision_kpis(wh)
    assert len(k["rows"]) == 33
    for r in k["rows"]:
        assert r["status"] in ("red", "amber", "green", "grey")
        assert r["purpose"] and r["formula"] and r["owner"] and r["source_model"] and r["status_reason"] and "decision" not in r
        assert r["threshold"]["basis"] and r["recon_status"]
    rev = next(r for r in k["rows"] if r["metric"] == "revenue")
    assert rev["lineage_sources"] and rev["recon_status"] == "pass"


def test_contribution_bridge_adds_up(wh):
    b = tools.get_contribution_bridge(wh)
    assert abs(b["start"]["amount"] + sum(x["amount"] for x in b["rows"]) - b["end"]["amount"]) < 0.02


def test_control_queue_items_are_owned(wh):
    q = tools.get_control_queue(wh)
    assert q["open_items"] == len(q["rows"]) > 0
    assert all(i["owner"] and i["action"] and i["threshold"] for i in q["rows"])
    grid = tools.get_margin_sensitivity(wh)["rows"]
    assert grid[0]["cost -10%"] > grid[0]["cost +35%"]


def test_approval_evidence_shows_why(wh):
    dup = wh.query("select doc_file from marts.fct_ap_documents where list_contains(issues, 'duplicate_invoice') limit 1")
    if dup:
        r = tools.get_approval_evidence(wh, "ap_reject", dup[0]["doc_file"], {})
        failed = [c for c in r["rows"] if not c["passed"]]
        assert failed and "already booked" in failed[0]["detail"]
        assert r["proposal_agrees_with_checks"] is True and r["approve_means"]
    deal = tools.price_deal(wh, "New Co", [{"product_id": "stream", "hours_per_month": 30000}], discount_pct=0.35)
    ev = {k: v for k, v in deal.items() if k not in ("source", "row_count", "rows")}
    r = tools.get_approval_evidence(wh, "deal_approval", "Q-x", {"evaluation": ev})
    assert r["failed"] > 0 and r["proposal_agrees_with_checks"] is False  # approving would override failed guardrails
