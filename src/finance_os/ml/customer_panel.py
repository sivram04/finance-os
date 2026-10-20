"""Weekly customer snapshots for the churn and expansion models: every Sunday, every active customer, with
point-in-time features from daily usage, the API request log (feature store), monthly revenue and invoices.

Labels look forward 3 months and exist only where those months have closed:
  churned   a churn movement (revenue to zero) in a month starting after the snapshot, within 92 days
  expanded  average monthly revenue over the next 3 closed months at least 20% above the last closed month,
            without churning
"""
import numpy as np
import pandas as pd

from finance_os.ml import feature_store
from finance_os.ml.features import Dense, PaymentHistory, api_dense, api_features, frame, latest_closed, month_end, segments, today

HORIZON_DAYS = 92
EXPANSION = 1.20
SEGMENTS = ("enterprise", "mid_market", "self_serve")
USAGE = ["hours_per_day_30d", "usage_trend", "usage_trend_7d", "days_since_usage", "active_day_share_30d", "usage_volatility_30d"]
API = ["req_per_day_30d", "req_trend", "req_trend_7d", "error_rate_30d", "error_rate_change", "server_error_rate_30d",
       "rate_limited_rate_30d", "auth_failure_rate_30d", "latency_p95_30d", "latency_p95_change", "active_keys_30d",
       "active_keys_change", "realtime_share_30d"]
REVENUE = ["log_revenue", "revenue_trend_3m", "contractions_3m", "expansions_3m", "tenure_months"]
PAYMENT = ["avg_days_late_6", "overdue_30_count"]
FEATURES = USAGE + API + REVENUE + PAYMENT + [f"seg_{s}" for s in SEGMENTS]
LABELS = {
    "hours_per_day_30d": "usage level", "usage_trend": "usage trend (30d vs prior 60d)", "usage_trend_7d": "usage last 7 days vs 30",
    "days_since_usage": "days since last usage", "active_day_share_30d": "share of days with usage", "usage_volatility_30d": "usage volatility",
    "req_per_day_30d": "API requests per day", "req_trend": "API request trend", "req_trend_7d": "API requests last 7 days vs 30",
    "error_rate_30d": "API error rate", "error_rate_change": "change in API error rate", "server_error_rate_30d": "server (5xx) error rate",
    "rate_limited_rate_30d": "rate-limited share", "auth_failure_rate_30d": "auth failure share", "latency_p95_30d": "p95 latency",
    "latency_p95_change": "change in p95 latency", "active_keys_30d": "active API keys", "active_keys_change": "change in active API keys",
    "realtime_share_30d": "real-time share", "log_revenue": "revenue size", "revenue_trend_3m": "revenue trend (3 months)",
    "contractions_3m": "months of contraction (last 3)", "expansions_3m": "months of expansion (last 3)", "tenure_months": "tenure",
    "avg_days_late_6": "average days paid late", "overdue_30_count": "invoices 30+ days overdue",
}


def _usage_dense(wh, end):
    u = frame(wh, "select customer_id, usage_date as d, sum(audio_hours) as h from staging.stg_synthetic__usage_daily group by 1, 2")
    u["h"] = u["h"].astype(float)
    u["on"] = (u["h"] > 0).astype(float)
    u["h2"] = u["h"] ** 2
    return Dense(u, "customer_id", "d", ["h", "on", "h2"], end=end)


def _usage_features(ud, asof, ids):
    rows = np.array([ud.ix.get(c, -1) for c in ids])
    pick = lambda a: np.where(rows >= 0, a[np.clip(rows, 0, None)], 0.0)  # noqa: E731
    h30 = pick(ud.total("h", asof, 0, 30)) / 30
    h60 = pick(ud.total("h", asof, 30, 60)) / 60
    h7 = pick(ud.total("h", asof, 0, 7)) / 7
    on30 = pick(ud.total("on", asof, 0, 30))
    sq30 = pick(ud.total("h2", asof, 0, 30)) / 30
    sd = np.sqrt(np.clip(sq30 - h30 ** 2, 0, None))
    # days since last usage: smallest window ending today with any usage
    since = np.full(len(ids), 120.0)
    for d in (1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120):
        hit = (pick(ud.total("on", asof, 0, d)) > 0) & (since == 120)
        since[hit] = d - 1
    trend = np.where(h60 > 0, h30 / np.where(h60 > 0, h60, 1) - 1, np.where(h30 > 0, 1.0, 0.0))
    t7 = np.where(h30 > 0, h7 / np.where(h30 > 0, h30, 1) - 1, 0.0)
    return {"hours_per_day_30d": h30, "usage_trend": np.clip(trend, -1, 3), "usage_trend_7d": np.clip(t7, -1, 3),
            "days_since_usage": since, "active_day_share_30d": on30 / 30,
            "usage_volatility_30d": np.where(h30 > 0, sd / np.where(h30 > 0, h30, 1), 0.0)}


def _revenue_features(piv, months, asof, ids):
    closed = [m for m in months if month_end(m) <= asof]
    if not closed:
        return None, None
    hist = piv.reindex(index=ids).fillna(0.0)[closed]
    now = hist.iloc[:, -1].to_numpy()
    before = hist.iloc[:, -4].to_numpy() if hist.shape[1] >= 4 else hist.iloc[:, 0].to_numpy()
    diffs = hist.diff(axis=1).iloc[:, -3:].to_numpy() if hist.shape[1] >= 2 else np.zeros((len(ids), 1))
    return {"log_revenue": np.log1p(np.clip(now, 0, None)),
            "revenue_trend_3m": np.clip(np.where(before > 0, now / np.where(before > 0, before, 1) - 1, 0.0), -1, 3),
            "contractions_3m": (diffs < 0).sum(axis=1), "expansions_3m": (diffs > 0).sum(axis=1),
            "tenure_months": (hist > 0).cumsum(axis=1).gt(0).sum(axis=1).to_numpy()}, closed[-1]


_CACHE = {}


def build(wh):
    """Built once per process and warehouse state (churn and expansion share it)."""
    key = (id(wh), str(today(wh)), str(latest_closed(wh)))
    if key not in _CACHE:
        _CACHE.clear()
        _CACHE[key] = _build(wh)
    return _CACHE[key]


def _build(wh):
    closed_m = latest_closed(wh)
    now = today(wh)
    rev = frame(wh, "select month, customer_id, revenue, movement from marts.fct_customer_revenue_monthly where month <= ?::date",
                [str(closed_m.date())])
    rev["month"] = pd.to_datetime(rev["month"])
    rev["revenue"] = rev["revenue"].astype(float)
    months = sorted(rev["month"].unique())
    piv = rev.pivot_table(index="customer_id", columns="month", values="revenue", aggfunc="sum").reindex(columns=months).fillna(0.0)
    churn_months = rev[rev["movement"] == "churn"].groupby("customer_id")["month"].apply(list).to_dict()
    seg = segments(wh)
    ud = _usage_dense(wh, now)
    ad = api_dense(feature_store.load(wh), end=now)
    pay = PaymentHistory(wh)
    label_end = month_end(closed_m)

    snaps = list(pd.date_range(ud.start + pd.Timedelta(days=90), now, freq="W-SUN"))
    if snaps[-1] != now:
        snaps.append(now)  # today, to score
    frames = []
    for asof in snaps:
        rf, last_closed = _revenue_features(piv, months, asof, list(piv.index))
        if rf is None:
            continue
        ids = list(piv.index)
        uf = _usage_features(ud, asof, ids)
        active = (piv[last_closed].to_numpy() > 0) | (uf["hours_per_day_30d"] > 0)
        ids = [c for c, a in zip(ids, active) if a]
        if not ids:
            continue
        sel = np.array(active)
        f = {k: np.asarray(v)[sel] for k, v in rf.items()}
        f.update({k: np.asarray(v)[sel] for k, v in uf.items()})
        arows = np.array([ad.ix.get(c, -1) for c in ids])
        af = api_features(ad, asof)
        f.update({k: np.where(arows >= 0, v[np.clip(arows, 0, None)], 0.0) for k, v in af.items() if k != "active_days_30d"})
        p = [pay.features(c, asof) for c in ids]
        f["avg_days_late_6"] = np.array([x["avg_days_late_6"] for x in p])
        f["overdue_30_count"] = np.array([x["overdue_30_count"] for x in p])
        for s in SEGMENTS:
            f[f"seg_{s}"] = np.array([int(seg.get(c) == s) for c in ids])
        df = pd.DataFrame(f)
        df.insert(0, "customer_id", ids)
        df.insert(1, "asof", asof)
        df["revenue_last_closed"] = piv.loc[ids, last_closed].to_numpy()
        labelled = asof + pd.Timedelta(days=HORIZON_DAYS) <= label_end
        df["labelled"] = labelled and asof != now
        horizon = asof + pd.Timedelta(days=HORIZON_DAYS)
        df["churned"] = [int(any(asof < m <= horizon for m in churn_months.get(c, ()))) for c in ids] if labelled else None
        if labelled:
            nxt = [m for m in months if m > last_closed][:3]
            fut = piv.loc[ids, nxt].mean(axis=1).to_numpy() if len(nxt) == 3 else np.full(len(ids), np.nan)
            base = df["revenue_last_closed"].to_numpy()
            df["expanded"] = ((fut >= EXPANSION * base) & (base > 0) & (df["churned"].to_numpy() == 0)).astype(int)
        else:
            df["expanded"] = None
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    return panel, now, piv, months, seg


def holdout_split(panel, months=6):
    lab = panel[panel["labelled"]].copy()
    cut = lab["asof"].max() - pd.DateOffset(months=months)
    # a gap of one label horizon, so no training label looks into the holdout period
    return lab[lab["asof"] <= cut - pd.Timedelta(days=HORIZON_DAYS)], lab[lab["asof"] > cut], cut
