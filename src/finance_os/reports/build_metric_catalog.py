"""Build the metric catalog seed and Markdown page from warehouse/metrics/kpis.yml.

    python -m finance_os.reports.build_metric_catalog

Writes warehouse/seeds/metric_catalog.csv (so dbt can test that every KPI is catalogued)
and docs/METRIC_CATALOG.md. tests/test_metric_catalog.py fails if either is stale.
"""
import csv
import io

import yaml

from finance_os.paths import DOCS, ROOT, SEEDS, WAREHOUSE

SOURCE = WAREHOUSE / "metrics" / "kpis.yml"
SEED = SEEDS / "metric_catalog.csv"
DOC = DOCS / "METRIC_CATALOG.md"
FIELDS = ["name", "label", "unit", "purpose", "formula", "grain", "source_model", "owner", "status", "tolerance"]


def load():
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["metrics"]


def render_seed(metrics):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["metric_name"] + FIELDS[1:], lineterminator="\n")
    w.writeheader()
    for m in metrics:
        w.writerow({"metric_name": m["name"], **{f: m[f] for f in FIELDS[1:]}})
    return buf.getvalue()


def render_doc(metrics):
    out = ["# Metric catalog", "",
           "Generated from `warehouse/metrics/kpis.yml` by `finance_os.reports.build_metric_catalog`. Do not edit by hand.", ""]
    for m in metrics:
        out += [f"## {m['label']} (`{m['name']}`)", "",
                f"- **Decision it supports:** {m['purpose']}",
                f"- **Formula:** {m['formula']}",
                f"- **Unit / grain:** {m['unit']} / {m['grain']}",
                f"- **Source model:** `{m['source_model']}`",
                f"- **Owner:** {m['owner']}",
                f"- **Status:** {m['status']}",
                f"- **Tolerance / caveats:** {m['tolerance']}", ""]
    return "\n".join(out)


def main():
    metrics = load()
    SEED.write_text(render_seed(metrics), encoding="utf-8", newline="\n")
    DOC.write_text(render_doc(metrics), encoding="utf-8", newline="\n")
    print(f"{len(metrics)} metrics -> {SEED.relative_to(ROOT)}, {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
