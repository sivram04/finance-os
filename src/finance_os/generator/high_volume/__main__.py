"""Generate high-volume source tables inside the warehouse.

    python -m finance_os.generator.high_volume --engine duckdb                 # local, after the loader (scale S)
    python -m finance_os.generator.high_volume --engine bigquery [--project P]  # after the BigQuery loader (M/L)

Reads the daily drivers already loaded in raw_synth and writes raw_usage.api_requests. On DuckDB only days the
table doesn't have yet are generated and appended (seconds a day); --full rebuilds every day (after a reset). On BigQuery the table is
partitioned by day and clustered by account; generation reads only the small driver tables, so it scans
megabytes, not the gigabytes it writes.
"""
import argparse
import time

import yaml

from finance_os.generator.__main__ import CONFIG
from finance_os.generator.high_volume.usage_events import api_requests_sql, bigquery_dialect, duckdb_dialect
from finance_os.paths import ROOT


def run_duckdb(params, db, full=False):
    """Append only the days the table doesn't have yet (each request's received_at falls on its usage day, so the
    last received date is the last generated day). Generation is deterministic per day, so appended days are
    identical to what a full rebuild would write. --full rebuilds everything: after a generator change or a reset
    of the live company, when past days changed."""
    import duckdb
    from datetime import timedelta
    dx = duckdb_dialect()
    con = duckdb.connect(str(db))
    con.execute("create schema if not exists raw_usage")
    exists = con.execute("select count(*) from information_schema.tables "
                         "where table_schema = 'raw_usage' and table_name = 'api_requests'").fetchone()[0]
    first, last_driver = con.execute("select min(usage_date), max(usage_date) from raw_synth.usage_daily").fetchone()
    done = con.execute("select max(cast(received_at as date)) from raw_usage.api_requests").fetchone()[0] if exists else None
    # guard: if the drivers for days already generated changed (a reset, a generator change), append would keep
    # stale history, so rebuild. The state table holds a checksum of the drivers the table was generated from.
    con.execute("create table if not exists raw_usage.api_requests_state (through_date date, drivers bigint, hours decimal(38,4))")
    state = con.execute("select through_date, drivers, hours from raw_usage.api_requests_state").fetchone()
    check = lambda d: con.execute("select count(*), coalesce(sum(audio_hours), 0) from raw_synth.usage_daily "  # noqa: E731
                                  "where usage_date <= ?", [d]).fetchone()
    stale = state is None or done is None or state[0] != done or tuple(check(done)) != (state[1], state[2])
    if full or not exists or done is None or done < first or stale:
        con.execute(api_requests_sql(dx, params))
        mode, days = "rebuilt", (last_driver - first).days + 1
    else:
        start, end = done + timedelta(days=1), last_driver + timedelta(days=1)
        days = max((end - start).days, 0)
        if days:
            # idempotent: clear anything already written for these days (a run stopped half way), then append
            con.execute(f"delete from raw_usage.api_requests where cast(received_at as date) >= date '{start}'")
            con.execute(api_requests_sql(dx, params, start.isoformat(), end.isoformat(), "insert"))
        mode = "appended"
    n = con.execute("select count(*) from raw_usage.api_requests").fetchone()[0]
    drivers, hours = check(last_driver)
    con.execute("delete from raw_usage.api_requests_state")
    con.execute("insert into raw_usage.api_requests_state values (?, ?, ?)", [last_driver, drivers, hours])
    con.close()
    return {"mode": mode, "days": days, "rows": n}


def run_bigquery(params, project, location="US"):
    """One query per month (first creates the table, the rest append): on-demand BigQuery caps CPU per byte
    scanned, and expanding the whole driver table in one query exceeds it."""
    from google.cloud import bigquery
    client = bigquery.Client(project=project, location=location)
    ds = bigquery.Dataset(f"{project}.raw_usage")
    ds.location = location
    client.create_dataset(ds, exists_ok=True)
    first, last = list(client.query(f"select min(usage_date) a, max(usage_date) b from `{project}.raw_synth.usage_daily`").result())[0]
    dx = bigquery_dialect(project)
    months, m = [], first.replace(day=1)
    while m <= last:
        nxt = m.replace(year=m.year + (m.month == 12), month=m.month % 12 + 1)
        months.append((m, nxt))
        m = nxt
    billed, slots = 0, 0
    for i, (a, b) in enumerate(months):
        job = client.query(api_requests_sql(dx, params, a.isoformat(), b.isoformat(), "create" if i == 0 else "insert"))
        job.result()
        billed += job.total_bytes_billed or 0
        slots += (job.slot_millis or 0) / 1000
        print(f"  {a:%Y-%m}: done ({(job.slot_millis or 0) / 1000:,.0f} slot-s)", flush=True)
    table = client.get_table(f"{project}.raw_usage.api_requests")
    return {"rows": table.num_rows, "logical_gb": round(table.num_bytes / 1e9, 2),
            "bytes_billed_mb": round(billed / 1e6, 1), "slot_seconds": round(slots)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--engine", choices=["duckdb", "bigquery"], default="duckdb")
    p.add_argument("--db", default=str(ROOT / "data" / "finance_os.duckdb"))
    p.add_argument("--project", default="finance-os-sivaram")
    p.add_argument("--print-sql", action="store_true")
    p.add_argument("--full", action="store_true", help="rebuild every day instead of appending new days (duckdb)")
    a = p.parse_args()
    params = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["api_requests"]
    dialect = duckdb_dialect() if a.engine == "duckdb" else bigquery_dialect(a.project)
    if a.print_sql:
        print(api_requests_sql(dialect, params))
        return
    t = time.time()
    stats = run_duckdb(params, a.db, a.full) if a.engine == "duckdb" else run_bigquery(params, a.project)
    print(f"raw_usage.api_requests on {a.engine}: {stats} in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
