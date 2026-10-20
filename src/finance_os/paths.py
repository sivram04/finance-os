"""Repository paths, resolved from the package location so code works from any working directory."""
import os
from pathlib import Path

# FINANCE_OS_ROOT is set in the container, where the package is installed into site-packages
ROOT = Path(os.environ.get("FINANCE_OS_ROOT") or Path(__file__).resolve().parents[2])
WAREHOUSE = ROOT / "warehouse"
SEEDS = WAREHOUSE / "seeds"
DOCS = ROOT / "docs"
