"""Number validator (design §9.2): every number the assistant writes must come from a tool result.

Code, not a model. It pulls the numbers out of the answer and looks for each among the numbers the tools
returned this turn, allowing only for how the answer rounded or scaled it ($30K for 30,335.85; 46.4% for
0.4638). Anything else is reported as unverified, which usually means the model computed or invented it.
Identifiers (EN-001, INV-…-202606, P-103), dates and years, and small list numbers are ignored.
"""
import re

ID_OR_DATE = re.compile(
    r"\b[A-Za-z]{1,6}-[\w-]*\d[\w-]*\b"       # EN-001, INV-EN-001-202606, P-103, A-M2-01, BVA-202604-GA-6400
    r"|\b\d{4}-\d{2}(?:-\d{2})?\b"             # 2026-09, 2026-09-30
    r"|\b(?:FY|Q[1-4])\s?\d{2,4}\b"            # FY2026, Q3 2026
    r"|\b[A-Z]{1,6}\d{3,}\b"                   # PINV00014, PAY000786, PO00001
)
NUMBER = re.compile(r"(?<![\w.])(\$)?(-?\d[\d,]*(?:\.\d+)?)\s?(%|[kKmMbB]\b|million\b|billion\b|thousand\b)?")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "m": 1e6, "M": 1e6, "million": 1e6, "b": 1e9, "B": 1e9, "billion": 1e9}
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
MONTH_YEAR = re.compile(rf"\b{MONTHS}\.?\s+(?:\d{{1,2}},\s+)?\d{{4}}\b|\b\d{{1,2}}\s+{MONTHS}\s+\d{{4}}\b")


def tool_numbers(obj, out=None):
    """Every number in a tool result, recursively (numeric strings included)."""
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        # numbers inside text the tools returned (labels like "61-90" or "90+", messages like
        # "sum of lines 2000.00") were returned too
        out += [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", obj)]
    elif isinstance(obj, dict):
        for k, v in obj.items():
            tool_numbers(k, out)  # thresholds named in fields, e.g. is_funding_alert_75
            tool_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            tool_numbers(v, out)
    return out


def answer_numbers(text):
    """(original text, value, decimals, scale, is_percent, has_currency) for each number worth checking."""
    clean = MONTH_YEAR.sub(" ", ID_OR_DATE.sub(" ", text))
    found = []
    for m in NUMBER.finditer(clean):
        cur, raw, suffix = m.group(1), m.group(2), m.group(3)
        value = float(raw.replace(",", ""))
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        is_pct = suffix == "%"
        scale = SCALE.get(suffix, 1.0) if suffix and not is_pct else 1.0
        if not cur and not suffix and decimals == 0:
            if abs(value) < 10:            # list numbering, small counts in prose
                continue
            if 1990 <= value <= 2100:      # years
                continue
        found.append((m.group(0).strip(), value, decimals, scale, is_pct, bool(cur)))
    return found


def _matches(value, decimals, scale, is_pct, candidates):
    half = 0.5 * 10 ** -decimals
    targets = []
    if is_pct:
        targets = [(value / 100, half / 100), (value, half)]
    else:
        targets = [(value * scale, half * scale)]
    for target, tol in targets:
        for v in candidates:
            for c in (v, -v, v * 100 if not is_pct else v):
                if abs(c - target) <= tol + 1e-9 or abs(abs(c) - abs(target)) <= tol + 1e-9:
                    return True
    return False


def unverified_numbers(answer, tool_results):
    candidates = tool_numbers(tool_results)
    bad = []
    for text, value, decimals, scale, is_pct, _ in answer_numbers(answer):
        if not _matches(value, decimals, scale, is_pct, candidates):
            bad.append(text)
    return bad
