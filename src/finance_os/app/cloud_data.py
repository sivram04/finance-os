"""The deployed app's data: the daily snapshot that finance_os.deploy uploads to Cloud Storage.

At startup the app downloads gs://<bucket>/current/* into its local data folder; a background thread then checks
manifest.json every 10 minutes and swaps in a new day when the laptop's daily job has uploaded one. Auth is the
Cloud Run service account (Application Default Credentials); no key files.
"""
import json
import os
import threading
import time
from urllib.parse import quote

import httpx

from finance_os.paths import ROOT

BUCKET = os.environ.get("FINANCE_OS_DATA_BUCKET")
CHECK_EVERY = int(os.environ.get("FINANCE_OS_DATA_CHECK_SECONDS", "600"))
PLACES = {  # object name -> local path
    "finance_os_app.duckdb": ROOT / "data" / "deploy" / "finance_os_app.duckdb",
    "alerts.duckdb": ROOT / "data" / "alerts.duckdb",
    "world.json": ROOT / "data" / "live" / "world.json",
}
STATE = {"manifest": None, "error": None, "checked_at": None}


def _token():
    import google.auth
    import google.auth.transport.requests
    cred = STATE.get("cred")
    if cred is None:
        cred, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/devstorage.read_only"])
        STATE["cred"] = cred
    if not cred.valid:
        cred.refresh(google.auth.transport.requests.Request())
    return cred.token


def _get(name):
    url = f"https://storage.googleapis.com/download/storage/v1/b/{BUCKET}/o/{quote('current/' + name, safe='')}?alt=media"
    r = httpx.get(url, headers={"Authorization": f"Bearer {_token()}"}, timeout=300)
    r.raise_for_status()
    return r.content


def _place(name):
    if name in PLACES:
        return PLACES[name]
    if name.endswith(".json"):
        return ROOT / "data" / "ml" / name  # model outputs
    return None


def sync():
    """Download a new day if the manifest changed. Returns True when files were replaced."""
    STATE["checked_at"] = time.time()
    manifest = json.loads(_get("manifest.json"))
    if STATE["manifest"] and manifest.get("uploaded_at") == STATE["manifest"].get("uploaded_at"):
        return False
    for name in manifest.get("files", []):
        dest = _place(name)
        if dest is None:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".download")
        tmp.write_bytes(_get(name))
        os.replace(tmp, dest)  # queries open the warehouse per call, so the swap is safe
    STATE["manifest"] = manifest
    return True


def start():
    """Sync once (blocking: the app needs data before serving), then keep checking in the background."""
    if not BUCKET:
        return
    sync()

    def loop():
        while True:
            time.sleep(CHECK_EVERY)
            try:
                sync()
                STATE["error"] = None
            except Exception as e:  # noqa: BLE001 - keep serving yesterday's data
                STATE["error"] = f"{type(e).__name__}: {e}"
    threading.Thread(target=loop, daemon=True, name="cloud-data-sync").start()
