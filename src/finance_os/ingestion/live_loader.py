"""Append the live company's records (data/live/*.jsonl) to the raw tables the history was loaded into.

Run after synthetic_loader (which rebuilds the raw tables from data/synthetic), so the warehouse sees one
continuous company: history up to the end of the synthetic window, then every simulated day since.
Columns follow synthetic_loader.SCHEMAS; a live table that lacks a column gets NULL. Stripe sandbox objects
pulled by stripe_sandbox.pull are appended to raw_stripe when they belong to the live period.

    python -m finance_os.ingestion.live_loader [--live data/live] [--stripe data/stripe_sandbox] [--db ...]
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from finance_os.ingestion.synthetic_loader import SCHEMAS, STRIPE_OBJECTS

# live file -> raw table (same name unless mapped)
LIVE_TABLES = {
    "journal_entries": ("raw_erp", "journal_entries"),
    "journal_lines": ("raw_erp", "journal_lines"),
    "customer_payments": ("raw_erp", "customer_payments"),
    "vendor_bills": ("raw_erp", "vendor_bills"),
    "vendor_bill_lines": ("raw_erp", "vendor_bill_lines"),
    "usage_daily": ("raw_synth", "usage_daily"),
    "gpu_jobs": ("raw_infra", "gpu_jobs"),
    "cloud_costs_daily": ("raw_infra", "cloud_costs_daily"),
    "customers": ("raw_synth", "customers"),
    "customer_product_mix": ("raw_synth", "customer_product_mix"),
    "lifecycle_events": ("raw_synth", "lifecycle_events"),
    "project_invoices": ("raw_projects", "project_invoices"),
    "project_invoice_lines": ("raw_projects", "project_invoice_lines"),
    "employees": ("raw_payroll", "employees"),
    "pay_runs": ("raw_payroll", "pay_runs"),
    "pay_lines": ("raw_payroll", "pay_lines"),
}


def append_live(con, live: Path):
    counts = {}
    for name, (schema, table) in LIVE_TABLES.items():
        path = live / f"{name}.jsonl"
        if not path.exists() or path.stat().st_size == 0:
            continue
        cols = SCHEMAS[(schema, table)]
        present = set(con.sql(f"select * from read_json_auto('{path.as_posix()}', format='newline_delimited') limit 0").columns)
        select = ", ".join(f"cast({c} as {t}) as {c}" if c in present else f"cast(null as {t}) as {c}" for c, t in cols.items())
        con.execute(f"insert into {schema}.{table} by name select {select}, current_timestamp as _loaded_at "
                    f"from read_json_auto('{path.as_posix()}', format='newline_delimited')")
        counts[f"{schema}.{table}"] = con.execute(f"select count(*) from read_json_auto('{path.as_posix()}', "
                                                  f"format='newline_delimited')").fetchone()[0]
    return counts


def append_stripe(con, stripe_dir: Path, since: datetime):
    """Sandbox objects created since the live period began (earlier test objects are left out)."""
    cutoff = int(since.replace(tzinfo=timezone.utc).timestamp())
    counts = {}
    for obj in STRIPE_OBJECTS:
        path = stripe_dir / "stripe" / f"{obj}.jsonl"
        if not path.exists():
            continue
        rows = [r for r in (json.loads(l) for l in open(path, encoding="utf-8"))
                if (r["data"].get("created") or 0) >= cutoff]
        for r in rows:
            con.execute(f"insert into raw_stripe.{obj} select ?, ?::json, current_timestamp",
                        [r["id"], json.dumps(r["data"])])
        counts[f"raw_stripe.{obj}"] = len(rows)
    return counts


def main():
    from finance_os.paths import ROOT
    p = argparse.ArgumentParser()
    p.add_argument("--live", default=str(ROOT / "data" / "live"))
    p.add_argument("--stripe", default=str(ROOT / "data" / "stripe_sandbox"))
    p.add_argument("--db", default=str(ROOT / "data" / "finance_os.duckdb"))
    a = p.parse_args()
    world = json.loads((Path(a.live) / "world.json").read_text(encoding="utf-8"))
    con = duckdb.connect(a.db)
    print(append_live(con, Path(a.live)))
    since = world["ops"].get("stripe_live_since")
    if since:
        print(append_stripe(con, Path(a.stripe), datetime.fromisoformat(since)))
    con.close()


if __name__ == "__main__":
    main()
