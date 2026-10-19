"""Copy every raw_* table from the local DuckDB warehouse to BigQuery, under a dataset prefix.

    python -m finance_os.ingestion.duckdb_to_bigquery [--prefix s_] [--project finance-os-sivaram]

The S company (history + every live day) is built locally first; this mirrors its raw layer to BigQuery
(s_raw_erp, s_raw_stripe, ...) so dbt can build the same models there and the two engines can be compared
to the cent. Tables are exported as Parquet (Stripe's JSON objects as newline-delimited JSON, landing in a
JSON column) and replaced in full, except raw_usage.api_requests, which only appends days BigQuery doesn't
have yet (it is tens of millions of rows); --full replaces it too, after a backfill or a live-company reset. Load jobs are free; nothing here scans data except one small
max(date) query.
"""
import argparse
import tempfile
import time
from pathlib import Path

import duckdb
from google.cloud import bigquery

from finance_os.paths import ROOT

INCREMENTAL = {("raw_usage", "api_requests"): "received_at"}


def _dataset(client, project, name, location):
    ds = bigquery.Dataset(f"{project}.{name}")
    ds.location = location
    client.create_dataset(ds, exists_ok=True)


def copy(db: Path, project: str, prefix: str, location="US", log=print, full=False):
    con = duckdb.connect(str(db), read_only=True)
    client = bigquery.Client(project=project, location=location)
    tables = con.execute("select table_schema, table_name from information_schema.tables "
                         "where table_schema like 'raw_%' order by 1, 2").fetchall()
    tmp = Path(tempfile.mkdtemp(prefix="fos_bq_"))
    for schema in sorted({s for s, _ in tables}):
        _dataset(client, project, prefix + schema, location)
    for schema, table in tables:
        dest = f"{project}.{prefix}{schema}.{table}"
        where, mode = "", bigquery.WriteDisposition.WRITE_TRUNCATE
        col = INCREMENTAL.get((schema, table))
        if col and not full:
            try:
                last = list(client.query(f"select max(date({col})) d from `{dest}`").result())[0].d
            except Exception:  # noqa: BLE001 - first copy: table doesn't exist yet
                last = None
            if last:
                where, mode = f" where cast({col} as date) > date '{last}'", bigquery.WriteDisposition.WRITE_APPEND
        n = con.execute(f"select count(*) from {schema}.{table}{where}").fetchone()[0]
        if n == 0 and mode == bigquery.WriteDisposition.WRITE_APPEND:
            log(f"{prefix}{schema}.{table}: up to date")
            continue
        if schema == "raw_stripe":  # id + raw JSON object, like the ELT tool lands it
            path = tmp / f"{schema}.{table}.jsonl"
            con.execute(f"copy (select id, data, _loaded_at from {schema}.{table}) to '{path.as_posix()}' (format json)")
            cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON, write_disposition=mode,
                                         schema=[bigquery.SchemaField("id", "STRING"), bigquery.SchemaField("data", "JSON"),
                                                 bigquery.SchemaField("_loaded_at", "TIMESTAMP")])
        else:
            path = tmp / f"{schema}.{table}.parquet"
            con.execute(f"copy (select * from {schema}.{table}{where}) to '{path.as_posix()}' (format parquet, compression zstd)")
            cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.PARQUET, write_disposition=mode,
                                         parquet_options=_parquet_opts())
            if col:
                cfg.time_partitioning = bigquery.TimePartitioning(field=col)
                cfg.clustering_fields = ["account_id"]
        t = time.time()
        with open(path, "rb") as f:
            client.load_table_from_file(f, dest, job_config=cfg).result()
        path.unlink()
        log(f"{prefix}{schema}.{table}: {n:,} rows {'appended' if where else 'loaded'} in {time.time() - t:.0f}s")
    con.close()


def _parquet_opts():
    opts = bigquery.ParquetOptions()
    opts.enable_list_inference = True
    return opts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(ROOT / "data" / "finance_os.duckdb"))
    p.add_argument("--project", default="finance-os-sivaram")
    p.add_argument("--prefix", default="s_")
    p.add_argument("--full", action="store_true",
                   help="replace the events table too (after a backfill or a reset of the live company)")
    a = p.parse_args()
    copy(Path(a.db), a.project, a.prefix, full=a.full)


if __name__ == "__main__":
    main()
