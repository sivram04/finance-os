"""Bottom-up usage revenue forecast: a gradient-boosted model of each customer's audio hours over the next 1, 2
and 3 months (30-day blocks), trained on a forecast origin every 3 days for every active customer (tens of
thousands of customer-origins from daily usage and the API request log), priced at each customer's own revenue
per hour, and summed.

Walk-forward backtest: at every month end, refit on origins whose targets had fully happened by then, forecast the
next 3 calendar months, and compare the total with actual usage revenue, the driver forecast (fct_forecast_monthly,
where a version exists for that month) and ETS on the monthly total. The 80% range comes from the backtest errors
by months ahead. Customers who have not signed yet are not in a bottom-up forecast.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from finance_os.ml import feature_store
from finance_os.ml.customer_panel import SEGMENTS
from finance_os.ml.features import Dense, api_dense, api_features, frame, latest_closed, month_end, segments, today

HORIZONS = (1, 2, 3)
BLOCK = 30
STEP_DAYS = 3
FEATS = ["h7", "h30", "h90", "trend_30_60", "trend_7_30", "on30", "vol30", "req_trend", "req_trend_7d", "error_rate_30d",
         "active_keys_change", "realtime_share_30d", "days_since", *[f"seg_{s}" for s in SEGMENTS]]


def _features(ud, ad, asof, seg):
    h7, h30, h90 = ud.total("h", asof, 0, 7) / 7, ud.total("h", asof, 0, 30) / 30, ud.total("h", asof, 0, 90) / 90
    h60p = ud.total("h", asof, 30, 60) / 60
    on30 = ud.total("on", asof, 0, 30)
    sq = ud.total("h2", asof, 0, 30) / 30
    since = np.full(len(ud.entities), 90.0)
    for d in (1, 3, 7, 14, 30, 60, 90):
        hit = (ud.total("on", asof, 0, d) > 0) & (since == 90)
        since[hit] = d - 1
    af = api_features(ad, asof)
    arows = np.array([ad.ix.get(c, -1) for c in ud.entities])
    a = {k: np.where(arows >= 0, v[np.clip(arows, 0, None)], 0.0) for k, v in af.items()}
    safe = lambda x: np.where(x > 0, x, 1)  # noqa: E731
    f = {"h7": h7, "h30": h30, "h90": h90, "trend_30_60": np.clip(np.where(h60p > 0, h30 / safe(h60p) - 1, 0), -1, 3),
         "trend_7_30": np.clip(np.where(h30 > 0, h7 / safe(h30) - 1, 0), -1, 3), "on30": on30,
         "vol30": np.where(h30 > 0, np.sqrt(np.clip(sq - h30 ** 2, 0, None)) / safe(h30), 0), "days_since": since,
         "req_trend": a["req_trend"], "req_trend_7d": a["req_trend_7d"], "error_rate_30d": a["error_rate_30d"],
         "active_keys_change": a["active_keys_change"], "realtime_share_30d": a["realtime_share_30d"]}
    for s in SEGMENTS:
        f[f"seg_{s}"] = np.array([int(seg.get(c) == s) for c in ud.entities], float)
    return pd.DataFrame(f, index=ud.entities)


def _panel(ud, ad, seg, origins):
    """Rows: (origin, customer) for customers active in the prior 90 days; targets: log ratio of the next blocks'
    daily hours to the last 30 days' (scale-free across customer sizes)."""
    out = []
    for o in origins:
        f = _features(ud, ad, o, seg)
        f = f[f["h90"] > 0].copy()
        if f.empty:
            continue
        rows = [ud.ix[c] for c in f.index]
        for h in HORIZONS:
            tot, ok = ud.ahead("h", o, (h - 1) * BLOCK, BLOCK)
            f[f"y{h}"] = np.log((tot[rows] / BLOCK + 0.01) / (f["h30"].to_numpy() + 0.01)) if ok else np.nan
        f["origin"] = o
        f["customer_id"] = f.index
        out.append(f.reset_index(drop=True))
    return pd.concat(out, ignore_index=True)


def _fit(panel, cutoff):
    """One model per horizon, on origins whose target window ended by the cutoff."""
    models = {}
    for h in HORIZONS:
        ok = panel[(panel["origin"] + pd.Timedelta(days=h * BLOCK) <= cutoff) & panel[f"y{h}"].notna()]
        m = HistGradientBoostingRegressor(loss="absolute_error", max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=30,
                                          l2_regularization=1.0, random_state=7)
        m.fit(ok[FEATS].to_numpy(float), ok[f"y{h}"].to_numpy(float))
        models[h] = (m, len(ok))
    return models


def _price(wh, piv_rev, ud, asof):
    """Revenue per audio hour per customer over the last closed month before asof."""
    m = max((c for c in piv_rev.columns if month_end(c) <= asof), default=None)
    if m is None:
        return {}, None
    hours = ud.total("h", month_end(m), 0, month_end(m).day)
    return {c: float(piv_rev.at[c, m]) / hours[ud.ix[c]] for c in piv_rev.index
            if c in ud.ix and hours[ud.ix[c]] > 0 and piv_rev.at[c, m] > 0}, m


def _forecast_months(models, feats, price, asof):
    """Revenue by calendar month for the next 3 months after asof (month end), per customer."""
    X = feats[FEATS].to_numpy(float)
    out = {}
    for h in HORIZONS:
        ratio = np.exp(models[h][0].predict(X))
        daily = np.clip(ratio * (feats["h30"].to_numpy() + 0.01) - 0.01, 0, None)
        mon = (asof + pd.offsets.MonthBegin(h)).normalize()
        days = mon.days_in_month
        out[mon] = pd.Series(daily * days * np.array([price.get(c, 0.0) for c in feats.index]), index=feats.index)
    return out


def run(wh):
    closed = latest_closed(wh)
    now = today(wh)
    seg = segments(wh)
    u = frame(wh, "select customer_id, usage_date as d, sum(audio_hours) as h from staging.stg_synthetic__usage_daily group by 1, 2")
    u["h"] = u["h"].astype(float)
    u["on"] = (u["h"] > 0).astype(float)
    u["h2"] = u["h"] ** 2
    ud = Dense(u, "customer_id", "d", ["h", "on", "h2"], end=now)
    ad = api_dense(feature_store.load(wh), end=now)
    rev = frame(wh, "select month, customer_id, revenue from marts.fct_customer_revenue_monthly where month <= ?::date", [str(closed.date())])
    rev["month"] = pd.to_datetime(rev["month"])
    piv_rev = rev.pivot_table(index="customer_id", columns="month", values="revenue", aggfunc="sum").fillna(0.0)
    actual = frame(wh, "select month, revenue_usage from intermediate.int_pnl_monthly where month <= ?::date", [str(closed.date())])
    actual = dict(zip(pd.to_datetime(actual["month"]), actual["revenue_usage"].astype(float)))
    drv = frame(wh, "select as_of_month, month, revenue_usage from marts.fct_forecast_monthly where scenario = 'base'")
    drv = {(pd.Timestamp(a), pd.Timestamp(m)): float(v) for a, m, v in drv.itertuples(index=False)}

    origins = list(pd.date_range(ud.start + pd.Timedelta(days=90), now, freq=f"{STEP_DAYS}D"))
    panel = _panel(ud, ad, seg, origins)

    # walk-forward backtest at month ends
    from finance_os.ml.usage import _forecast as ets_forecast
    tot = pd.Series(actual).sort_index()
    bt = []
    for me in [month_end(m) for m in sorted(actual) if month_end(m) >= ud.start + pd.Timedelta(days=270)]:
        models = _fit(panel, me)
        feats = _features(ud, ad, me, seg)
        feats = feats[feats["h90"] > 0]
        price, _ = _price(wh, piv_rev, ud, me)
        fc = _forecast_months(models, feats, price, me)
        ets = ets_forecast(tot[tot.index <= me.replace(day=1)], 3)
        for h, (mon, s) in enumerate(fc.items(), start=1):
            if mon in actual:
                bt.append({"as_of": str(me.date())[:7], "month": str(mon.date())[:7], "months_ahead": h, "actual": round(actual[mon], 2),
                           "ml": round(float(s.sum()), 2), "ets": round(float(ets.loc[mon, "mean"]), 2) if mon in ets.index else None,
                           "driver": drv.get((me.replace(day=1), mon))})
    bt = pd.DataFrame(bt)
    bt["ml_err"] = bt["ml"] / bt["actual"] - 1
    bands = {h: (float(g["ml_err"].quantile(0.1)), float(g["ml_err"].quantile(0.9))) for h, g in bt.groupby("months_ahead")}

    def mape(col, d):
        d = d[d[col].notna()]
        return round(float((d[col] / d["actual"] - 1).abs().mean()), 4) if len(d) else None
    with_drv = bt[bt["driver"].notna()]
    evaluation = {
        "origins_trained_on": int(panel["origin"].nunique()), "customer_origin_rows": int(len(panel)),
        "backtest_forecasts": int(len(bt)),
        "mape_all_origins": {"ml_bottom_up": mape("ml", bt), "ets_total": mape("ets", bt)},
        "mape_where_driver_exists": {"ml_bottom_up": mape("ml", with_drv), "ets_total": mape("ets", with_drv),
                                     "driver": mape("driver", with_drv), "forecasts": int(len(with_drv))},
        "ml_bias": round(float(bt["ml_err"].mean()), 4),
        "by_months_ahead": [{"months_ahead": int(h), "n": int(len(g)), "ml_mape": round(float(g["ml_err"].abs().mean()), 4),
                             "ets_mape": mape("ets", g)} for h, g in bt.groupby("months_ahead")],
    }

    # final: fit on everything that has happened, forecast from the last closed month end
    models = _fit(panel, now)
    me = month_end(closed)
    feats = _features(ud, ad, me, seg)
    feats = feats[feats["h90"] > 0]
    price, _ = _price(wh, piv_rev, ud, me)
    fc = _forecast_months(models, feats, price, me)
    rows, cust = [], []
    for h, (mon, s) in enumerate(fc.items(), start=1):
        lo, hi = bands.get(h, (-0.1, 0.1))
        t = float(s.sum())
        rows.append({"month": str(mon.date())[:7], "months_ahead": h, "forecast": round(t, 2),
                     "low_80": round(t * (1 + lo), 2), "high_80": round(t * (1 + hi), 2),
                     "driver_forecast": drv.get((closed, mon))})
    last = piv_rev[closed] if closed in piv_rev.columns else pd.Series(dtype=float)
    for c in feats.index:
        f1 = float(fc[list(fc)[0]].get(c, 0.0))
        base = float(last.get(c, 0.0))
        cust.append({"customer_id": c, "segment": seg.get(c), "last_month": round(base, 2),
                     "next_3_months": [round(float(fc[m].get(c, 0.0)), 2) for m in fc],
                     "next_month": round(f1, 2), "change_vs_last_month": round(f1 / base - 1, 4) if base else None})
    cust.sort(key=lambda r: -(r["next_month"] or 0))
    e = evaluation["mape_where_driver_exists"]
    card = {
        "model": "gradient boosting per customer and horizon (bottom-up)",
        "target": "each customer's audio hours in the next 1-3 months x their revenue per hour",
        "evaluation": evaluation,
        "headline": (f"trained on {evaluation['customer_origin_rows']:,} customer-origins; backtest MAPE "
                     f"{evaluation['mape_all_origins']['ml_bottom_up']:.1%} over {evaluation['backtest_forecasts']} forecasts "
                     f"(ETS {evaluation['mape_all_origins']['ets_total']:.1%}); where a driver forecast exists: ML "
                     f"{e['ml_bottom_up']:.1%}, ETS {e['ets_total']:.1%}, driver {e['driver']:.1%}") if e["driver"] is not None else "",
        "verdict": ("ML was the most accurate one month out; ETS and the driver forecast were better further out"
                    if evaluation["by_months_ahead"][0]["ml_mape"] < (evaluation["by_months_ahead"][0]["ets_mape"] or 1) else
                    "ETS or the driver forecast was more accurate; use the bottom-up model for the customer detail"),
        "caveat": "Bottom-up: customers not yet signed are not included, so it runs below a forecast that adds new business.",
    }
    return {"as_of": str(closed.date())[:7], "card": card, "rows": rows, "customers": cust,
            "backtest_rows": bt.drop(columns=["ml_err"]).to_dict("records")}
