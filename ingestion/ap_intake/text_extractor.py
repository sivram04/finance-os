"""Rule-based extraction from a PDF's text layer. Offline, deterministic, used in tests and CI.

Recognises the label variants vendors use ("Invoice #", "Bill No.", "Invoice No", ...). Each label is
followed by its value on the next line. Line items sit between the "Description / Quantity / Amount"
header and the total label: a text line starts an item, then one number (amount) or two (quantity, amount).
It reads what is printed and never computes money.
"""
import re
from decimal import Decimal

from pypdf import PdfReader

NUMBER_LABELS = ("Invoice #:", "Invoice number:", "Bill No.:", "Invoice No:")
DATE_LABELS = ("Invoice Date:", "Issue date:", "Date:", "Dated:")
PO_LABELS = ("PO:", "Purchase Order:", "Customer PO:")
TOTAL_LABELS = ("Amount Due:", "Total:", "Total Due:", "Balance Due:")
NUM = re.compile(r"^-?[\d,]+\.\d+$")


def _value_after(lines, labels):
    for i, line in enumerate(lines):
        if line in labels and i + 1 < len(lines):
            return lines[i + 1]
    return None


def _dec(s):
    return Decimal(s.replace(",", "")) if s is not None else None


def extract(path):
    text = "\n".join(page.extract_text() for page in PdfReader(path).pages)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    items, current = [], None
    try:
        start = next(i for i in range(len(lines) - 2)
                     if lines[i:i + 3] == ["Description", "Quantity", "Amount"]) + 3
    except StopIteration:
        start = len(lines)
    for line in lines[start:]:
        if line in TOTAL_LABELS:
            break
        if NUM.match(line):
            current["numbers"].append(_dec(line))
        else:
            current = {"description": line, "numbers": []}
            items.append(current)

    out_lines = []
    for n, it in enumerate(items, 1):
        nums = it["numbers"]
        out_lines.append({"line_no": n, "description": it["description"],
                          "quantity": nums[0] if len(nums) == 2 else None,
                          "amount": nums[-1] if nums else None})
    return {
        "vendor_name": lines[0] if lines else None,
        "vendor_invoice_number": _value_after(lines, NUMBER_LABELS),
        "invoice_date": _value_after(lines, DATE_LABELS),
        "po_number": _value_after(lines, PO_LABELS),
        "currency": "USD" if "Currency: USD" in text else None,
        "total": _dec(_value_after(lines, TOTAL_LABELS)),
        "lines": out_lines,
        "model": "rules-v1",
    }
