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
from generator.events.infra import build_cloud_costs, build_gpu_jobs
from generator.events.opex import build_opex_pools
from generator.events.usage import build_usage
from generator.events.vendor_bills import build_vendor_bills

CONFIG = Path(__file__).with_name("config.yaml")


def generate(seed=None):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    rng = random.Random(seed if seed is not None else cfg["seed"])
    customers, mixes = build_customers(cfg, rng)
    usage = build_usage(cfg, customers, mixes, rng)
    gpu_jobs = build_gpu_jobs(cfg, usage, rng)
    cloud_costs = build_cloud_costs(cfg, usage)
    bills, bill_lines = build_vendor_bills(cfg, gpu_jobs, cloud_costs, rng)
    return {
        "products": build_products(cfg),
        "volume_tiers": build_volume_tiers(cfg),
        "customers": customers,
        "customer_product_mix": mixes,
        "usage_daily": usage,
        "gpu_jobs": gpu_jobs,
        "cloud_costs_daily": cloud_costs,
        "vendor_bills": bills,
        "vendor_bill_lines": bill_lines,
        "opex_pools_monthly": build_opex_pools(cfg),
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
