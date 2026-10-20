"""The deployed app (Cloud Run): the same API as local, plus what a public demo needs.

    uvicorn finance_os.app.cloud:app --host 0.0.0.0 --port $PORT

- data      downloaded from Cloud Storage at startup and refreshed daily (cloud_data)
- web       the built React app (web/dist) served from the same origin, with SPA fallback
- demo      a daily cap on assistant questions across all visitors (Gemini costs per question) and /api/demo for
            the banner; approvals and uploads only change this instance's demo state, which resets on restart
- CORS      extra origins (e.g. a Cloudflare Pages front end) from FINANCE_OS_ALLOWED_ORIGINS
"""
import datetime as dt
import os
import threading

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from finance_os.app import cloud_data
from finance_os.paths import ROOT

DAILY_QUESTIONS = int(os.environ.get("DEMO_DAILY_QUESTIONS", "50"))
WEB = ROOT / "web" / "dist"
_count = {"day": None, "n": 0}
_lock = threading.Lock()


def _left():
    today = dt.date.today().isoformat()
    with _lock:
        if _count["day"] != today:
            _count.update(day=today, n=0)
        return max(DAILY_QUESTIONS - _count["n"], 0)


def create():
    cloud_data.start()
    os.environ.setdefault("FINANCE_OS_NO_TRAIN", "1")  # models are trained on the laptop; never here
    from finance_os.app.api import create_app
    app = create_app()
    origins = [o.strip() for o in os.environ.get("FINANCE_OS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def question_cap(request: Request, call_next):
        if request.method == "POST" and request.url.path.startswith("/api/conversations/") and request.url.path.endswith("/messages"):
            if _left() <= 0:
                return JSONResponse({"detail": f"The demo's daily limit of {DAILY_QUESTIONS} assistant questions is "
                                               "used up. It resets at midnight UTC; the dashboards still work."}, status_code=429)
            with _lock:
                _count["n"] += 1
        return await call_next(request)

    @app.get("/api/demo")
    def demo():
        m = cloud_data.STATE.get("manifest") or {}
        return {"demo": True, "questions_left_today": _left(), "daily_question_limit": DAILY_QUESTIONS,
                "data_through": m.get("data_through"), "data_uploaded_at": m.get("uploaded_at"),
                "data_sync_error": cloud_data.STATE.get("error")}

    if WEB.exists():
        app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = WEB / path
            return FileResponse(f if path and f.is_file() else WEB / "index.html")
    return app


app = create()
