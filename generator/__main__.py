"""Generate Echo Labs synthetic data as CSVs.

    python -m generator [--out data/synthetic] [--seed N]

Same seed → byte-identical output (NFR-2).
"""
import argparse
import csv
import random
from pathlib import Path

import yaml

from generator.entities.catalog import build_products, build_volume_tiers
from generator.entities.customers import build_customers
from generator.events.usage import build_usage

CONFIG = Path(__file__).with_name("config.yaml")


def generate(seed=None):
    cfg = yaml.safe_load(CONFIG.read_text())
    rng = random.Random(seed if seed is not None else cfg["seed"])
    customers, mixes = build_customers(cfg, rng)
    return {
        "products": build_products(cfg),
        "volume_tiers": build_volume_tiers(cfg),
        "customers": customers,
        "customer_product_mix": mixes,
        "usage_daily": build_usage(cfg, customers, mixes, rng),
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
