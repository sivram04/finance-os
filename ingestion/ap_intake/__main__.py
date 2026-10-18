"""Read every vendor bill PDF in the AP inbox and load the extracted fields into DuckDB (raw_ap).

    python -m ingestion.ap_intake [--backend text|grok] [--inbox data/inbox/ap] [--db data/finance_os.duckdb]

Writes raw_ap.extractions (one row per document), raw_ap.extraction_lines and raw_ap.extraction_errors.
Each run replaces the rows for its backend, so it is safe to rerun. Matching, arithmetic checks and the
review queue are in the warehouse (models/marts/ap). XAI_API_KEY is read from the environment or .env.
"""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from ingestion.ap_intake import grok_extractor, text_extractor

BACKENDS = {"text": text_extractor.extract, "grok": grok_extractor.extract}


def load_dotenv(path=Path(".env")):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(backend, inbox: Path, db: Path):
    extract = BACKENDS[backend]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    docs, lines, errors = [], [], []
    for pdf in sorted(inbox.glob("*.pdf")):
        try:
            r = extract(pdf)
        except Exception as e:  # one bad document must not stop the batch; it goes to review
            errors.append((pdf.name, backend, now, f"{type(e).__name__}: {e}"))
            continue
        docs.append((pdf.name, backend, r["model"], now, r["vendor_name"], r["vendor_invoice_number"],
                     r["invoice_date"], r["po_number"], r["currency"], r["total"],
                     r.get("prompt_tokens"), r.get("completion_tokens")))
        lines += [(pdf.name, backend, l["line_no"], l["description"], l["quantity"], l["amount"]) for l in r["lines"]]

    con = duckdb.connect(str(db))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw_ap")
    con.execute("""CREATE TABLE IF NOT EXISTS raw_ap.extractions (
        doc_file VARCHAR, backend VARCHAR, model VARCHAR, extracted_at TIMESTAMP, vendor_name VARCHAR,
        vendor_invoice_number VARCHAR, invoice_date VARCHAR, po_number VARCHAR, currency VARCHAR,
        total DECIMAL(18,2), prompt_tokens INTEGER, completion_tokens INTEGER)""")
    con.execute("""CREATE TABLE IF NOT EXISTS raw_ap.extraction_lines (
        doc_file VARCHAR, backend VARCHAR, line_no INTEGER, description VARCHAR,
        quantity DECIMAL(18,4), amount DECIMAL(18,2))""")
    con.execute("""CREATE TABLE IF NOT EXISTS raw_ap.extraction_errors (
        doc_file VARCHAR, backend VARCHAR, extracted_at TIMESTAMP, error VARCHAR)""")
    for table in ("extractions", "extraction_lines", "extraction_errors"):
        con.execute(f"DELETE FROM raw_ap.{table} WHERE backend = ?", [backend])
    if docs:
        con.executemany("INSERT INTO raw_ap.extractions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", docs)
    if lines:
        con.executemany("INSERT INTO raw_ap.extraction_lines VALUES (?,?,?,?,?,?)", lines)
    if errors:
        con.executemany("INSERT INTO raw_ap.extraction_errors VALUES (?,?,?,?)", errors)
    con.close()
    print(f"{backend}: {len(docs)} documents extracted, {len(lines)} lines, {len(errors)} errors")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=sorted(BACKENDS), default="text")
    p.add_argument("--inbox", default="data/inbox/ap")
    p.add_argument("--db", default="data/finance_os.duckdb")
    a = p.parse_args()
    load_dotenv()
    if a.backend == "grok" and not os.environ.get("XAI_API_KEY"):
        raise SystemExit("XAI_API_KEY is not set. Add it to .env (never commit it) or use --backend text.")
    run(a.backend, Path(a.inbox), Path(a.db))


if __name__ == "__main__":
    main()
