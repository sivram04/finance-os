"""Generate Echo Labs synthetic data as CSVs.

    python -m generator [--out data/synthetic] [--seed N]

Same seed → byte-identical output (NFR-2).
"""
import argparse
import csv
import random
from pathlib import Path

import yaml

from generator.anomalies import build_manifest
from generator.entities.catalog import build_products, build_volume_tiers
from generator.entities.customers import build_customers
from generator.entities.employees import build_employees
from generator.entities.lifecycle import build_lifecycle
from generator.events.infra import build_cloud_costs, build_gpu_jobs
from generator.events.ledger import build_ledger
from generator.events.payroll import build_payroll
from generator.events.usage import build_usage
from generator.events.vendor_bills import build_vendor_bills

CONFIG = Path(__file__).with_name("config.yaml")


def generate(seed=None):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    rng = random.Random(seed if seed is not None else cfg["seed"])
    customers, mixes = build_customers(cfg, rng)
    lifecycle = build_lifecycle(cfg, customers, mixes, rng)
    usage = build_usage(cfg, customers, mixes, lifecycle, rng)
    gpu_jobs = build_gpu_jobs(cfg, usage, rng)
    cloud_costs = build_cloud_costs(cfg, usage)
    bills, bill_lines = build_vendor_bills(cfg, gpu_jobs, cloud_costs, rng)
    employees = build_employees(cfg, rng)
    pay_runs, pay_lines = build_payroll(cfg, employees)
    entries, lines = build_ledger(cfg, customers, usage, lifecycle, cloud_costs, bills, bill_lines, pay_lines, employees, rng)
    return {
        "products": build_products(cfg),
        "volume_tiers": build_volume_tiers(cfg),
        "customers": customers,
        "customer_product_mix": mixes,
        "lifecycle_events": lifecycle,
        "usage_daily": usage,
        "gpu_jobs": gpu_jobs,
        "cloud_costs_daily": cloud_costs,
        "vendor_bills": bills,
        "vendor_bill_lines": bill_lines,
        "employees": employees,
        "pay_runs": pay_runs,
        "pay_lines": pay_lines,
        "journal_entries": entries,
        "journal_lines": lines,
        "anomaly_manifest": build_manifest(cfg),
    }


def write_csvs(tables, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--seed", type=int)
    a = p.parse_args()
    tables = generate(a.seed)
    write_csvs(tables, Path(a.out))
    for name, rows in tables.items():
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
