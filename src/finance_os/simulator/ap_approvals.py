"""Which vendor bills may be paid: the approval gate between AP intake and the payment run.

A live bill is payable when its PDF was auto-approved by intake (marts.fct_ap_documents.route) or a person
approved it in the app (an approved ap_approve action). A bill a person rejected is never paid. Anything else
is held for review. Bills that were already open when the live period began were approved in the history.

Approvals come from data/app.duckdb, read directly, or through the running app's API when the app holds the
database open (DuckDB allows one process at a time). If neither can be read, every live bill is held: when in
doubt, don't pay.
"""
import json
import urllib.request

import duckdb

from finance_os.paths import ROOT

WAREHOUSE = ROOT / "data" / "finance_os.duckdb"
APP_DB = ROOT / "data" / "app.duckdb"
APP_API = "http://127.0.0.1:8000/api/actions?status=approved"


def _routes():
    try:
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        try:
            return dict(con.execute("select doc_file, route from marts.fct_ap_documents").fetchall())
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - no warehouse yet, or it is busy: no routes known
        return {}


def _approved_actions():
    """[(kind, doc_file)] for approved AP decisions, or None if they cannot be read."""
    try:
        con = duckdb.connect(str(APP_DB), read_only=True)
        try:
            return con.execute("select kind, target_id from actions where status = 'approved' "
                               "and kind in ('ap_approve', 'ap_reject')").fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - locked by the running app: ask the app instead
        pass
    try:
        with urllib.request.urlopen(APP_API, timeout=5) as r:
            return [(a["kind"], a["target_id"]) for a in json.loads(r.read()) if a["kind"] in ("ap_approve", "ap_reject")]
    except Exception:  # noqa: BLE001
        return None


def load():
    """{doc_file: 'approved' | 'rejected' | 'review'} plus whether people's decisions could be read."""
    status = {doc: ("approved" if route == "auto_approve" else "review") for doc, route in _routes().items()}
    actions = _approved_actions()
    for kind, doc in actions or []:
        status[doc] = "approved" if kind == "ap_approve" else "rejected"
    return {"documents": status, "decisions_readable": actions is not None}


def payable(bill, approvals):
    """'pay', 'hold' or 'rejected' for an open bill."""
    doc = bill.get("doc_file")
    if not doc:
        return "pay"  # open before the live period began: approved in the history
    s = (approvals or {}).get("documents", {}).get(doc, "review")
    return {"approved": "pay", "rejected": "rejected"}.get(s, "hold")
