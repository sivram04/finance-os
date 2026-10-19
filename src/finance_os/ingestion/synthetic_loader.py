"""Load generator CSVs into DuckDB raw schemas (raw_synth, raw_infra, raw_erp, raw_payroll, raw_projects) with explicit types (money as DECIMAL, NFR-1).

    python -m finance_os.ingestion.synthetic_loader [--src data/synthetic] [--db data/finance_os.duckdb]

Full replace each run, so it is safe to rerun (NFR-3).
"""
import argparse
from pathlib import Path

import duckdb

# (schema, table) -> column types
SCHEMAS = {
    ("raw_synth", "products"): {"product_id": "VARCHAR", "model": "VARCHAR", "workload": "VARCHAR",
                 "list_price_per_hour": "DECIMAL(18,4)"},
    ("raw_synth", "volume_tiers"): {"tier": "INTEGER", "min_hours_month": "INTEGER", "discount_pct": "DECIMAL(5,4)"},
    ("raw_synth", "customers"): {"customer_id": "VARCHAR", "customer_name": "VARCHAR", "segment": "VARCHAR",
                  "signup_date": "DATE", "start_hours_month": "INTEGER", "monthly_growth": "DECIMAL(6,4)"},
    ("raw_synth", "customer_product_mix"): {"customer_id": "VARCHAR", "product_id": "VARCHAR", "share": "DECIMAL(5,4)"},
    ("raw_synth", "usage_daily"): {"usage_date": "DATE", "customer_id": "VARCHAR", "product_id": "VARCHAR",
                    "audio_hours": "DECIMAL(18,4)", "requests": "INTEGER"},
    ("raw_synth", "lifecycle_events"): {"event_id": "VARCHAR", "customer_id": "VARCHAR", "event_date": "DATE",
                                        "event_type": "VARCHAR", "multiplier": "DECIMAL(9,4)", "reason": "VARCHAR",
                                        "source": "VARCHAR"},
    ("raw_synth", "ap_document_truth"): {"doc_file": "VARCHAR", "erp_bill_id": "VARCHAR", "vendor_id": "VARCHAR",
                                         "vendor_name": "VARCHAR", "vendor_invoice_number": "VARCHAR",
                                         "invoice_date": "DATE", "po_number": "VARCHAR", "total": "DECIMAL(18,2)",
                                         "doc_issue": "VARCHAR"},
    ("raw_synth", "ap_document_truth_lines"): {"doc_file": "VARCHAR", "line_no": "INTEGER", "description": "VARCHAR",
                                               "quantity": "DECIMAL(18,4)", "amount": "DECIMAL(18,2)"},
    ("raw_synth", "anomaly_manifest"): {"anomaly_id": "VARCHAR", "module": "VARCHAR", "kind": "VARCHAR",
                                        "entity_id": "VARCHAR", "start_date": "DATE", "description": "VARCHAR",
                                        "expected_detection": "VARCHAR"},
    ("raw_infra", "gpu_jobs"): {"job_id": "VARCHAR", "job_date": "DATE", "customer_id": "VARCHAR",
                                "product_id": "VARCHAR", "model": "VARCHAR", "workload": "VARCHAR",
                                "gpu_type": "VARCHAR", "gpu_seconds": "BIGINT", "region": "VARCHAR",
                                "label_team": "VARCHAR", "label_env": "VARCHAR"},
    ("raw_infra", "cloud_costs_daily"): {"usage_date": "DATE", "service": "VARCHAR", "sku": "VARCHAR",
                                         "label_team": "VARCHAR", "label_env": "VARCHAR",
                                         "cost": "DECIMAL(18,6)"},
    ("raw_netsuite", "transaction"): {"id": "BIGINT", "tranid": "VARCHAR", "type": "VARCHAR", "trandate": "DATE",
                                      "postingperiod": "INTEGER", "memo": "VARCHAR", "entity": "BIGINT",
                                      "currency": "INTEGER", "exchangerate": "DECIMAL(18,6)", "posting": "VARCHAR",
                                      "status": "VARCHAR", "custbody_echo_entry_type": "VARCHAR",
                                      "custbody_echo_source_ref": "VARCHAR", "createddate": "TIMESTAMP",
                                      "lastmodifieddate": "TIMESTAMP"},
    ("raw_netsuite", "transactionline"): {"transaction": "BIGINT", "id": "INTEGER", "account": "INTEGER",
                                          "department": "INTEGER", "entity": "BIGINT", "subsidiary": "INTEGER",
                                          "location": "INTEGER", "memo": "VARCHAR", "debit": "DECIMAL(18,2)",
                                          "credit": "DECIMAL(18,2)", "posting": "VARCHAR"},
    ("raw_netsuite", "account"): {"id": "INTEGER", "acctnumber": "VARCHAR", "fullname": "VARCHAR", "accttype": "VARCHAR",
                                  "isinactive": "VARCHAR"},
    ("raw_netsuite", "department"): {"id": "INTEGER", "name": "VARCHAR", "externalid": "VARCHAR", "isinactive": "VARCHAR"},
    ("raw_netsuite", "entity"): {"id": "BIGINT", "entityid": "VARCHAR", "type": "VARCHAR", "isinactive": "VARCHAR"},
    ("raw_netsuite", "accountingperiod"): {"id": "INTEGER", "periodname": "VARCHAR", "startdate": "DATE", "enddate": "DATE",
                                           "isquarter": "VARCHAR", "isyear": "VARCHAR", "isadjust": "VARCHAR"},
    ("raw_erp", "journal_entries"): {"entry_id": "VARCHAR", "entry_date": "DATE", "entry_type": "VARCHAR",
                                     "memo": "VARCHAR", "source_ref": "VARCHAR"},
    ("raw_erp", "journal_lines"): {"entry_id": "VARCHAR", "line_no": "INTEGER", "account_id": "VARCHAR",
                                   "department_id": "VARCHAR", "customer_id": "VARCHAR", "vendor_id": "VARCHAR",
                                   "debit": "DECIMAL(18,2)", "credit": "DECIMAL(18,2)"},
    ("raw_erp", "customer_payments"): {"payment_id": "VARCHAR", "customer_id": "VARCHAR", "received_date": "DATE",
                                       "amount": "DECIMAL(18,2)", "remittance_ref": "VARCHAR", "applied_ref": "VARCHAR"},
    ("raw_erp", "disputes"): {"dispute_id": "VARCHAR", "customer_id": "VARCHAR", "invoice_ref": "VARCHAR",
                              "project_id": "VARCHAR", "opened_date": "DATE", "amount": "DECIMAL(18,2)",
                              "status": "VARCHAR", "root_cause": "VARCHAR", "resolved_date": "DATE", "note": "VARCHAR"},
    ("raw_erp", "budgets"): {"fiscal_year": "INTEGER", "month": "DATE", "department_id": "VARCHAR",
                             "account_id": "VARCHAR", "version": "VARCHAR", "amount": "DECIMAL(18,2)"},
    ("raw_projects", "contracts"): {"contract_id": "VARCHAR", "customer_id": "VARCHAR", "contract_type": "VARCHAR",
                                    "start_date": "DATE", "end_date": "DATE", "contract_value": "DECIMAL(18,2)",
                                    "ceiling": "DECIMAL(18,2)", "funded_amount": "DECIMAL(18,2)",
                                    "payment_terms_days": "INTEGER", "is_federal": "BOOLEAN"},
    ("raw_projects", "clins"): {"contract_id": "VARCHAR", "clin_id": "VARCHAR", "description": "VARCHAR",
                                "ceiling": "DECIMAL(18,2)", "funded": "DECIMAL(18,2)"},
    ("raw_projects", "contract_rates"): {"contract_id": "VARCHAR", "labor_category": "VARCHAR", "bill_rate": "DECIMAL(18,2)"},
    ("raw_projects", "projects"): {"project_id": "VARCHAR", "contract_id": "VARCHAR", "customer_id": "VARCHAR",
                                   "project_name": "VARCHAR", "project_type": "VARCHAR", "start_date": "DATE",
                                   "planned_end_date": "DATE"},
    ("raw_projects", "project_budgets"): {"project_id": "VARCHAR", "cost_type": "VARCHAR", "budget_amount": "DECIMAL(18,2)"},
    ("raw_projects", "timesheets"): {"timesheet_id": "VARCHAR", "employee_id": "VARCHAR", "project_id": "VARCHAR",
                                     "week_ending": "DATE", "labor_category": "VARCHAR", "hours": "DECIMAL(9,2)",
                                     "approved": "BOOLEAN"},
    ("raw_projects", "odc_expenses"): {"expense_id": "VARCHAR", "project_id": "VARCHAR", "expense_date": "DATE",
                                       "amount": "DECIMAL(18,2)", "description": "VARCHAR"},
    ("raw_projects", "purchase_orders"): {"po_id": "VARCHAR", "project_id": "VARCHAR", "vendor_id": "VARCHAR",
                                          "po_date": "DATE", "amount": "DECIMAL(18,2)", "description": "VARCHAR"},
    ("raw_projects", "subcontractor_bills"): {"bill_id": "VARCHAR", "project_id": "VARCHAR", "vendor_id": "VARCHAR",
                                              "po_id": "VARCHAR", "bill_date": "DATE", "amount": "DECIMAL(18,2)",
                                              "description": "VARCHAR", "vendor_invoice_number": "VARCHAR"},
    ("raw_projects", "milestones"): {"milestone_id": "VARCHAR", "project_id": "VARCHAR", "milestone_name": "VARCHAR",
                                     "amount": "DECIMAL(18,2)", "accepted_date": "DATE"},
    ("raw_projects", "project_invoices"): {"invoice_id": "VARCHAR", "project_id": "VARCHAR", "contract_id": "VARCHAR",
                                           "customer_id": "VARCHAR", "invoice_date": "DATE", "service_month": "DATE",
                                           "amount": "DECIMAL(18,2)"},
    ("raw_projects", "project_invoice_lines"): {"invoice_id": "VARCHAR", "line_no": "INTEGER", "line_type": "VARCHAR",
                                                "clin_id": "VARCHAR", "labor_category": "VARCHAR", "milestone_id": "VARCHAR",
                                                "hours": "DECIMAL(9,2)", "rate": "DECIMAL(18,2)", "amount": "DECIMAL(18,2)"},
    ("raw_projects", "pm_estimates"): {"project_id": "VARCHAR", "as_of_month": "DATE", "etc_amount": "DECIMAL(18,2)"},
    ("raw_projects", "subcontractors"): {"vendor_id": "VARCHAR", "vendor_name": "VARCHAR"},
    ("raw_payroll", "employees"): {"employee_id": "VARCHAR", "employee_name": "VARCHAR", "department_id": "VARCHAR",
                                   "function": "VARCHAR", "title": "VARCHAR", "hire_date": "DATE",
                                   "termination_date": "DATE", "annual_salary": "DECIMAL(18,2)"},
    ("raw_payroll", "pay_runs"): {"pay_run_id": "VARCHAR", "period_start": "DATE", "period_end": "DATE",
                                  "pay_date": "DATE"},
    ("raw_payroll", "pay_lines"): {"pay_run_id": "VARCHAR", "employee_id": "VARCHAR", "department_id": "VARCHAR",
                                   "gross_pay": "DECIMAL(18,2)", "employer_tax": "DECIMAL(18,2)",
                                   "benefits": "DECIMAL(18,2)"},
    ("raw_payroll", "pay_register_lines"): {"pay_run_id": "VARCHAR", "employee_id": "VARCHAR", "department_id": "VARCHAR",
                                            "line_no": "INTEGER", "line_type": "VARCHAR", "code": "VARCHAR",
                                            "amount": "DECIMAL(18,2)"},
    ("raw_erp", "vendor_bills"): {"bill_id": "VARCHAR", "vendor_id": "VARCHAR", "service_month": "DATE",
                                  "bill_date": "DATE", "total_amount": "DECIMAL(18,2)",
                                  "vendor_invoice_number": "VARCHAR"},
    ("raw_erp", "vendor_bill_lines"): {"bill_id": "VARCHAR", "line_type": "VARCHAR", "gpu_type": "VARCHAR",
                                       "quantity_hours": "DECIMAL(18,4)", "amount": "DECIMAL(18,2)"},
}


def load(src: Path, db: Path):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    con.execute("DROP TABLE IF EXISTS raw_erp.opex_pools_monthly")  # replaced by payroll (step 4)
    for (schema, table), cols in SCHEMAS.items():
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        path = (src / (f"netsuite_{table}.csv" if schema == "raw_netsuite" else f"{table}.csv")).as_posix()
        types = ", ".join(f"'{c}': '{t}'" for c, t in cols.items())
        con.execute(
            f"CREATE OR REPLACE TABLE {schema}.{table} AS "
            f"SELECT *, current_timestamp AS _loaded_at "
            f"FROM read_csv('{path}', header=true, columns={{{types}}})"
        )
        n = con.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
        print(f"{schema}.{table}: {n} rows")
    load_stripe(con, src)
    load_gcp(con, src)
    con.close()


def load_gcp(con, src: Path):
    """Google's billing export lands as Google writes it: nested structs and repeated key/value labels."""
    path = src / "gcp" / "gcp_billing_export_v1.jsonl"
    if not path.exists():
        return
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_gcp")
    con.execute(f"CREATE OR REPLACE TABLE raw_gcp.gcp_billing_export_v1 AS SELECT *, current_timestamp AS _loaded_at "
                f"FROM read_json('{path.as_posix()}', format='newline_delimited', columns={GCP_EXPORT_COLUMNS})")
    print(f"raw_gcp.gcp_billing_export_v1: {con.execute('SELECT count(*) FROM raw_gcp.gcp_billing_export_v1').fetchone()[0]} rows")


KV = "STRUCT(key VARCHAR, value VARCHAR)[]"
GCP_EXPORT_COLUMNS = "{" + ", ".join(f"'{c}': '{t}'" for c, t in {
    "billing_account_id": "VARCHAR",
    "service": "STRUCT(id VARCHAR, description VARCHAR)",
    "sku": "STRUCT(id VARCHAR, description VARCHAR)",
    "usage_start_time": "TIMESTAMP", "usage_end_time": "TIMESTAMP",
    "project": f"STRUCT(id VARCHAR, number VARCHAR, name VARCHAR, labels {KV}, ancestry_numbers VARCHAR)",
    "labels": KV, "system_labels": KV,
    "location": "STRUCT(location VARCHAR, country VARCHAR, region VARCHAR, zone VARCHAR)",
    "export_time": "TIMESTAMP", "cost": "DOUBLE", "currency": "VARCHAR", "currency_conversion_rate": "DOUBLE",
    "usage": "STRUCT(amount DOUBLE, unit VARCHAR, amount_in_pricing_units DOUBLE, pricing_unit VARCHAR)",
    "credits": "STRUCT(name VARCHAR, amount DOUBLE, full_name VARCHAR, id VARCHAR, type VARCHAR)[]",
    "invoice": "STRUCT(month VARCHAR, publisher_type VARCHAR)",
    "cost_type": "VARCHAR", "transaction_type": "VARCHAR", "seller_name": "VARCHAR"}.items()) + "}"


STRIPE_OBJECTS = ["customers", "invoices", "charges", "refunds", "balance_transactions", "payouts"]


def load_stripe(con, src: Path):
    """Stripe objects land as one row per object with the raw JSON, like an ELT tool's raw table."""
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_stripe")
    for obj in STRIPE_OBJECTS:
        path = src / "stripe" / f"{obj}.jsonl"
        if not path.exists():
            continue
        con.execute(f"CREATE OR REPLACE TABLE raw_stripe.{obj} AS SELECT id, data, current_timestamp AS _loaded_at "
                    f"FROM read_json('{path.as_posix()}', columns={{'id': 'VARCHAR', 'data': 'JSON'}}, format='newline_delimited')")
        n = con.execute(f"SELECT count(*) FROM raw_stripe.{obj}").fetchone()[0]
        print(f"raw_stripe.{obj}: {n} rows")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src", default="data/synthetic")
    p.add_argument("--db", default="data/finance_os.duckdb")
    a = p.parse_args()
    load(Path(a.src), Path(a.db))


if __name__ == "__main__":
    main()
