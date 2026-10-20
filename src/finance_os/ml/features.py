"""Point-in-time features shared by the models: every value is computed from data dated on or before the snapshot,
so a backtest never sees the future."""
from datetime import date, timedelta

import numpy as np
import pandas as pd


def frame(wh, sql, params=None):
    return pd.DataFrame(wh.query(sql, params or []))


def latest_closed(wh):
    return pd.Timestamp(str(wh.latest_month())[:10])


def month_end(m):
    return (pd.Timestamp(m) + pd.offsets.MonthEnd(0)).normalize()


class DailyUsage:
    """Daily audio hours per customer as a dense matrix (customers x days), for fast trailing windows."""

    def __init__(self, wh):
        u = frame(wh, """select customer_id, usage_date as d, sum(audio_hours) as h
                         from staging.stg_synthetic__usage_daily group by 1, 2""")
        u["d"] = pd.to_datetime(u["d"])
        u["h"] = u["h"].astype(float)
        self.start, self.end = u["d"].min(), u["d"].max()
        self.days = pd.date_range(self.start, self.end, freq="D")
        piv = u.pivot_table(index="customer_id", columns="d", values="h", aggfunc="sum").reindex(columns=self.days).fillna(0.0)
        self.ids = {c: i for i, c in enumerate(piv.index)}
        self.m = piv.to_numpy()
        self.cum = np.concatenate([np.zeros((self.m.shape[0], 1)), self.m.cumsum(axis=1)], axis=1)

    def _ix(self, d):
        return int((min(pd.Timestamp(d), self.end) - self.start).days) + 1  # columns up to and including d

    def window(self, cid, asof, back, length):
        """Mean daily hours over `length` days ending `back` days before asof."""
        i = self.ids.get(cid)
        if i is None:
            return 0.0
        hi = self._ix(pd.Timestamp(asof) - timedelta(days=back))
        lo = max(hi - length, 0)
        return float(self.cum[i, hi] - self.cum[i, lo]) / length if hi > 0 else 0.0

    def features(self, cid, asof):
        h30, h60 = self.window(cid, asof, 0, 30), self.window(cid, asof, 30, 60)
        trend = (h30 / h60 - 1) if h60 > 0 else (0.0 if h30 == 0 else 1.0)
        i, hi = self.ids.get(cid), self._ix(asof)
        if i is None or hi <= 0:
            return {"hours_per_day_30d": 0.0, "usage_trend": -1.0, "days_since_usage": 120, "active_day_share_30d": 0.0,
                    "usage_volatility_30d": 0.0}
        row = self.m[i, :hi]
        nz = np.nonzero(row)[0]
        since = min(hi - 1 - nz[-1], 120) if len(nz) else 120
        last30 = row[-30:]
        return {"hours_per_day_30d": h30, "usage_trend": float(np.clip(trend, -1, 3)), "days_since_usage": int(since),
                "active_day_share_30d": float((last30 > 0).mean()),
                "usage_volatility_30d": float(last30.std() / last30.mean()) if last30.mean() > 0 else 0.0}


class PaymentHistory:
    """Each customer's invoices, to measure lateness as of any date."""

    def __init__(self, wh):
        inv = frame(wh, """select customer_id, invoice_ref, invoice_date, due_date, paid_date, amount
                           from marts.fct_ar_invoices""")
        for c in ("invoice_date", "due_date", "paid_date"):
            inv[c] = pd.to_datetime(inv[c])
        self.by = {c: g.sort_values("due_date") for c, g in inv.groupby("customer_id")}

    def features(self, cid, asof):
        g = self.by.get(cid)
        asof = pd.Timestamp(asof)
        if g is None:
            return {"avg_days_late_6": 0.0, "overdue_30_count": 0}
        due = g[g["due_date"] <= asof].tail(6)
        settled = due["paid_date"].where(due["paid_date"] <= asof, asof)
        late = (settled - due["due_date"]).dt.days.clip(lower=0)
        open_ = g[(g["due_date"] < asof - timedelta(days=30)) & (g["paid_date"].isna() | (g["paid_date"] > asof))]
        return {"avg_days_late_6": float(late.mean()) if len(late) else 0.0, "overdue_30_count": int(len(open_))}


def revenue_panel(wh):
    r = frame(wh, "select month, customer_id, revenue, movement from marts.fct_customer_revenue_monthly")
    r["month"] = pd.to_datetime(r["month"])
    r["revenue"] = r["revenue"].astype(float)
    return r


def segments(wh):
    return {r["customer_id"]: r["segment"] for r in wh.query("select customer_id, segment from marts.dim_customer")}


def today(wh):
    d = wh.query("select max(usage_date) as d from staging.stg_synthetic__usage_daily")[0]["d"]
    return pd.Timestamp(str(d)[:10]) if d else pd.Timestamp(date.today())


class Dense:
    """Entity x day matrices for several daily metrics, with prefix sums so any trailing window is O(1).
    `frame` has columns entity, day and the metrics; missing days are zero."""

    def __init__(self, frame_, entity, day, metrics, start=None, end=None):
        f = frame_.copy()
        f[day] = pd.to_datetime(f[day])
        self.start = pd.Timestamp(start) if start is not None else f[day].min()
        self.end = pd.Timestamp(end) if end is not None else f[day].max()
        self.days = pd.date_range(self.start, self.end, freq="D")
        self.entities = sorted(f[entity].dropna().unique())
        self.ix = {e: i for i, e in enumerate(self.entities)}
        self.cum = {}
        for m in metrics:
            piv = f.pivot_table(index=entity, columns=day, values=m, aggfunc="sum").reindex(index=self.entities, columns=self.days).fillna(0.0)
            a = piv.to_numpy(float)
            self.cum[m] = np.concatenate([np.zeros((a.shape[0], 1)), a.cumsum(axis=1)], axis=1)

    def col(self, d):
        """Prefix index for 'up to and including day d'."""
        return int(np.clip((pd.Timestamp(d) - self.start).days + 1, 0, len(self.days)))

    def total(self, metric, asof, back, length):
        """Per-entity sum over `length` days ending `back` days before asof (inclusive of asof - back)."""
        hi = self.col(pd.Timestamp(asof) - pd.Timedelta(days=back))
        lo = max(hi - length, 0)
        return self.cum[metric][:, hi] - self.cum[metric][:, lo]

    def ahead(self, metric, asof, skip, length):
        """Per-entity sum over days asof+skip+1 .. asof+skip+length (the target window)."""
        lo = self.col(pd.Timestamp(asof) + pd.Timedelta(days=skip))
        hi = min(lo + length, len(self.days))
        return self.cum[metric][:, hi] - self.cum[metric][:, lo], (lo + length) <= len(self.days)


def api_features(dense, asof):
    """Per-customer behaviour from the request log as of a date: volume trend, error and rate-limit rates, latency,
    API keys, real-time mix. `dense` is a Dense over the feature store."""
    def rate(num, den):
        return np.divide(num, den, out=np.zeros_like(num, dtype=float), where=den > 0)
    r30, r60p = dense.total("requests", asof, 0, 30), dense.total("requests", asof, 30, 60) / 2
    r7 = dense.total("requests", asof, 0, 7) * 30 / 7
    err30 = dense.total("errors", asof, 0, 30)
    err60p = dense.total("errors", asof, 30, 60)
    days30 = dense.total("active", asof, 0, 30)
    return {
        "req_per_day_30d": r30 / 30,
        "req_trend": np.clip(rate(r30 - r60p, r60p), -1, 3),
        "req_trend_7d": np.clip(rate(r7 - r30, r30), -1, 3),
        "error_rate_30d": rate(err30, r30),
        "error_rate_change": rate(err30, r30) - rate(err60p, dense.total("requests", asof, 30, 60)),
        "server_error_rate_30d": rate(dense.total("errors_5xx", asof, 0, 30), r30),
        "rate_limited_rate_30d": rate(dense.total("rate_limited", asof, 0, 30), r30),
        "auth_failure_rate_30d": rate(dense.total("auth_failures", asof, 0, 30), r30),
        "latency_p95_30d": rate(dense.total("latency_p95_x_days", asof, 0, 30), days30),
        "latency_p95_change": rate(dense.total("latency_p95_x_days", asof, 0, 30), days30)
                              - rate(dense.total("latency_p95_x_days", asof, 30, 60), dense.total("active", asof, 30, 60)),
        "active_keys_30d": rate(dense.total("active_keys", asof, 0, 30), days30),
        "active_keys_change": rate(dense.total("active_keys", asof, 0, 30), days30)
                              - rate(dense.total("active_keys", asof, 30, 60), dense.total("active", asof, 30, 60)),
        "realtime_share_30d": rate(dense.total("realtime_requests", asof, 0, 30), r30),
        "active_days_30d": days30,
    }


def api_dense(store, end=None):
    s = store.copy()
    s["errors"] = s["errors_4xx"] + s["errors_5xx"]
    s["active"] = (s["requests"] > 0).astype(float)
    s["latency_p95_x_days"] = s["latency_p95"].fillna(0) * s["active"]
    s["realtime_requests"] = s["realtime_share"].fillna(0) * s["requests"]
    return Dense(s, "customer_id", "usage_date", ["requests", "billable_requests", "audio_hours", "errors", "errors_5xx",
                 "rate_limited", "auth_failures", "latency_p95_x_days", "active", "active_keys", "realtime_requests"], end=end)
