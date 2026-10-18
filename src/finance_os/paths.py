"""Repository paths, resolved from the package location so code works from any working directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE = ROOT / "warehouse"
SEEDS = WAREHOUSE / "seeds"
DOCS = ROOT / "docs"
