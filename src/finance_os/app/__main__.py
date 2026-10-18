"""Run the Finance OS API locally: python -m finance_os.app [--port 8000]"""
import argparse

import uvicorn

from finance_os.app.api import create_app
from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
