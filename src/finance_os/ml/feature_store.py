"""Customer x day features from the raw API request log (about 200 million rows), built in DuckDB and kept as a
Parquet file (data/ml/api_daily.parquet). Rebuilt in one pass; the daily job only re-reads the last few days
(late deliveries arrive up to 3 days later) and merges them in.

Per customer and day: requests, billable requests and audio hours, client errors (4xx), server errors (5xx),
rate-limited (429) and auth failures (401), latency p50 / p95, active API keys, regions, the real-time share of
requests, and late-delivered events. Duplicate deliveries are counted once (first delivery wins), as in
stg_usage__api_requests.
"""
import time

import pandas as pd

from finance_os.ml import OUT

PATH = OUT / "api_daily.parquet"
LOOKBACK_DAYS = 4

SQL = """
with ev as (
    select *, row_number() over (partition by request_id order by ingested_at) as k
    from raw_usage.api_requests
    where received_at >= ?::timestamp and received_at < ?::timestamp
)
select
    cast(received_at as date) as usage_date,
    account_id as customer_id,
    count(*) as requests,
    count(*) filter (where status_code = 200) as billable_requests,
    sum(case when status_code = 200 then coalesce(audio_duration_ms, cast(round(audio_seconds * 1000) as bigint)) end) / 3600000.0 as audio_hours,
    count(*) filter (where status_code between 400 and 499) as errors_4xx,
    count(*) filter (where status_code >= 500) as errors_5xx,
    count(*) filter (where status_code = 429) as rate_limited,
    count(*) filter (where status_code = 401) as auth_failures,
    approx_quantile(latency_ms, 0.5) as latency_p50,
    approx_quantile(latency_ms, 0.95) as latency_p95,
    count(distinct api_key_id) as active_keys,
    count(distinct region) as regions,
    avg(case when endpoint like '%realtime%' then 1.0 else 0.0 end) as realtime_share,
    avg(case when cast(ingested_at as date) > cast(received_at as date) then 1.0 else 0.0 end) as late_share
from ev
where k = 1
group by 1, 2
"""


def _range(wh, start, end):
    return pd.DataFrame(wh.query(SQL, [str(start), str(end)]))


def build(wh, full=False, log=print):
    """Create or refresh the feature store. Month by month on a full build to keep memory flat."""
    t0 = time.perf_counter()
    lo, hi = (pd.Timestamp(str(x)[:10]) for x in wh.query(
        "select min(received_at) as a, max(received_at) as b from raw_usage.api_requests")[0].values())
    end = hi + pd.Timedelta(days=1)
    if PATH.exists() and not full:
        old = pd.read_parquet(PATH)
        start = pd.Timestamp(old["usage_date"].max()) - pd.Timedelta(days=LOOKBACK_DAYS)
        new = _range(wh, start, end)
        old = old[pd.to_datetime(old["usage_date"]) < start]
        df = pd.concat([old, new], ignore_index=True)
    else:
        parts, m = [], lo.replace(day=1)
        while m < end:
            nxt = m + pd.offsets.MonthBegin(1)
            parts.append(_range(wh, m, min(nxt, end)))
            m = nxt
        df = pd.concat(parts, ignore_index=True)
    df["usage_date"] = pd.to_datetime(df["usage_date"])
    df = df.sort_values(["customer_id", "usage_date"]).reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PATH, index=False)
    log(f"feature store: {len(df):,} customer-days from the request log in {time.perf_counter() - t0:.0f}s")
    return df


def load(wh=None):
    if not PATH.exists():
        if wh is None:
            raise FileNotFoundError(PATH)
        return build(wh)
    df = pd.read_parquet(PATH)
    df["usage_date"] = pd.to_datetime(df["usage_date"])
    return df


def raw_rows(wh):
    return int(wh.query("select count(*) as n from raw_usage.api_requests")[0]["n"])
