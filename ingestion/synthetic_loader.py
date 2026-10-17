"""Load generator CSVs into DuckDB schema raw_synth with explicit types (money as DECIMAL, NFR-1).

    python -m ingestion.synthetic_loader [--src data/synthetic] [--db data/finance_os.duckdb]

Full replace each run, so it is safe to rerun (NFR-3).
"""
import argparse
from pathlib import Path

import duckdb

SCHEMAS = {
    "products": {"product_id": "VARCHAR", "model": "VARCHAR", "workload": "VARCHAR",
                 "list_price_per_hour": "DECIMAL(18,4)"},
    "volume_tiers": {"tier": "INTEGER", "min_hours_month": "INTEGER", "discount_pct": "DECIMAL(5,4)"},
    "customers": {"customer_id": "VARCHAR", "customer_name": "VARCHAR", "segment": "VARCHAR",
                  "signup_date": "DATE", "start_hours_month": "INTEGER", "monthly_growth": "DECIMAL(6,4)"},
    "customer_product_mix": {"customer_id": "VARCHAR", "product_id": "VARCHAR", "share": "DECIMAL(5,4)"},
    "usage_daily": {"usage_date": "DATE", "customer_id": "VARCHAR", "product_id": "VARCHAR",
                    "audio_hours": "DECIMAL(18,4)"},
}


def load(src: Path, db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_synth")
    for table, cols in SCHEMAS.items():
        path = (src / f"{table}.csv").as_posix()
        types = ", ".join(f"'{c}': '{t}'" for c, t in cols.items())
        con.execute(
            f"CREATE OR REPLACE TABLE raw_synth.{table} AS "
            f"SELECT *, current_timestamp AS _loaded_at "
            f"FROM read_csv('{path}', header=true, columns={{{types}}})"
        )
        n = con.execute(f"SELECT count(*) FROM raw_synth.{table}").fetchone()[0]
        print(f"raw_synth.{table}: {n} rows")
    con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/synthetic")
    p.add_argument("--db", default="data/finance_os.duckdb")
    a = p.parse_args()
    load(Path(a.src), Path(a.db))


if __name__ == "__main__":
    main()
