"""Ship the day's data to the deployed app (Option A: the laptop generates and builds; the cloud app only serves).

    python -m finance_os.deploy            # build the snapshot and upload it (the daily job runs this)
    python -m finance_os.deploy --no-upload

snapshot   a slim copy of the warehouse with everything the app reads: every staging, intermediate, mart, seed,
           recon and alert relation, materialised as tables, without the raw request log (~200M rows, used only
           to build the ML feature store) or other raw tables, except the two raw tables the app queries.
upload     the snapshot, data/ml/*.json (model outputs) and alerts.duckdb to gs://<bucket>/current/, then a
           manifest.json last, which the app polls to pick up a new day.

The app side is finance_os.app.cloud_data.
"""
import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

import duckdb

from finance_os.paths import ROOT

WAREHOUSE = ROOT / "data" / "finance_os.duckdb"
OUT = ROOT / "data" / "deploy"
SNAPSHOT = OUT / "finance_os_app.duckdb"
BUCKET = os.environ.get("FINANCE_OS_DATA_BUCKET", "finance-os-app-sivaram-data")
SKIP_RELATIONS = {("staging", "stg_usage__api_requests")}  # a view over the raw request log
RAW_KEEP = {("raw_ar", "collection_drafts"), ("raw_erp", "budgets")}


def snapshot(log=print):
    t0 = time.perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute(f"attach '{WAREHOUSE.as_posix()}' as finance_os (read_only)")
    rels = con.execute("""select table_schema, table_name from information_schema.tables
                          where table_catalog = 'finance_os' order by 1, 2""").fetchall()
    copied, skipped = 0, []
    for schema, name in rels:
        if (schema, name) in SKIP_RELATIONS or (schema.startswith("raw_") and (schema, name) not in RAW_KEEP):
            continue
        con.execute(f'create schema if not exists "{schema}"')
        try:
            con.execute(f'create table "{schema}"."{name}" as select * from finance_os."{schema}"."{name}"')
            copied += 1
        except duckdb.Error as e:  # a view over a relation left out
            skipped.append(f"{schema}.{name}: {str(e).splitlines()[0][:80]}")
    con.execute("detach finance_os")
    con.execute("checkpoint")
    con.close()
    os.replace(tmp, SNAPSHOT)
    mb = SNAPSHOT.stat().st_size / 1e6
    log(f"snapshot: {copied} relations, {mb:,.0f} MB in {time.perf_counter() - t0:.0f}s"
        + (f"; skipped {len(skipped)}: {'; '.join(skipped[:5])}" if skipped else ""))
    return {"relations": copied, "mb": round(mb, 1), "skipped": skipped}


def _gcloud():
    return shutil.which("gcloud") or shutil.which("gcloud.cmd") or "gcloud"


def upload(log=print):
    files = [SNAPSHOT, ROOT / "data" / "alerts.duckdb", ROOT / "data" / "live" / "world.json",
             *sorted((ROOT / "data" / "ml").glob("*.json"))]
    files = [f for f in files if f.exists()]
    dest = f"gs://{BUCKET}/current/"
    subprocess.run([_gcloud(), "storage", "cp", *[str(f) for f in files], dest], check=True, capture_output=True)
    con = duckdb.connect(str(SNAPSHOT), read_only=True)
    through = con.execute("select max(entry_date) from staging.stg_erp__journal_entries").fetchone()[0]
    con.close()
    manifest = {"uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "data_through": str(through),
                "files": [f.name for f in files]}
    m = OUT / "manifest.json"
    m.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    subprocess.run([_gcloud(), "storage", "cp", str(m), dest], check=True, capture_output=True)
    log(f"uploaded {len(files)} files to {dest} (data through {through})")
    return manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-upload", action="store_true")
    a = p.parse_args()
    snapshot()
    if not a.no_upload:
        upload()


if __name__ == "__main__":
    main()
