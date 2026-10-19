"""Prove the DuckDB and BigQuery builds of the same company agree: every model, row counts and the total of
every numeric column. Books of record (ledger, AR/AP, projects, revenue, recons) must match exactly.
Forecast models compound growth with pow() in floating point, so each row may round to a different cent:
their totals may differ by at most one cent per row. Floating-point ratio columns compare to 1e-6 relative.

    python -m finance_os.warehouse_parity [--prefix s_] [--project finance-os-sivaram]

Run after `dbt build` on both targets from the same raw data (duckdb_to_bigquery copies it).
"""
import argparse
import sys
from decimal import Decimal

import duckdb
from google.cloud import bigquery

from finance_os.paths import ROOT

SCHEMAS = ("staging", "intermediate", "marts", "recon")
# outputs of floating-point growth math: allowed one cent (or 1e-6 for 6-place rates) of rounding per row
MODELED = {"fct_forecast_monthly", "fct_forecast_accuracy", "fct_scenario_summary", "fct_budget_build",
           "fct_treasury_covenants", "fct_unit_economics_monthly", "fct_fundraise_scenarios", "fct_long_range_plan"}
NUMERIC = {"DECIMAL", "INTEGER", "BIGINT", "HUGEINT", "DOUBLE", "FLOAT", "SMALLINT", "TINYINT", "UBIGINT"}


def _num_cols(con, schema, table):
    rows = con.execute("select column_name, data_type from information_schema.columns "
                       "where table_schema = ? and table_name = ? order by ordinal_position", [schema, table]).fetchall()
    return [(c, t) for c, t in rows if t.split("(")[0].upper() in NUMERIC]


def _close(a, b, is_float, rows=0, modeled=False):
    if a is None or b is None:
        return a is None and b is None
    a, b = Decimal(str(a)), Decimal(str(b))
    if is_float:
        return abs(a - b) <= max(abs(a), abs(b), Decimal(1)) * Decimal("1e-6")
    if modeled:
        return abs(a - b) <= Decimal("0.01") * max(rows, 1)
    return abs(a - b) <= Decimal("0.000001")


def compare(prefix, project, log=print):
    con = duckdb.connect(str(ROOT / "data" / "finance_os.duckdb"), read_only=True)
    bq = bigquery.Client(project=project, location="US")
    tables = con.execute(f"select table_schema, table_name from information_schema.tables "
                         f"where table_schema in {SCHEMAS} order by 1, 2").fetchall()
    bad, checked, scanned = [], 0, 0
    for schema, table in tables:
        cols = _num_cols(con, schema, table)
        exprs = ["count(*)"] + [f"sum(cast({c} as double))" if t.upper().startswith(("DOUBLE", "FLOAT")) else f"sum({c})"
                                for c, t in cols]
        try:
            local = con.execute(f"select {', '.join(exprs)} from {schema}.{table}").fetchone()
        except duckdb.Error:
            log(f"skip {schema}.{table}: left over in DuckDB from an old model")
            continue
        bq_exprs = ["count(*)"] + [f"sum(cast(`{c}` as float64))" if t.upper().startswith(("DOUBLE", "FLOAT"))
                                   else f"sum(cast(`{c}` as bignumeric))" for c, t in cols]
        job = bq.query(f"select {', '.join(bq_exprs)} from `{project}.{prefix}{schema}.{table}`")
        remote = list(job.result())[0]
        scanned += job.total_bytes_processed or 0
        checked += 1
        diffs = []
        if local[0] != remote[0]:
            diffs.append(f"rows {local[0]} vs {remote[0]}")
        for i, (c, t) in enumerate(cols, 1):
            if not _close(local[i], remote[i], t.upper().startswith(("DOUBLE", "FLOAT")), local[0], table in MODELED):
                diffs.append(f"{c}: {local[i]} vs {remote[i]}")
        if diffs:
            bad.append((f"{schema}.{table}", diffs))
            log(f"DIFF {schema}.{table}: " + "; ".join(diffs[:4]))
    log(f"{checked} models compared, {len(bad)} differ; BigQuery scanned {scanned / 1e6:.1f} MB")
    return bad


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prefix", default="s_")
    p.add_argument("--project", default="finance-os-sivaram")
    a = p.parse_args()
    sys.exit(1 if compare(a.prefix, a.project) else 0)


if __name__ == "__main__":
    main()
