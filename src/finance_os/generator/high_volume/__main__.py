"""Generate high-volume source tables inside the warehouse.

    python -m finance_os.generator.high_volume --engine duckdb                 # local, after the loader (scale S)
    python -m finance_os.generator.high_volume --engine bigquery [--project P]  # after the BigQuery loader (M/L)

Reads the daily drivers already loaded in raw_synth and writes raw_usage.api_requests. On BigQuery the table is
partitioned by day and clustered by account; generation reads only the small driver tables, so it scans
megabytes, not the gigabytes it writes.
"""
import argparse
import time

import yaml

from finance_os.generator.__main__ import CONFIG
from finance_os.generator.high_volume.usage_events import api_requests_sql, bigquery_dialect, duckdb_dialect
from finance_os.paths import ROOT


def run_duckdb(sql, db):
    import duckdb
    con = duckdb.connect(str(db))
    con.execute("create schema if not exists raw_usage")
    con.execute(sql)
    n = con.execute("select count(*) from raw_usage.api_requests").fetchone()[0]
    con.close()
    return {"rows": n}


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
    a = p.parse_args()
    params = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["api_requests"]
    dialect = duckdb_dialect() if a.engine == "duckdb" else bigquery_dialect(a.project)
    if a.print_sql:
        print(api_requests_sql(dialect, params))
        return
    t = time.time()
    stats = run_duckdb(api_requests_sql(dialect, params), a.db) if a.engine == "duckdb" else run_bigquery(params, a.project)
    print(f"raw_usage.api_requests on {a.engine}: {stats} in {time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
