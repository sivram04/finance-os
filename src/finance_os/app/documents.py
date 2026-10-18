"""Documents dropped into the chat (design §9.5): vendor bills as PDF, scanned PDF, or image.

How a file is read:
- PDF with a text layer → layout text → OpenAI with the strict bill schema (or the rules extractor when no
  OpenAI key is set).
- Scanned PDF (no usable text) → the page images embedded in it → OpenAI vision (OCR).
- PNG / JPEG / WEBP photo or scan → OpenAI vision (OCR).
The model only reads; these controls (the same rules as fct_ap_documents) decide whether the bill can be
approved: known vendor, total = sum of lines, not already received or posted, PO exists, belongs to the vendor
and has enough open balance. Uploads are app state (data/app.duckdb), so warehouse rebuilds never lose them.
"""
import json
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from finance_os.app.state import AppState, now
from finance_os.app.tools import Warehouse
from finance_os.ingestion.ap_intake import openai_extractor, text_extractor
from finance_os.paths import ROOT

UPLOADS = ROOT / "data" / "inbox" / "uploads"
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
MAX_BYTES = 15 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploaded_documents (
    id VARCHAR PRIMARY KEY, filename VARCHAR, path VARCHAR, method VARCHAR, model VARCHAR,
    fields JSON, issues JSON, vendor_id VARCHAR, created_at TIMESTAMP);
"""


def _safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)[:120] or "upload"


def _read(path: Path):
    """Return (extraction, method)."""
    use_ai = bool(os.environ.get("OPENAI_API_KEY"))
    suffix = path.suffix.lower()
    if suffix in IMAGE_TYPES:
        if not use_ai:
            raise RuntimeError("Reading images (OCR) needs OPENAI_API_KEY in .env.")
        return openai_extractor.extract_images([(path.read_bytes(), IMAGE_TYPES[suffix])]), "ocr_image"
    if suffix != ".pdf":
        raise ValueError("Upload a PDF, PNG, JPEG or WEBP vendor bill.")
    text = openai_extractor.pdf_text(path)
    if len(re.sub(r"\s+", "", text)) >= 40:
        return (openai_extractor.extract(path), "pdf_text") if use_ai else (text_extractor.extract(path), "pdf_rules")
    if not use_ai:
        raise RuntimeError("This PDF has no text layer (a scan); reading it (OCR) needs OPENAI_API_KEY in .env.")
    images = []
    for page in PdfReader(path).pages:
        for img in page.images:
            mime = "image/png" if img.name.lower().endswith(".png") else "image/jpeg"
            images.append((img.data, mime))
    if not images:
        raise ValueError("This PDF has neither text nor page images to read.")
    return openai_extractor.extract_images(images[:6]), "ocr_scanned_pdf"


def check(wh: Warehouse, state: AppState, doc_id, f):
    """Controls on an extracted bill. Returns (vendor_id, [issue codes with details])."""
    issues = []
    # vendors vary case and punctuation ("ANNOTATE CO." vs "Annotate Co"), so compare normalized names
    alias = wh.query("""select vendor_id from seeds.ap_vendor_aliases
                        where trim(regexp_replace(lower(printed_name), '[^a-z0-9]+', ' ', 'g'))
                            = trim(regexp_replace(lower(?), '[^a-z0-9]+', ' ', 'g'))""", [f.get("vendor_name") or ""])
    vendor_id = alias[0]["vendor_id"] if alias else None
    if not vendor_id:
        issues.append({"code": "unknown_vendor", "detail": f"Vendor \"{f.get('vendor_name')}\" is not a known vendor"})
    lines_total = sum((Decimal(str(l["amount"])) for l in f["lines"] if l.get("amount") is not None), Decimal(0))
    total = Decimal(str(f["total"])) if f.get("total") is not None else None
    if total is None or total != lines_total:
        issues.append({"code": "arithmetic_mismatch", "detail": f"Printed total {total} ≠ sum of lines {lines_total}"})
    number = f.get("vendor_invoice_number")
    if vendor_id and number:
        posted = wh.query("""select bill_id from staging.stg_erp__vendor_bills where vendor_id = ? and vendor_invoice_number = ?
                             union all
                             select bill_id from staging.stg_projects__subcontractor_bills
                             where vendor_id = ? and vendor_invoice_number = ?""", [vendor_id, number, vendor_id, number])
        earlier = state._q("""select id from uploaded_documents where vendor_id = ? and json_extract_string(fields, '$.vendor_invoice_number') = ?
                              and id <> ?""", [vendor_id, number, doc_id])
        if posted or earlier:
            where = f"posted as {posted[0]['bill_id']}" if posted else f"uploaded earlier as {earlier[0]['id']}"
            issues.append({"code": "duplicate_invoice", "detail": f"Invoice {number} was already {where}"})
    po = f.get("po_number")
    is_sub = bool(vendor_id and wh.query("select 1 from staging.stg_projects__subcontractors where vendor_id = ?", [vendor_id]))
    if is_sub and not po:
        issues.append({"code": "missing_po", "detail": "Subcontractor bill with no PO"})
    if po:
        rows = wh.query("""select po.po_id, po.vendor_id, po.amount,
                                  po.amount - coalesce((select sum(amount) from staging.stg_projects__subcontractor_bills b
                                                        where b.po_id = po.po_id), 0) as open_amount
                           from staging.stg_projects__purchase_orders po where po.po_id = ?""", [po])
        if not rows:
            issues.append({"code": "po_not_found", "detail": f"PO {po} does not exist"})
        elif vendor_id and rows[0]["vendor_id"] != vendor_id:
            issues.append({"code": "po_vendor_mismatch", "detail": f"PO {po} belongs to {rows[0]['vendor_id']}"})
        elif total is not None and total > Decimal(str(rows[0]["open_amount"])):
            issues.append({"code": "po_over_remaining",
                           "detail": f"Bill {total} exceeds PO {po}'s open balance {rows[0]['open_amount']:.2f}"})
    return vendor_id, issues


def _jsonable(x):
    return json.loads(json.dumps(x, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)))


class Documents:
    def __init__(self, state: AppState, wh: Warehouse):
        self.state, self.wh = state, wh
        with state.lock:
            state.con.execute(SCHEMA)

    def upload(self, filename, data: bytes):
        if len(data) > MAX_BYTES:
            raise ValueError("File is larger than 15 MB.")
        doc_id = "UP-" + uuid.uuid4().hex[:8].upper()
        UPLOADS.mkdir(parents=True, exist_ok=True)
        path = UPLOADS / f"{doc_id}_{_safe_name(filename)}"
        path.write_bytes(data)
        extraction, method = _read(path)
        fields = _jsonable({k: v for k, v in extraction.items() if k not in ("prompt_tokens", "completion_tokens")})
        vendor_id, issues = check(self.wh, self.state, doc_id, extraction)
        self.state._q("INSERT INTO uploaded_documents VALUES (?,?,?,?,?,?,?,?,?)",
                      [doc_id, filename, str(path), method, extraction.get("model"), json.dumps(fields),
                       json.dumps(issues), vendor_id, now()])
        return self.get(doc_id)

    def get(self, doc_id):
        rows = self.state._q("SELECT * FROM uploaded_documents WHERE id = ?", [doc_id])
        if not rows:
            return None
        d = rows[0]
        fields, issues = json.loads(d["fields"]), json.loads(d["issues"])
        return {"id": d["id"], "filename": d["filename"], "method": d["method"], "model": d["model"],
                "vendor_id": d["vendor_id"], "fields": fields, "issues": issues,
                "route": "needs_review" if issues else "auto_approve", "path": d["path"],
                "source": "uploaded document (app state), checked against the warehouse"}
