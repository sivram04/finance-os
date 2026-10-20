"""Machine-learning forecasts that sit beside the rule- and driver-based ones, each backtested against the method
it would replace:

- churn        gradient-boosted classifier: probability a customer churns in the next 3 months
               (vs the at-risk / watch rules in fct_customer_health)
- usage        damped-trend exponential smoothing (ETS): next 6 months of usage revenue with an 80% range
               (vs the driver forecast in fct_forecast_monthly)
- payment      quantile gradient boosting: when each open invoice will be paid, with a P10-P90 range
               (vs due date + the customer's average days late, the 13-week cash forecast's rule)
- anomalies    robust z-score against each GL line's own history plus an isolation forest
               (vs fixed thresholds)
- expansion    gradient-boosted classifier: probability revenue grows 20%+ over the next 3 months
               (vs a usage-trend rule)
- revenue      bottom-up gradient boosting per customer and horizon, from daily usage and the API log
               (vs ETS and the driver forecast)
- spend        gradient boosting on daily GPU and cloud spend with usage as the driver
               (vs the 3-month growth method in fct_spend_forecast)
- deals        logistic regression on closed deals: win probability for open ones (vs segment win rate / CRM stage)

Customer models read a feature store built from the raw API request log (~200M rows -> customer x day,
data/ml/api_daily.parquet; see feature_store).

Models train on the warehouse (DuckDB) and write their outputs and model cards to data/ml/*.json; the app reads
those files. They are not dbt models, so they are not part of the BigQuery parity check.

    python -m finance_os.ml            # train all four, write data/ml
"""
import json
from datetime import datetime, timezone

from finance_os.paths import ROOT

OUT = ROOT / "data" / "ml"
MODELS = ("churn", "expansion", "revenue", "usage", "spend", "payment", "deals", "anomalies")


def save(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}
    (OUT / f"{name}.json").write_text(json.dumps(payload, default=str, indent=1), encoding="utf-8")
    return payload


def load(name, wh=None):
    """The latest saved run of a model; trains it first if it has never run."""
    path = OUT / f"{name}.json"
    if not path.exists():
        if wh is None:
            return None
        return train(name, wh)
    return json.loads(path.read_text(encoding="utf-8"))


def train(name, wh):
    import importlib
    return save(name, importlib.import_module(f"finance_os.ml.{name}").run(wh))


def train_all(wh, log=print, refresh_features=True):
    """Refresh the request-log feature store (incremental), then train every model."""
    out = {}
    if refresh_features:
        from finance_os.ml import feature_store
        feature_store.build(wh, log=log)
    for name in MODELS:
        r = train(name, wh)
        log(f"{name}: {r['card']['headline']}")
        out[name] = r
    return out
