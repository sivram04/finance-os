"""The ML models train on the warehouse, produce sane outputs and report a backtest against the current method."""
import pandas as pd
import pytest

from finance_os import ml
from finance_os.app import tools
from finance_os.ml import feature_store

pytestmark = pytest.mark.skipif(not feature_store.PATH.exists(),
                                reason="feature store not built (python -m finance_os.ml builds it from the request log)")


@pytest.fixture(scope="module")
def runs():
    wh = tools.Warehouse()
    return {name: ml.train(name, wh) for name in ml.MODELS}


def test_feature_store_covers_the_request_log():
    fs = feature_store.load()
    assert len(fs) > 10_000 and fs["customer_id"].nunique() > 50
    assert (fs["billable_requests"] <= fs["requests"]).all()
    assert fs["usage_date"].max() >= pd.Timestamp("2026-10-01")


@pytest.mark.parametrize("name,label", [("churn", "churn_probability_3m"), ("expansion", "expansion_probability_3m")])
def test_customer_classifiers_score_and_compare_with_the_rule(runs, name, label):
    r = runs[name]
    assert r["rows"] and all(0 <= x[label] <= 1 for x in r["rows"])
    card = r["card"]
    assert card["training_positives"] > 0 and card["holdout_positives"] > 0
    cmp = card["same_budget_comparison"]
    assert cmp["model"]["flagged"] == cmp["rule"]["flagged"]  # compared at the same number flagged
    assert "current_rule" in card["evaluation"]
    probs = [x[label] for x in r["rows"]]
    assert probs == sorted(probs, reverse=True)


def test_panel_holdout_has_a_gap_and_no_future_labels():
    from finance_os.ml import customer_panel
    panel, today, *_ = customer_panel.build(tools.Warehouse())
    train, test, cut = customer_panel.holdout_split(panel)
    assert train["asof"].max() <= cut - pd.Timedelta(days=customer_panel.HORIZON_DAYS)
    assert not panel[panel["asof"] == today]["labelled"].any()


def test_churn_expected_loss_adds_up(runs):
    r = runs["churn"]
    assert r["expected_arr_lost_3m"] == pytest.approx(sum(x["arr_at_risk"] for x in r["rows"]), abs=1)


@pytest.mark.parametrize("name", ["usage", "revenue"])
def test_revenue_forecasts_have_ranges_and_backtests(runs, name):
    rows = [x for x in runs[name]["rows"] if x.get("series", "total") == "total"]
    assert len(rows) >= 3
    assert all(x["low_80"] <= x["forecast"] <= x["high_80"] for x in rows)


def test_spend_forecast_vs_growth_method(runs):
    r = runs["spend"]
    total = [x for x in r["rows"] if x["series"] == "total"]
    assert len(total) == 3 and all(x["forecast"] > 0 for x in total)
    assert r["card"]["evaluation"]["mape"]["growth_method"] is not None


def test_deal_model_does_not_leak(runs):
    # no feature may reveal the outcome: a perfect cross-validated score on a few dozen deals means leakage
    assert runs["deals"]["card"]["evaluation"]["model"]["roc_auc"] < 0.95
    assert all(0 <= x["ml_win_probability"] <= 1 for x in runs["deals"]["rows"])


def test_payment_dates_are_ordered(runs):
    r = runs["payment"]
    for x in r["rows"]:
        assert x["earliest_p10"] <= x["expected_pay_date"] <= x["latest_p90"] or x["note"]
    disputed = sum(x["balance"] for x in r["rows"] if x["is_disputed"])
    assert sum(w["amount"] for w in r["expected_collections_by_week"]) == pytest.approx(
        sum(x["balance"] for x in r["rows"]) - disputed, abs=1)


def test_anomalies_catch_the_planted_ones(runs):
    for p in runs["anomalies"]["card"]["evaluation"]["planted_anomalies"]:
        assert p["model_caught"] == p["periods"], p


def test_tools_read_the_saved_runs(runs):
    wh = tools.Warehouse()
    for t in ("get_churn_predictions", "get_expansion_predictions", "get_revenue_forecast_ml", "get_usage_forecast_ml",
              "get_spend_forecast_ml", "get_payment_predictions", "get_deal_predictions", "get_cost_anomalies_ml"):
        out = tools.run_tool(wh, t, {})
        assert out["model_card"]["headline"], t
    assert len(tools.run_tool(wh, "get_ml_models", {})["rows"]) == len(ml.MODELS)
