"""Read dbt seeds that the generator shares with the warehouse (one definition, two readers)."""
import csv
from pathlib import Path

SEEDS = Path(__file__).resolve().parents[1] / "warehouse" / "seeds"


def read_seed(name):
    with open(SEEDS / f"{name}.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
