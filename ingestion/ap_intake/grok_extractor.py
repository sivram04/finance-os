"""Extraction with xAI Grok (structured JSON output). Needs XAI_API_KEY (environment or .env).

The model gets the PDF's text and returns the printed fields as strings in a fixed JSON schema. It is told
to copy numbers exactly as printed and never to add, total or correct them (design AIR-1: AI never produces
a money figure). Arithmetic and matching happen in the warehouse, which flags anything that doesn't tie.
Model and endpoint are configurable: XAI_MODEL (default grok-4), XAI_BASE_URL.
"""
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["vendor_name", "vendor_invoice_number", "invoice_date", "po_number", "currency", "total", "lines"],
    "properties": {
        "vendor_name": {"type": ["string", "null"]},
        "vendor_invoice_number": {"type": ["string", "null"]},
        "invoice_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "po_number": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"]},
        "total": {"type": ["string", "null"], "description": "Total exactly as printed, digits only, no commas"},
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["description", "quantity", "amount"],
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["string", "null"]},
                    "amount": {"type": ["string", "null"]},
                },
            },
        },
    },
}

PROMPT = (
    "You extract fields from a vendor bill sent to Echo Labs. Return JSON matching the schema. "
    "Copy every value exactly as printed. For numbers, remove thousands separators but do not round, add, "
    "total, or correct anything; if the printed total disagrees with the lines, return what is printed. "
    "Use null for a field that is not on the document. The PO number is whatever the vendor printed as the "
    "purchase order reference, under any label."
)


def _dec(s):
    if s in (None, ""):
        return None
    try:
        return Decimal(str(s).replace(",", ""))
    except InvalidOperation:
        return None


def extract(path):
    key = os.environ.get("XAI_API_KEY")
    if not key:
        raise RuntimeError("XAI_API_KEY is not set (environment or .env)")
    model = os.environ.get("XAI_MODEL", "grok-4")
    base = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1")
    text = "\n".join(page.extract_text() for page in PdfReader(path).pages)
    body = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "vendor_bill", "schema": SCHEMA, "strict": True}},
    }
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read())
    data = json.loads(payload["choices"][0]["message"]["content"])
    usage = payload.get("usage", {})
    return {
        "vendor_name": data["vendor_name"],
        "vendor_invoice_number": data["vendor_invoice_number"],
        "invoice_date": data["invoice_date"],
        "po_number": data["po_number"],
        "currency": data["currency"],
        "total": _dec(data["total"]),
        "lines": [{"line_no": n, "description": l["description"], "quantity": _dec(l["quantity"]),
                   "amount": _dec(l["amount"])} for n, l in enumerate(data["lines"], 1)],
        "model": payload.get("model", model),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }
