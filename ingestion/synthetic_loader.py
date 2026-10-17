"""Load generator CSVs into DuckDB raw schemas (raw_synth, raw_infra, raw_erp) with explicit types (money as DECIMAL, NFR-1).

    python -m ingestion.synthetic_loader [--src data/synthetic] [--db data/finance_os.duckdb]

Full replace each run, so it is safe to rerun (NFR-3).
"""
import argparse
from pathlib import Path

import duckdb

# (schema, table) -> column types
SCHEMAS = {
    ("raw_synth", "products"): {"product_id": "VARCHAR", "model": "VARCHAR", "workload": "VARCHAR",
                 "list_price_per_hour": "DECIMAL(18,4)"},
    ("raw_synth", "volume_tiers"): {"tier": "INTEGER", "min_hours_month": "INTEGER", "discount_pct": "DECIMAL(5,4)"},
    ("raw_synth", "customers"): {"customer_id": "VARCHAR", "customer_name": "VARCHAR", "segment": "VARCHAR",
                  "signup_date": "DATE", "start_hours_month": "INTEGER", "monthly_growth": "DECIMAL(6,4)"},
    ("raw_synth", "customer_product_mix"): {"customer_id": "VARCHAR", "product_id": "VARCHAR", "share": "DECIMAL(5,4)"},
    ("raw_synth", "usage_daily"): {"usage_date": "DATE", "customer_id": "VARCHAR", "product_id": "VARCHAR",
                    "audio_hours": "DECIMAL(18,4)", "requests": "INTEGER"},
    ("raw_synth", "anomaly_manifest"): {"anomaly_id": "VARCHAR", "module": "VARCHAR", "kind": "VARCHAR",
                                        "entity_id": "VARCHAR", "start_date": "DATE", "description": "VARCHAR",
                                        "expected_detection": "VARCHAR"},
    ("raw_infra", "gpu_jobs"): {"job_id": "VARCHAR", "job_date": "DATE", "customer_id": "VARCHAR",
                                "product_id": "VARCHAR", "model": "VARCHAR", "workload": "VARCHAR",
                                "gpu_type": "VARCHAR", "gpu_seconds": "BIGINT", "region": "VARCHAR",
                                "label_team": "VARCHAR", "label_env": "VARCHAR"},
    ("raw_infra", "cloud_costs_daily"): {"usage_date": "DATE", "service": "VARCHAR", "sku": "VARCHAR",
                                         "label_team": "VARCHAR", "label_env": "VARCHAR",
                                         "cost": "DECIMAL(18,6)"},
    ("raw_erp", "opex_pools_monthly"): {"month": "DATE", "pool": "VARCHAR", "amount": "DECIMAL(18,2)"},
}


def load(src: Path, db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    for (schema, table), cols in SCHEMAS.items():
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        path = (src / f"{table}.csv").as_posix()
        types = ", ".join(f"'{c}': '{t}'" for c, t in cols.items())
        con.execute(
            f"CREATE OR REPLACE TABLE {schema}.{table} AS "
            f"SELECT *, current_timestamp AS _loaded_at "
            f"FROM read_csv('{path}', header=true, columns={{{types}}})"
        )
        n = con.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
        print(f"{schema}.{table}: {n} rows")
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/synthetic")
    p.add_argument("--db", default="data/finance_os.duckdb")
    a = p.parse_args()
    load(Path(a.src), Path(a.db))


if __name__ == "__main__":
    main()
