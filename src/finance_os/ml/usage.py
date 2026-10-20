"""Usage revenue forecast: damped-trend exponential smoothing (ETS, additive errors) on monthly usage revenue,
next 6 months with an 80% range, in total and by segment.

Backtest: refit as of each month the driver forecast was run (fct_forecast_monthly, base scenario) using only
data up to then, and compare both forecasts with the actuals that have since closed (MAPE by months ahead, and
how often the actual fell inside the 80% range). Monthly history is under two years, so no seasonality is fitted.
"""
import warnings

import numpy as np
import pandas as pd
from statsmodels.tsa.exponential_smoothing.ets import ETSModel

from finance_os.ml.features import frame, latest_closed

HORIZON = 6
ALPHA = 0.2  # 80% range


def _fit(y):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ETSModel(y, error="add", trend="add", damped_trend=True).fit(disp=False)


def _forecast(y, h):
    """y: monthly series (DatetimeIndex, month start). Returns a frame of mean, lo, hi for the next h months."""
    y = y.asfreq("MS")
    fit = _fit(y)
    pr = fit.get_prediction(start=len(y), end=len(y) + h - 1).summary_frame(alpha=ALPHA)
    pr.index = pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=h, freq="MS")
    return pr.rename(columns={"pi_lower": "lo", "pi_upper": "hi"})[["mean", "lo", "hi"]].clip(lower=0)


def _series(wh):
    closed = latest_closed(wh)
    tot = frame(wh, "select month, revenue_usage as v from intermediate.int_pnl_monthly where month <= ?::date order by month", [str(closed.date())])
    tot["month"] = pd.to_datetime(tot["month"])
    seg = frame(wh, """select r.month, c.segment, sum(r.revenue) as v from marts.fct_customer_revenue_monthly r
                       join marts.dim_customer c using (customer_id) where r.month <= ?::date group by 1, 2 order by 1""", [str(closed.date())])
    seg["month"] = pd.to_datetime(seg["month"])
    out = {"total": tot.set_index("month")["v"].astype(float)}
    for s, g in seg.groupby("segment"):
        out[s] = g.set_index("month")["v"].astype(float)
    return out


def _backtest(wh, y):
    drv = frame(wh, """select as_of_month, month, months_ahead, revenue_usage from marts.fct_forecast_monthly
                       where scenario = 'base' order by 1, 2""")
    if drv.empty:
        return [], {}
    drv["as_of_month"], drv["month"] = pd.to_datetime(drv["as_of_month"]), pd.to_datetime(drv["month"])
    rows = []
    for asof, g in drv.groupby("as_of_month"):
        hist = y[y.index <= asof]
        if len(hist) < 12:
            continue
        fc = _forecast(hist, HORIZON)
        for r in g.itertuples():
            if r.month not in y.index or r.months_ahead > HORIZON or r.month not in fc.index:
                continue
            a = float(y[r.month])
            e = fc.loc[r.month]
            rows.append({"as_of": str(asof.date())[:7], "month": str(r.month.date())[:7], "months_ahead": int(r.months_ahead),
                         "actual": round(a, 2), "ets": round(float(e["mean"]), 2), "ets_lo": round(float(e["lo"]), 2),
                         "ets_hi": round(float(e["hi"]), 2), "driver": round(float(r.revenue_usage), 2)})
    bt = pd.DataFrame(rows)
    if bt.empty:
        return [], {}
    bt["ets_ape"] = (bt["ets"] - bt["actual"]).abs() / bt["actual"]
    bt["drv_ape"] = (bt["driver"] - bt["actual"]).abs() / bt["actual"]
    by_h = [{"months_ahead": int(h), "n": int(len(g)), "ets_mape": round(float(g["ets_ape"].mean()), 4),
             "driver_mape": round(float(g["drv_ape"].mean()), 4)} for h, g in bt.groupby("months_ahead")]
    summary = {"forecasts_compared": int(len(bt)), "ets_mape": round(float(bt["ets_ape"].mean()), 4),
               "driver_mape": round(float(bt["drv_ape"].mean()), 4),
               "ets_bias": round(float(((bt["ets"] - bt["actual"]) / bt["actual"]).mean()), 4),
               "driver_bias": round(float(((bt["driver"] - bt["actual"]) / bt["actual"]).mean()), 4),
               "range_coverage": round(float(((bt["actual"] >= bt["ets_lo"]) & (bt["actual"] <= bt["ets_hi"])).mean()), 3),
               "by_months_ahead": by_h}
    return rows, summary


def run(wh):
    series = _series(wh)
    y = series["total"]
    rows = []
    for name, s in series.items():
        if len(s) < 12:
            continue
        fc = _forecast(s, HORIZON)
        for m, r in fc.iterrows():
            rows.append({"series": name, "month": str(m.date())[:7], "forecast": round(float(r["mean"]), 2),
                         "low_80": round(float(r["lo"]), 2), "high_80": round(float(r["hi"]), 2)})
    history = [{"month": str(m.date())[:7], "actual": round(float(v), 2)} for m, v in y.items()]
    drv = frame(wh, """select strftime(month, '%Y-%m') as month, revenue_usage from marts.fct_forecast_monthly
                       where scenario = 'base' and is_latest order by month limit ?""", [HORIZON])
    driver = {r["month"]: round(float(r["revenue_usage"]), 2) for r in drv.to_dict("records")}
    for r in rows:
        if r["series"] == "total":
            r["driver_forecast"] = driver.get(r["month"])
    bt_rows, bt = _backtest(wh, y)
    fit = _fit(y.asfreq("MS"))
    p = dict(zip(fit.param_names, np.asarray(fit.params, dtype=float)))
    better = bt and bt["ets_mape"] < bt["driver_mape"]
    card = {
        "model": "ETS (additive error, damped additive trend)",
        "target": "monthly usage revenue, next 6 months, 80% range",
        "history_months": int(len(y)), "parameters": {k: round(float(p[k]), 4) for k in ("smoothing_level", "smoothing_trend", "damping_trend") if k in p},
        "backtest": bt,
        "headline": (f"ETS backtest MAPE {bt['ets_mape']:.1%} vs driver forecast {bt['driver_mape']:.1%} over "
                     f"{bt['forecasts_compared']} forecasts; actuals inside the 80% range {bt['range_coverage']:.0%} of the time")
                    if bt else "no driver forecast versions to compare with yet",
        "verdict": ("ETS was more accurate than the driver forecast in the backtest" if better else
                    "the driver forecast was as or more accurate in the backtest; use ETS as a cross-check and for its range") if bt else None,
        "caveat": "Under two years of monthly history: no seasonality is fitted, and the backtest covers only the last "
                  "few forecast versions.",
    }
    return {"as_of": str(latest_closed(wh).date())[:7], "card": card, "rows": rows, "history": history, "backtest_rows": bt_rows}
