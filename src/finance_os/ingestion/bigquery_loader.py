"""Load generator CSVs into BigQuery raw datasets (raw_synth, raw_infra, raw_erp, raw_payroll, raw_projects).

    python -m finance_os.ingestion.bigquery_loader --src data/synthetic_L [--project finance-os-sivaram]

Uses the same table schemas as the DuckDB loader (synthetic_loader.SCHEMAS), mapped to BigQuery types; money
stays exact (DECIMAL → NUMERIC). Each table is replaced in full, so reruns are safe (NFR-3). Load jobs are free;
the final step that adds _loaded_at scans each table once (small: the raw drivers, not the request events).
Auth is your gcloud login (Application Default Credentials).
"""
import argparse
import re
import time
from pathlib import Path

from google.cloud import bigquery

from finance_os.ingestion.synthetic_loader import SCHEMAS, STRIPE_OBJECTS


def bq_type(duck_type):
    t = duck_type.upper()
    if t.startswith("DECIMAL"):
        precision, scale = map(int, re.findall(r"\d+", t))
        return "NUMERIC" if scale <= 9 and precision - scale <= 29 else "BIGNUMERIC"
    return {"VARCHAR": "STRING", "INTEGER": "INT64", "BIGINT": "INT64", "BOOLEAN": "BOOL", "DATE": "DATE",
            "TIMESTAMP": "TIMESTAMP", "DOUBLE": "FLOAT64"}[t]


def load(src: Path, project: str, location="US"):
    client = bigquery.Client(project=project, location=location)
    for schema in sorted({s for s, _ in SCHEMAS}):
        ds = bigquery.Dataset(f"{project}.{schema}")
        ds.location = location
        client.create_dataset(ds, exists_ok=True)
    total_scanned = 0
    for (schema, table), cols in SCHEMAS.items():
        path = src / f"{table}.csv"
        if not path.exists():
            continue
        tmp = f"{project}.{schema}._load_{table}"
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1, write_disposition="WRITE_TRUNCATE",
            schema=[bigquery.SchemaField(c, bq_type(t)) for c, t in cols.items()], allow_quoted_newlines=True)
        with open(path, "rb") as f:
            client.load_table_from_file(f, tmp, job_config=config).result()
        job = client.query(f"create or replace table `{project}.{schema}.{table}` as "
                           f"select *, current_timestamp() as _loaded_at from `{tmp}`")
        job.result()
        client.delete_table(tmp)
        total_scanned += job.total_bytes_processed or 0
        rows = client.get_table(f"{project}.{schema}.{table}").num_rows
        print(f"{schema}.{table}: {rows:,} rows")
    for ds_name in ("raw_stripe",):
        ds = bigquery.Dataset(f"{project}.{ds_name}")
        ds.location = location
        client.create_dataset(ds, exists_ok=True)
    for obj in STRIPE_OBJECTS:  # one row per object: id + the raw JSON (BigQuery JSON type)
        path = src / "stripe" / f"{obj}.jsonl"
        if not path.exists():
            continue
        tmp = f"{project}.raw_stripe._load_{obj}"
        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON, write_disposition="WRITE_TRUNCATE",
            schema=[bigquery.SchemaField("id", "STRING"), bigquery.SchemaField("data", "JSON")])
        with open(path, "rb") as f:
            client.load_table_from_file(f, tmp, job_config=config).result()
        job = client.query(f"create or replace table `{project}.raw_stripe.{obj}` as "
                           f"select *, current_timestamp() as _loaded_at from `{tmp}`")
        job.result()
        client.delete_table(tmp)
        total_scanned += job.total_bytes_processed or 0
        print(f"raw_stripe.{obj}: {client.get_table(f'{project}.raw_stripe.{obj}').num_rows:,} rows")
    print(f"done; scanned {total_scanned / 1e6:.0f} MB to stamp _loaded_at")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/synthetic")
    p.add_argument("--project", default="finance-os-sivaram")
    a = p.parse_args()
    t = time.time()
    load(Path(a.src), a.project)
    print(f"{time.time() - t:.0f}s")


if __name__ == "__main__":
    main()
