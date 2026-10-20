"""Generate Echo Labs synthetic data as CSVs.

    python -m finance_os.generator [--out data/synthetic] [--seed N]

Same seed → byte-identical output (NFR-2).
"""
import argparse
from datetime import date
import csv
import json
import random
from pathlib import Path

from decimal import Decimal

import yaml

from finance_os.generator.anomalies import build_manifest
from finance_os.generator.documents.ap_bills import assign_vendor_invoice_numbers, build_ap_truth, render_ap_pdfs
from finance_os.generator.entities.catalog import build_products, build_volume_tiers
from finance_os.generator.erp.netsuite import build_netsuite
from finance_os.generator.seeds import read_seed
from finance_os.generator.entities.customers import build_customers
from finance_os.generator.entities.employees import build_employees
from finance_os.generator.entities.lifecycle import build_lifecycle
from finance_os.generator.events.budget import build_budgets
from finance_os.generator.events.gcp_billing_export import build_gcp_export, gcp_bill_lines
from finance_os.generator.events.infra import build_cloud_costs, build_gpu_jobs
from finance_os.generator.events.ledger import build_ledger
from finance_os.generator.events.payroll import build_payroll
from finance_os.generator.events.pipeline import build_pipeline
from finance_os.generator.events.projects import build_projects
from finance_os.generator.events.stripe import build_stripe
from finance_os.generator.events.contracts import build_contracts
from finance_os.generator.events.usage import build_usage
from finance_os.generator.events.vendor_bills import build_vendor_bills

from finance_os.paths import ROOT  # noqa: E402

CONFIG = Path(__file__).with_name("config.yaml")


def load_config(scale="S"):
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    for segment, count in cfg["scales"][scale].items():
        cfg["segments"][segment]["count"] = count
    people = cfg["people_scale"][scale]
    for plan in cfg["headcount_plan"]:
        plan["start"], plan["end"] = plan["start"] * people, plan["end"] * people
    cfg["terminations"] *= people
    for o in cfg["opex_monthly"]:
        o["amount"] = str(Decimal(o["amount"]) * people)
    for f in cfg["funding"]:  # a company 10x the size raised 10x the capital
        f["amount"] = str(Decimal(f["amount"]) * people)
    cfg["scale"] = scale
    return cfg


def generate(seed=None, scale="S"):
    cfg = load_config(scale)
    rng = random.Random(seed if seed is not None else cfg["seed"])
    customers, mixes = build_customers(cfg, rng)
    lifecycle = build_lifecycle(cfg, customers, mixes, rng)
    usage = build_usage(cfg, customers, mixes, lifecycle, rng)
    gpu_jobs = build_gpu_jobs(cfg, usage, rng)
    cloud_costs = build_cloud_costs(cfg, usage)
    bills, bill_lines = build_vendor_bills(cfg, gpu_jobs, cloud_costs, rng)
    employees = build_employees(cfg, rng)
    pay_runs, pay_lines, pay_register = build_payroll(cfg, employees)
    projects = build_projects(cfg, employees, rng)
    assign_vendor_invoice_numbers(cfg, bills, projects["subcontractor_bills"])
    ap_docs, ap_doc_lines = build_ap_truth(cfg, bills, bill_lines, projects["subcontractor_bills"])
    entries, lines, payments, disputes, billing = build_ledger(cfg, customers, usage, lifecycle, cloud_costs, bills, bill_lines, pay_register, employees,
                                  projects, rng)
    # the ERP's view of the ledger: a NetSuite data export (raw_netsuite), read by the warehouse's ERP staging
    vendor_codes = {l["vendor_id"] for l in lines if l["vendor_id"]} | set(cfg["ap_documents"]["layouts"])
    customer_codes = {c["customer_id"] for c in customers} | {l["customer_id"] for l in lines if l["customer_id"]}
    netsuite = build_netsuite(read_seed("gl_accounts"), read_seed("departments"), customer_codes, vendor_codes,
                              entries, lines, cfg["window"]["start"], date(cfg["window"]["end"].year + 1, 12, 31))
    opportunities = build_pipeline(cfg, customers)
    contracts, contract_schedule = build_contracts(cfg, customers, opportunities, lifecycle,
                                                    {(b["customer_id"], (b["month"].year, b["month"].month)): b["amount"] for b in billing})
    return {
        **netsuite,
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
        "gcp_billing_export_v1": build_gcp_export(gcp_bill_lines(bills, bill_lines), cloud_costs, gpu_jobs),
        "employees": employees,
        "pay_runs": pay_runs,
        "pay_lines": pay_lines,
        "pay_register_lines": pay_register,
        "journal_entries": entries,
        "journal_lines": lines,
        **build_stripe(cfg, customers, billing),
        "customer_payments": payments,
        "disputes": disputes,
        "budgets": build_budgets(cfg, entries, lines),
        **projects,
        "anomaly_manifest": build_manifest(cfg),
        "opportunities": opportunities,
        "customer_contracts": contracts,  # not "contracts": that name is the project contracts
        "customer_contract_schedule": contract_schedule,
        "ap_document_truth": ap_docs,
        "ap_document_truth_lines": ap_doc_lines,
    }


def write_csvs(tables, out_dir: Path):
    """Flat tables as CSV; nested sources as JSON lines: Stripe objects in out_dir/stripe/, the GCP billing
    export in out_dir/gcp/."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in tables.items():
        if name.startswith("stripe_"):
            (out_dir / "stripe").mkdir(exist_ok=True)
            with open(out_dir / "stripe" / f"{name[7:]}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for obj in rows:
                    f.write(json.dumps({"id": obj["id"], "data": obj}, separators=(",", ":")) + "\n")
            continue
        if name.startswith("gcp_"):
            (out_dir / "gcp").mkdir(exist_ok=True)
            with open(out_dir / "gcp" / f"{name}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, separators=(",", ":")) + "\n")
            continue
        with open(out_dir / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/synthetic")
    p.add_argument("--seed", type=int)
    p.add_argument("--scale", choices=["S", "M", "L"], default="S",
                   help="S: local/tests (default); M, L: larger companies for the BigQuery build")
    p.add_argument("--inbox", default="data/inbox/ap", help="where vendor bill PDFs are written")
    a = p.parse_args()
    tables = generate(a.seed, a.scale)
    write_csvs(tables, Path(a.out))
    cfg = load_config(a.scale)
    live_docs = ROOT / "data" / "live" / "ap_documents.jsonl"  # bills the live company received: never delete them
    keep = {json.loads(l)["doc_file"] for l in live_docs.read_text(encoding="utf-8").splitlines() if l.strip()} if live_docs.exists() else set()
    render_ap_pdfs(cfg, tables["ap_document_truth"], tables["ap_document_truth_lines"], Path(a.inbox), keep=keep)
    print(f"vendor bill PDFs: {len(tables['ap_document_truth'])} -> {a.inbox}")
    for name, rows in tables.items():
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
