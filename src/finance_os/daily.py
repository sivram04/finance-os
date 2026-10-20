"""The morning job: move the live company forward to today and refresh everything that reads from it.

    python -m finance_os.daily [--no-stripe] [--skip-dbt]

Steps (each logged to data/live/logs/<date>.log; a failed step stops the run and is retried next morning):
  1 simulate     every day since the last run, through today (AI decides events, code applies them)
  2 stripe pull  what the Stripe sandbox actually recorded (when a key is set)
  3 load         rebuild raw tables from history, then append the live records and live Stripe objects
  4 events       regenerate request-level usage events from the (now longer) daily drivers
  5 ap intake    read every vendor bill PDF in the inbox (rules extractor; offline)
  6 dbt build    models + tests, so forecasts, cash, close, AR and AP include today
  7 alerts       new alert conditions go out as one digest (Slack / email / Telegram, or the outbox file)
    reports      recurring reports due today (seeds/report_schedule.csv), saved to reports/ and delivered
  8 bigquery     copy the raw layer to BigQuery (s_* datasets; events append only new days) and build there
                 too (incremental; the full-scan event tests are skipped). Uses your gcloud login.
A lock file stops two runs overlapping (e.g. a manual run while the scheduled one is going).
Scheduled by scripts/schedule_daily.ps1 (Windows Task Scheduler, 7:00, runs late if the laptop was off).
"""
import argparse
import os
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT, WAREHOUSE

LIVE = ROOT / "data" / "live"
DB = ROOT / "data" / "finance_os.duckdb"
LOCK = LIVE / "daily.lock"
PY = sys.executable


class Log:
    def __init__(self):
        (LIVE / "logs").mkdir(parents=True, exist_ok=True)
        self.path = LIVE / "logs" / f"{date.today()}.log"

    def __call__(self, msg):
        line = f"{datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def sh(log, name, args, cwd=ROOT):
    t = time.time()
    run = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    tail = (run.stdout + run.stderr).strip().splitlines()[-6:]
    log(f"[{name}] exit {run.returncode} in {time.time() - t:.0f}s" + "".join(f"\n    {l}" for l in tail))
    if run.returncode != 0:
        raise RuntimeError(f"{name} failed")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-stripe", action="store_true")
    p.add_argument("--skip-dbt", action="store_true")
    p.add_argument("--no-bigquery", action="store_true", help="local warehouse only")
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    LIVE.mkdir(parents=True, exist_ok=True)
    log = Log()
    if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 6 * 3600:
        log("another run is in progress (lock file); exiting")
        return 0
    LOCK.write_text(str(os.getpid()))
    no_stripe = a.no_stripe or not os.environ.get("STRIPE_SECRET_KEY")
    try:
        log("== daily run ==")
        from finance_os.simulator.__main__ import run
        s = run(no_stripe=no_stripe, log=lambda m: log(f"[simulate] {m}"))
        if s["fallbacks"]:
            log(f"[simulate] note: {s['fallbacks']} day(s) used a fallback provider (see agent_calls.jsonl fallback_from)")
        if not no_stripe:
            sh(log, "stripe pull", [PY, "-m", "finance_os.ingestion.stripe_sandbox", "pull"])
        sh(log, "load history", [PY, "-m", "finance_os.ingestion.synthetic_loader", "--db", str(DB)])
        sh(log, "load live", [PY, "-m", "finance_os.ingestion.live_loader", "--db", str(DB)])
        sh(log, "usage events", [PY, "-m", "finance_os.generator.high_volume", "--engine", "duckdb"])
        sh(log, "ap intake", [PY, "-m", "finance_os.ingestion.ap_intake", "--backend", "text"])
        if not a.skip_dbt:
            dbt = str(Path(PY).with_name("dbt.exe" if os.name == "nt" else "dbt"))
            sh(log, "dbt build", [dbt, "build", "--target", "local"], cwd=WAREHOUSE)
            from finance_os import alerts
            alerts.run(log=lambda m: log(f"[alerts] {m}"))
            from finance_os.reports import scheduled
            scheduled.run(log=lambda m: log(f"[reports] {m}"))
            from finance_os.app import tools
            log(f"[forecast] snapshot: {tools.save_forecast_snapshot(tools.Warehouse())} row(s)")
            from finance_os import ml
            ml.train_all(tools.Warehouse(), log=lambda m: log(f"[ml] {m}"))  # also refreshes the request-log features
        if not a.no_bigquery and not a.skip_dbt:
            sh(log, "bigquery copy", [PY, "-m", "finance_os.ingestion.duckdb_to_bigquery", "--prefix", "s_"])
            sh(log, "bigquery build", [dbt, "build", "--target", "cloud", "--vars", "dataset_prefix: s_",
                                       "--exclude", "tag:full_scan"], cwd=WAREHOUSE)
        log(f"== done: {s['days']} day(s) simulated through {s['as_of']}, cash {s['cash']} ==")
        return 0
    except Exception as err:  # noqa: BLE001 - logged; the next run retries
        log(f"== FAILED: {err} ==")
        return 1
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
