"""The request-event generator must split each day's audio exactly and add realistic mess (in-memory DuckDB)."""
import duckdb
import yaml

from finance_os.generator.__main__ import CONFIG
from finance_os.generator.high_volume.usage_events import api_requests_sql, bigquery_dialect, duckdb_dialect

PARAMS = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["api_requests"]


def _db():
    con = duckdb.connect()
    con.execute("create schema raw_synth; create schema raw_usage")
    con.execute("create table raw_synth.products as select * from (values ('batch_pro','echo-pro','batch'), ('stream','echo-stream','streaming')) t(product_id, model, workload)")
    con.execute("create table raw_synth.customers as select * from (values ('EN-001','enterprise'), ('SS-001','self_serve')) t(customer_id, segment)")
    con.execute("""create table raw_synth.usage_daily as select * from (values
        (date '2026-02-27', 'EN-001', 'batch_pro', 1234.5678::decimal(18,4)),
        (date '2026-03-02', 'EN-001', 'stream', 987.0001::decimal(18,4)),
        (date '2026-03-02', 'SS-001', 'batch_pro', 0.0005::decimal(18,4))) t(usage_date, customer_id, product_id, audio_hours)""")
    con.execute(api_requests_sql(duckdb_dialect(), PARAMS))
    return con


def test_billable_requests_add_up_to_the_driver_exactly():
    con = _db()
    rows = con.execute("""
        with ev as (select distinct on (request_id) * from raw_usage.api_requests where status_code = 200 order by request_id, ingested_at),
             agg as (select account_id, cast(received_at as date) d, model,
                            sum(coalesce(audio_duration_ms, cast(round(audio_seconds * 1000) as bigint))) ms, min(coalesce(audio_duration_ms, audio_seconds * 1000)) mn
                     from ev group by all)
        select u.usage_date, cast(round(u.audio_hours * 3600000) as bigint) expected, a.ms, a.mn
        from raw_synth.usage_daily u join raw_synth.products p using (product_id)
        join agg a on a.account_id = u.customer_id and a.d = u.usage_date and a.model = p.model""").fetchall()
    assert len(rows) == 3
    assert all(expected == ms and mn > 0 for _, expected, ms, mn in rows)


def test_mess_is_present_and_schema_changes_on_the_configured_date():
    con = _db()
    r = con.execute("""select count(*) - count(distinct request_id) dups,
                              count(*) filter (where status_code <> 200) failed,
                              bool_and((schema_version = 2) = (cast(received_at as date) >= date '2026-03-01')) v2_by_date,
                              bool_and((audio_duration_ms is null) = (schema_version = 2)) one_format_per_row
                       from raw_usage.api_requests""").fetchone()
    dups, failed, v2_by_date, one_format = r
    assert failed > 0 and v2_by_date and one_format
    assert dups >= 0  # rare by design (0.1%); the S-scale build checks real duplicate removal


def test_bigquery_rendering_partitions_and_appends_by_month():
    dx = bigquery_dialect("p")
    create = api_requests_sql(dx, PARAMS, "2025-01-01", "2025-02-01", "create")
    insert = api_requests_sql(dx, PARAMS, "2025-02-01", "2025-03-01", "insert")
    assert "partition by date(received_at) cluster by account_id" in create
    assert insert.strip().startswith("insert into `p.raw_usage.api_requests`")
    assert "u.usage_date >= date '2025-02-01' and u.usage_date < date '2025-03-01'" in insert
    assert "FARM_FINGERPRINT" in create and "generate_array" in create
