"""Request-level API usage events (raw_usage.api_requests), generated *inside* the warehouse by SQL.

Each daily driver row (customer × product × day × audio hours, from the Python generator) expands into
individual API requests. Durations vary ±30% around the product's average, in pairs whose variations cancel,
and the first request carries the rounding remainder, so a day's billable requests add up to the driver's
audio *exactly* (to the millisecond). That is what lets the warehouse reconcile 300M+ events back to source.

Realistic mess, as in a real request log:
- failed requests (4xx/5xx): logged with audio, never billable
- duplicates: the same request delivered twice, with a later ingested_at
- late arrivals: ingested 1–5 days after they happened
- a logging change: from schema_v2_from, duration is audio_seconds (float) instead of audio_duration_ms (int)

The same template renders for DuckDB (local, scale S) and BigQuery (scale M/L, partitioned by day and
clustered by account), through the small dialect layer below. Randomness is hash-based, so a rerun on the
same engine produces identical rows.
"""
from dataclasses import dataclass


@dataclass
class Dialect:
    name: str
    table: callable          # schema, table -> qualified name
    int_type: str
    str_type: str

    def hash01(self, expr):
        if self.name == "duckdb":
            return f"((hash({expr}) % 1000003) / 1000003.0)"
        return f"(MOD(ABS(FARM_FINGERPRINT({expr})), 1000003) / 1000003.0)"

    def hexid(self, expr):
        return f"substr(md5({expr}), 1, 20)" if self.name == "duckdb" else f"substr(to_hex(md5({expr})), 1, 20)"

    def series(self, n_expr, alias):
        if self.name == "duckdb":
            return f"cross join range({n_expr}) as _g({alias})"
        return f"cross join unnest(generate_array(0, {n_expr} - 1)) as {alias}"

    def ts_plus_seconds(self, ts, secs):
        if self.name == "duckdb":
            return f"({ts} + to_seconds(cast({secs} as bigint)))"
        return f"timestamp_add({ts}, interval cast({secs} as int64) second)"

    def day_ts(self, d):
        return f"cast({d} as timestamp)" if self.name == "duckdb" else f"timestamp({d})"

    def create(self, schema, table):
        if self.name == "duckdb":
            return f"create or replace table {self.table(schema, table)} as"
        return (f"create or replace table {self.table(schema, table)} "
                f"partition by date(received_at) cluster by account_id as")


def duckdb_dialect():
    return Dialect("duckdb", lambda s, t: f"{s}.{t}", "bigint", "varchar")


def bigquery_dialect(project):
    return Dialect("bigquery", lambda s, t: f"`{project}.{s}.{t}`", "int64", "string")


def api_requests_sql(dx: Dialect, params: dict, month_start=None, month_end=None, mode="create") -> str:
    """mode 'create' replaces the table; 'insert' appends. month_start/month_end ('YYYY-MM-DD', end exclusive)
    limit the drivers, so BigQuery can generate month by month: on-demand pricing caps CPU per byte scanned,
    and a single query that expands 46 MB of drivers into ~590M rows exceeds it."""
    p = params
    avg_b, avg_s = p["avg_request_seconds"]["batch"], p["avg_request_seconds"]["streaming"]
    jitter = float(p["duration_jitter"])
    regions = p["regions"]
    I, S = dx.int_type, dx.str_type
    usage, products, customers = (dx.table("raw_synth", "usage_daily"), dx.table("raw_synth", "products"),
                                  dx.table("raw_synth", "customers"))
    region_case = "case " + " ".join(
        f"when cast(floor({dx.hash01('customer_id')} * {len(regions)}) as {I}) = {i} then '{r}'"
        for i, r in enumerate(regions)) + f" else '{regions[0]}' end"

    head = dx.create("raw_usage", "api_requests") if mode == "create" else f"insert into {dx.table('raw_usage', 'api_requests')}"
    window = (f"and u.usage_date >= date '{month_start}' and u.usage_date < date '{month_end}'" if month_start else "")
    return f"""
{head}
with drivers as (
    select
        u.usage_date, u.customer_id, u.product_id, pr.model, pr.workload, c.segment,
        cast(round(u.audio_hours * 3600000) as {I}) as total_ms,
        greatest(1, cast(round(u.audio_hours * 3600 / case pr.workload when 'batch' then {avg_b} else {avg_s} end) as {I})) as n
    from {usage} u
    join {products} pr on pr.product_id = u.product_id
    join {customers} c on c.customer_id = u.customer_id
    where u.audio_hours > 0 {window}
),

d as (
    select *,
        cast(floor(total_ms / n) as {I}) as base_ms,
        total_ms - cast(floor(total_ms / n) as {I}) * n as remainder_ms,
        customer_id || '|' || product_id || '|' || cast(usage_date as {S}) as drv_key
    from drivers
),

billable as (
    select
        d.*, i,
        d.drv_key || '|' || cast(i as {S}) as ev_key,
        -- paired jitter: request 2k gets +j, 2k+1 gets -j (unpaired last request gets none); first takes the remainder
        d.base_ms
          + case when i = 0 then d.remainder_ms else 0 end
          + case when mod(i, 2) = 0 and i + 1 < d.n
                 then cast(floor(d.base_ms * {jitter} * ({dx.hash01("d.drv_key || '|p' || cast(cast(floor(i / 2) as " + I + ") as " + S + ")")} - 0.5)) as {I})
                 when mod(i, 2) = 1
                 then -cast(floor(d.base_ms * {jitter} * ({dx.hash01("d.drv_key || '|p' || cast(cast(floor(i / 2) as " + I + ") as " + S + ")")} - 0.5)) as {I})
                 else 0 end as duration_ms,
        200 as status_code
    from d
    {dx.series("d.n", "i")}
),

failed as (
    select
        d.*, i,
        d.drv_key || '|f' || cast(i as {S}) as ev_key,
        d.base_ms as duration_ms,
        case cast(floor({dx.hash01("d.drv_key || '|s' || cast(i as " + S + ")")} * 6) as {I})
             when 0 then 400 when 1 then 401 when 2 then 413 when 3 then 429 when 4 then 500 else 503 end as status_code
    from d
    {dx.series(f"cast(round(d.n * {p['failed_request_rate']}) as {I})", "i")}
),

events as (
    select * from billable
    union all
    select * from failed
),

shaped as (
    select
        'req_' || {dx.hexid("ev_key")} as request_id,
        {dx.ts_plus_seconds(dx.day_ts("usage_date"), f"floor({dx.hash01("ev_key || '|t'")} * 86400)")} as received_at,
        ev_key,
        customer_id as account_id,
        'key_' || customer_id || '_' || cast(
            cast(floor({dx.hash01("ev_key || '|k'")} * case segment when 'enterprise' then 3 else 1 end) as {I}) as {S}) as api_key_id,
        case workload when 'batch' then '/v2/transcript' else '/v2/realtime' end as endpoint,
        model,
        {region_case} as region,
        status_code,
        usage_date,
        duration_ms,
        case workload when 'batch' then cast(duration_ms * 0.08 as {I}) + cast(floor({dx.hash01("ev_key || '|lat'")} * 4000) as {I})
             else 250 + cast(floor({dx.hash01("ev_key || '|lat'")} * 300) as {I}) end as latency_ms
    from events
),

logged as (
    select
        request_id,
        received_at,
        case when {dx.hash01("ev_key || '|late'")} < {p['late_rate']}
             then {dx.ts_plus_seconds("received_at", f"86400 * (1 + floor({dx.hash01("ev_key || '|ld'")} * 5))")}
             else {dx.ts_plus_seconds("received_at", f"30 + floor({dx.hash01("ev_key || '|ing'")} * 570)")} end as ingested_at,
        account_id, api_key_id, endpoint, model, region, status_code,
        case when usage_date >= date '{p['schema_v2_from']}' then 2 else 1 end as schema_version,
        case when usage_date >= date '{p['schema_v2_from']}' then null else duration_ms end as audio_duration_ms,
        case when usage_date >= date '{p['schema_v2_from']}' then duration_ms / 1000.0 else null end as audio_seconds,
        latency_ms,
        ev_key
    from shaped
)

select request_id, received_at, ingested_at, account_id, api_key_id, endpoint, model, region, status_code,
       schema_version, audio_duration_ms, audio_seconds, latency_ms
from logged
union all
-- duplicates: the same request delivered again an hour later
select request_id, received_at, {dx.ts_plus_seconds("ingested_at", "3600")} as ingested_at, account_id, api_key_id,
       endpoint, model, region, status_code, schema_version, audio_duration_ms, audio_seconds, latency_ms
from logged
where {dx.hash01("ev_key || '|dup'")} < {p['duplicate_rate']}
"""
