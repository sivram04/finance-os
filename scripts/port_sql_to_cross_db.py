"""One-off rewrite of DuckDB-only SQL in warehouse models/tests into the cross-database macros (macros/cross_db.sql).

    python scripts/port_sql_to_cross_db.py [--dry-run]

Mechanical, paren-aware rewrites only; anything subtler is ported by hand. Kept for the record of how the
BigQuery port was done.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "warehouse"


def _close(s, i):
    """Index just past the parenthesis group that opens at s[i] == '('."""
    depth, q = 0, None
    for j in range(i, len(s)):
        c = s[j]
        if q:
            q = None if c == q else q
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("unbalanced")


def _split_args(inner):
    out, depth, q, cur = [], 0, None, ""
    for c in inner:
        if q:
            q = None if c == q else q
        elif c in "'\"":
            q = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == "," and depth == 0:
            out.append(cur.strip()); cur = ""; continue
        cur += c
    out.append(cur.strip())
    return out


def rewrite_calls(s, name, fn):
    """Replace every call name(...) via fn(args) -> str or None (leave as is)."""
    pat = re.compile(r"(?<![\w.])" + re.escape(name) + r"\s*\(", re.I)
    i = 0
    while True:
        m = pat.search(s, i)
        if not m:
            return s
        open_ = m.end() - 1
        end = _close(s, open_)
        new = fn(_split_args(s[open_ + 1:end - 1]))
        if new is None:
            i = end
            continue
        s = s[:m.start()] + new + s[end:]
        i = m.start() + len(new)


def rewrite_filter(s):
    """agg(x) filter (where cond)  ->  agg(case when cond then x end); count(*) -> count(case when cond then 1 end)"""
    pat = re.compile(r"(?<![\w.])(count|sum|min|max|avg|any_value)\s*\(", re.I)
    i = 0
    while True:
        m = pat.search(s, i)
        if not m:
            return s
        end = _close(s, m.end() - 1)
        f = re.match(r"\s*filter\s*\(\s*where\s", s[end:], re.I)
        if not f:
            i = end
            continue
        fopen = end + s[end:].index("(")
        fend = _close(s, fopen)
        cond = s[fopen + 1:fend - 1].strip()[len("where"):].strip()
        arg = s[m.end():end - 1].strip()
        agg = m.group(1)
        value = "1" if arg == "*" else arg
        if arg.lower().startswith("distinct "):
            new = f"{agg}(distinct case when {cond} then {arg[9:]} end)"
        else:
            new = f"{agg}(case when {cond} then {value} end)"
        s = s[:m.start()] + new + s[fend:]
        i = m.start() + len(new)


def port(s):
    s = rewrite_filter(s)
    s = rewrite_calls(s, "date_trunc", lambda a: "{{ month_start(" + repr_sql(a[1]) + ") }}"
                      if a[0].strip("'\"").lower() == "month" else None)
    s = rewrite_calls(s, "date_diff", lambda a: "{{ days_between(" + repr_sql(a[1]) + ", " + repr_sql(a[2]) + ") }}"
                      if a[0].strip("'\"").lower() == "day" else None)
    s = rewrite_calls(s, "strftime", lambda a: "{{ fmt_month(" + repr_sql(a[0]) + ") }}" if a[1] == "'%Y-%m'" else None)
    s = rewrite_calls(s, "dayofweek", lambda a: "{{ day_of_week(" + repr_sql(a[0]) + ") }}")
    s = rewrite_calls(s, "year", lambda a: f"extract(year from {a[0]})")
    s = rewrite_calls(s, "median", lambda a: "{{ median(" + repr_sql(a[0]) + ") }}")
    s = rewrite_calls(s, "bool_or", lambda a: "{{ bool_or(" + repr_sql(a[0]) + ") }}")
    s = rewrite_calls(s, "bool_and", lambda a: "{{ bool_and(" + repr_sql(a[0]) + ") }}")
    s = re.sub(r"cross join range\((\w+), (\w+)\) (\w+)\(n\)",
               lambda m: f"cross join {{{{ int_series('{m.group(3)}', {m.group(1)}, {m.group(2)} - 1) }}}}", s)
    s = re.sub(r"(?i)\bas varchar\b", "as {{ t_string() }}", s)
    s = re.sub(r"(?i)\bas double\b", "as {{ t_float() }}", s)
    return s


def repr_sql(x):
    """A SQL fragment as a Jinja string literal (macros receive SQL text)."""
    if "{{" in x:  # already a macro call: pass the inner expression through as-is
        x = x.replace("{{ ", "").replace(" }}", "")
    return '"' + x.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    dry = "--dry-run" in sys.argv
    changed = 0
    for path in sorted(list((ROOT / "models").rglob("*.sql")) + list((ROOT / "tests").rglob("*.sql"))):
        old = path.read_text(encoding="utf-8")
        new = port(old)
        if new != old:
            changed += 1
            print(("would change " if dry else "changed ") + str(path.relative_to(ROOT)))
            if not dry:
                path.write_text(new, encoding="utf-8", newline="\n")
    print(f"{changed} files")


if __name__ == "__main__":
    main()
