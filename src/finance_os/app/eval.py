"""Run the assistant eval (design §9.3): python -m finance_os.app.eval [--model google/gemini-2.5-flash] [--runs 1] [--only id,id]

Each question runs in a fresh conversation against a throwaway app database. Results are written to
evals/assistant/results/<timestamp>_<model>.csv with pass/fail per check, unverified numbers, steps, tokens
and latency, and a summary is printed. It calls the real OpenAI API, so it costs money (cents per question).
"""
import argparse
import csv
import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

import yaml

from finance_os.app.agent import Agent
from finance_os.app.state import AppState
from finance_os.app.tools import Warehouse
from finance_os.app.validator import _matches, answer_numbers
from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT

QUESTIONS = ROOT / "evals" / "assistant" / "questions.yaml"
RESULTS = ROOT / "evals" / "assistant" / "results"
REFUSAL = re.compile(r"can(?:no|')t|unable|not able|outside|don't provide|do not provide|not (?:in a position|qualified)"
                     r"|investment advice|not provide", re.I)


def _scalar(wh, sql):
    m = wh.latest_month()
    rows = wh.query(sql.replace("month=M", f"month=date '{m}'"))
    return next(iter(rows[0].values())) if rows else None


def _value_found(answer, expected):
    return any(_matches(v, d, s, p, [expected]) for _, v, d, s, p, _ in answer_numbers(answer))


def run_question(q, wh, model):
    with tempfile.TemporaryDirectory() as tmp:
        state = AppState(Path(tmp) / "app.duckdb")
        cid = state.new_conversation()
        t0 = time.perf_counter()
        events = list(Agent(state, wh, model=model).run(cid, q["ask"]))
        latency = time.perf_counter() - t0
        answer = next((e for e in events if e["type"] == "answer"), {"text": "", "unverified_numbers": []})
        done = events[-1]
        tools_called = [e["tool"] for e in events if e["type"] == "step"]
        checks = []
        for sql in q.get("expect_values", []):
            expected = _scalar(wh, sql)
            checks.append((f"value {expected}", expected is not None and _value_found(answer["text"], float(expected))))
        for tool in q.get("expect_tools", []):  # "a|b": either tool is a valid source
            checks.append((f"tool {tool}", any(t in tools_called for t in tool.split("|"))))
        for sql in q.get("expect_text", []):
            pattern = sql.strip("'") if sql.startswith("'") else _scalar(wh, sql)
            checks.append((f"text {pattern}", bool(pattern) and re.search(str(pattern), answer["text"], re.I) is not None))
        if q.get("expect_refusal"):
            checks.append(("refused", bool(REFUSAL.search(answer["text"]))))
        if q.get("expect_proposal"):
            kinds = [a["kind"] for a in state.actions()]
            executed = [a for a in state.actions() if a["status"] != "pending"]
            checks.append((f"proposal {q['expect_proposal']}", q["expect_proposal"] in kinds and not executed))
        state.con.close()
    no_unverified = not answer["unverified_numbers"]
    return {
        "id": q["id"], "persona": q["persona"],
        "passed": all(ok for _, ok in checks) and no_unverified and done["stopped"] == "answered",
        "checks": "; ".join(f"{name}={'ok' if ok else 'FAIL'}" for name, ok in checks),
        "unverified": " ".join(answer["unverified_numbers"]),
        "stopped": done["stopped"], "steps": done["steps"], "tools": " ".join(tools_called),
        "prompt_tokens": done["prompt_tokens"], "completion_tokens": done["completion_tokens"],
        "latency_s": round(latency, 1), "answer": answer["text"].replace("\n", " ")[:600],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--only", help="comma-separated question ids")
    p.add_argument("--workers", type=int, default=6, help="questions run in parallel")
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    from finance_os.app.agent import default_model
    model = a.model or default_model()
    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))["questions"]
    if a.only:
        keep = set(a.only.split(","))
        questions = [q for q in questions if q["id"] in keep]
    import threading
    from concurrent.futures import ThreadPoolExecutor
    local, lock = threading.local(), threading.Lock()
    jobs = [(run, q) for run in range(1, a.runs + 1) for q in questions]
    RESULTS.mkdir(parents=True, exist_ok=True)
    partial = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}_{model.replace('/', '-')}.partial.jsonl"
    done = {"n": 0, "passed": 0}

    def one(run, q):
        if not hasattr(local, "wh"):
            local.wh = Warehouse()  # a warehouse connection per worker thread
        r = {"run": run, **run_question(q, local.wh, model)}
        with lock:  # progress line and a saved row per question, so a stopped run keeps what it finished
            done["n"] += 1
            done["passed"] += bool(r["passed"])
            with open(partial, "a", encoding="utf-8") as f:
                f.write(json.dumps(r, default=str) + "\n")
            print(f"[{done['n']}/{len(jobs)} done, {done['passed']} passed] {'PASS' if r['passed'] else 'FAIL'}  {r['id']:28} "
                  f"steps={r['steps']:<2} {r['latency_s']:>5}s  {r['checks']}"
                  + (f"  unverified: {r['unverified']}" if r["unverified"] else ""), flush=True)
        return r
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(lambda j: one(*j), jobs))
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{datetime.now():%Y%m%d-%H%M%S}_{model.replace("/", "-")}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    passed = sum(r["passed"] for r in rows)
    p_tok = sum(r["prompt_tokens"] for r in rows)
    c_tok = sum(r["completion_tokens"] for r in rows)
    print(f"\n{passed}/{len(rows)} passed with {model}. Tokens: {p_tok:,} in / {c_tok:,} out. Results: {out}")


if __name__ == "__main__":
    main()
