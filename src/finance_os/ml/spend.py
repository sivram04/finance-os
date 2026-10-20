"""GPU and cloud spend forecast, next 3 months, per vendor and category: gradient boosting on daily spend (68K
spend lines and 128K GPU jobs rolled up per day), with the company's usage hours as the demand driver.

Each forecast origin (every 2 days) gives a row per series: trailing spend and usage over 7 / 30 / 90 days, their
trends, the GPU-hour rate change, and the target, the log ratio of the next 30-day block's spend to the last 30
days'. Walk-forward backtest at month ends against the current method (fct_spend_forecast: compound growth of the
last 3 months, (m / m-2)^(1/2) - 1, applied to the last month).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from finance_os.ml.features import Dense, frame, latest_closed, month_end, today

HORIZONS = (1, 2, 3)
BLOCK = 30
STEP_DAYS = 2
FEATS = ["c7", "c30", "c90", "c_trend", "c_trend_7", "h30", "h_trend", "h_trend_7", "cost_per_hour", "cost_per_hour_change", "is_gpu", "is_cloud"]


def _series(wh, now):
    s = frame(wh, "select spend_date as d, vendor_id || ' ' || category as series, sum(cost) as cost from marts.fct_tech_spend_daily group by 1, 2")
    s["cost"] = s["cost"].astype(float)
    u = frame(wh, "select usage_date as d, 'all' as k, sum(audio_hours) as h from staging.stg_synthetic__usage_daily group by 1")
    u["h"] = u["h"].astype(float)
    return Dense(s, "series", "d", ["cost"], end=now), Dense(u, "k", "d", ["h"], end=now)


def _features(sd, hd, o):
    c7, c30, c90 = sd.total("cost", o, 0, 7) / 7, sd.total("cost", o, 0, 30) / 30, sd.total("cost", o, 0, 90) / 90
    c60p = sd.total("cost", o, 30, 60) / 60
    h7, h30, h60p = (hd.total("h", o, 0, 7) / 7)[0], (hd.total("h", o, 0, 30) / 30)[0], (hd.total("h", o, 30, 60) / 60)[0]
    cph, cph_p = c30 / max(h30, 1e-9), c60p / max(h60p, 1e-9)
    safe = lambda x: np.where(x > 0, x, 1)  # noqa: E731
    return pd.DataFrame({
        "c7": c7, "c30": c30, "c90": c90, "c_trend": np.clip(np.where(c60p > 0, c30 / safe(c60p) - 1, 0), -1, 3),
        "c_trend_7": np.clip(np.where(c30 > 0, c7 / safe(c30) - 1, 0), -1, 3), "h30": h30,
        "h_trend": (h30 / h60p - 1) if h60p else 0.0, "h_trend_7": (h7 / h30 - 1) if h30 else 0.0,
        "cost_per_hour": cph, "cost_per_hour_change": np.where(cph_p > 0, cph / safe(cph_p) - 1, 0),
        "is_gpu": [int("gpu" in e) for e in sd.entities], "is_cloud": [int("cloud" in e) for e in sd.entities]}, index=sd.entities)


def _panel(sd, hd, origins):
    out = []
    for o in origins:
        f = _features(sd, hd, o)
        for h in HORIZONS:
            tot, ok = sd.ahead("cost", o, (h - 1) * BLOCK, BLOCK)
            f[f"y{h}"] = np.log((tot / BLOCK + 1) / (f["c30"].to_numpy() + 1)) if ok else np.nan
        f["origin"] = o
        f["series"] = f.index
        out.append(f.reset_index(drop=True))
    return pd.concat(out, ignore_index=True)


def _fit(panel, cutoff):
    models = {}
    for h in HORIZONS:
        ok = panel[(panel["origin"] + pd.Timedelta(days=h * BLOCK) <= cutoff) & panel[f"y{h}"].notna()]
        models[h] = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=15,
                                                  random_state=7).fit(ok[FEATS].to_numpy(float), ok[f"y{h}"].to_numpy(float))
    return models


def _predict(models, feats, asof):
    out = {}
    for h in HORIZONS:
        daily = np.clip(np.exp(models[h].predict(feats[FEATS].to_numpy(float))) * (feats["c30"].to_numpy() + 1) - 1, 0, None)
        mon = (asof + pd.offsets.MonthBegin(h)).normalize()
        out[mon] = pd.Series(daily * mon.days_in_month, index=feats.index)
    return out


def _growth(monthly, asof_month, h):
    """The current method, per series: last month x (1 + g)^h, g = (m / m-2)^(1/2) - 1."""
    m0, m2 = monthly.get(asof_month), monthly.get(asof_month - pd.DateOffset(months=2))
    if m0 is None or m2 is None or m2 <= 0:
        return m0
    g = (m0 / m2) ** 0.5 - 1
    return m0 * (1 + g) ** h


def run(wh):
    closed, now = latest_closed(wh), today(wh)
    sd, hd = _series(wh, now)
    m = frame(wh, "select spend_month as m, vendor_id || ' ' || category as series, sum(cost) as cost from marts.fct_tech_spend_daily group by 1, 2")
    m["m"] = pd.to_datetime(m["m"])
    monthly = {s: dict(zip(g["m"], g["cost"].astype(float))) for s, g in m.groupby("series")}
    panel = _panel(sd, hd, list(pd.date_range(sd.start + pd.Timedelta(days=90), now, freq=f"{STEP_DAYS}D")))
    bt = []
    for mm in sorted(set(m["m"])):
        me = month_end(mm)
        if me < sd.start + pd.Timedelta(days=240) or mm > closed:
            continue
        fc = _predict(_fit(panel, me), _features(sd, hd, me), me)
        for h, (mon, s) in enumerate(fc.items(), start=1):
            if mon > closed:
                continue
            act = sum(monthly[k].get(mon, 0.0) for k in monthly)
            gro = sum(_growth(monthly[k], mm, h) or 0.0 for k in monthly)
            bt.append({"as_of": str(mm.date())[:7], "month": str(mon.date())[:7], "months_ahead": h, "actual": round(act, 2),
                       "ml": round(float(s.sum()), 2), "growth_method": round(gro, 2)})
    bt = pd.DataFrame(bt)
    ape = lambda c: round(float((bt[c] / bt["actual"] - 1).abs().mean()), 4)  # noqa: E731
    bt["err"] = bt["ml"] / bt["actual"] - 1
    bands = {h: (float(g["err"].quantile(0.1)), float(g["err"].quantile(0.9))) for h, g in bt.groupby("months_ahead")}
    evaluation = {"origins_x_series": int(len(panel)), "backtest_forecasts": int(len(bt)),
                  "mape": {"ml": ape("ml"), "growth_method": ape("growth_method")},
                  "by_months_ahead": [{"months_ahead": int(h), "ml_mape": round(float(g["err"].abs().mean()), 4),
                                       "growth_mape": round(float((g["growth_method"] / g["actual"] - 1).abs().mean()), 4)}
                                      for h, g in bt.groupby("months_ahead")]}
    me = month_end(closed)
    fc = _predict(_fit(panel, now), _features(sd, hd, me), me)
    rows = []
    for h, (mon, s) in enumerate(fc.items(), start=1):
        lo, hi = bands.get(h, (-0.1, 0.1))
        for k, v in s.items():
            rows.append({"month": str(mon.date())[:7], "months_ahead": h, "series": k, "forecast": round(float(v), 2),
                         "growth_method": round(_growth(monthly[k], closed, h) or 0.0, 2)})
        t = float(s.sum())
        rows.append({"month": str(mon.date())[:7], "months_ahead": h, "series": "total", "forecast": round(t, 2),
                     "low_80": round(t * (1 + lo), 2), "high_80": round(t * (1 + hi), 2),
                     "growth_method": round(sum(_growth(monthly[k], closed, h) or 0.0 for k in monthly), 2)})
    ev = evaluation["mape"]
    card = {"model": "gradient boosting on daily spend with usage as the driver", "target": "GPU and cloud spend, next 3 months",
            "evaluation": evaluation,
            "headline": f"backtest MAPE {ev['ml']:.1%} (ML) vs {ev['growth_method']:.1%} (3-month growth method) over {evaluation['backtest_forecasts']} forecasts",
            "verdict": "ML was more accurate" if ev["ml"] < ev["growth_method"] else "the growth method was as or more accurate",
            "caveat": "Committed-contract shortfalls and announced price changes are not in the model; the driver forecast adds them."}
    return {"as_of": str(closed.date())[:7], "card": card, "rows": rows, "backtest_rows": bt.drop(columns=["err"]).to_dict("records")}
