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
FIELDS = ["name", "label", "unit", "purpose", "formula", "grain", "source_model", "owner", "status", "tolerance",
          "numerator", "denominator", "inclusions", "exclusions", "currency_treatment", "period_logic", "refresh",
          "version", "effective_from", "restatement_policy", "threshold_rule", "decision_amber", "decision_red", "recon_checks"]
CHANGELOG = SEEDS / "metric_changelog.csv"


def load():
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8"))["metrics"]


def load_changelog():
    return yaml.safe_load(SOURCE.read_text(encoding="utf-8")).get("changelog") or []


def threshold_rule(m):
    t = m.get("threshold") or {}
    basis = {"value": "value", "mom": "month-over-month change", "vs_budget": "variance vs budget", "vs_plan": "variance vs plan",
             "vs_run_rate": "vs run-rate ARR"}.get(t.get("basis"), t.get("basis"))
    return f"{basis}; {t.get('better')} is better; amber at {t.get('amber')}, red at {t.get('red')}"


def _row(m):
    return {**m, "threshold_rule": threshold_rule(m), "recon_checks": ", ".join(m.get("recon_checks") or [])}


def render_seed(metrics):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["metric_name"] + FIELDS[1:], lineterminator="\n")
    w.writeheader()
    for m in metrics:
        r = _row(m)
        w.writerow({"metric_name": m["name"], **{f: r[f] for f in FIELDS[1:]}})
    return buf.getvalue()


def render_doc(metrics):
    out = ["# Metric catalog", "",
           "Generated from `warehouse/metrics/kpis.yml` by `finance_os.reports.build_metric_catalog`. Do not edit by hand.", ""]
    for m in metrics:
        out += [f"## {m['label']} (`{m['name']}`)", "",
                f"- **Decision it supports:** {m['purpose']}",
                f"- **Formula:** {m['formula']}",
                f"- **Numerator / denominator:** {m['numerator']} / {m['denominator']}",
                f"- **Includes / excludes:** {m['inclusions']} / {m['exclusions']}",
                f"- **Currency:** {m['currency_treatment']}",
                f"- **Period:** {m['period_logic']} Refresh: {m['refresh']}",
                f"- **Version:** {m['version']}, effective {m['effective_from']}. Restatement: {m['restatement_policy']}",
                f"- **Unit / grain:** {m['unit']} / {m['grain']}",
                f"- **Source model:** `{m['source_model']}`",
                f"- **Owner:** {m['owner']}",
                f"- **Status:** {m['status']}",
                f"- **Tolerance / caveats:** {m['tolerance']}",
                f"- **Threshold:** {threshold_rule(m)}",
                f"- **Decision at amber:** {m.get('decision_amber')}",
                f"- **Decision at red:** {m.get('decision_red')}",
                f"- **Proved by reconciliation checks:** {', '.join(m.get('recon_checks') or []) or 'none (derived metric)'}", ""]
    return "\n".join(out)


def main():
    metrics = load()
    SEED.write_text(render_seed(metrics), encoding="utf-8", newline="\n")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["metric_name", "version", "effective_from", "change", "approved_by"], lineterminator="\n")
    w.writeheader()
    for c in load_changelog():
        w.writerow({"metric_name": c["metric"], **{k: c[k] for k in ("version", "effective_from", "change", "approved_by")}})
    CHANGELOG.write_text(buf.getvalue(), encoding="utf-8", newline="\n")
    DOC.write_text(render_doc(metrics), encoding="utf-8", newline="\n")
    print(f"{len(metrics)} metrics -> {SEED.relative_to(ROOT)}, {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
