"""The simulator's long-term memory: small chunks, searched on demand instead of re-read in full.

Chunks are short texts with metadata (date, kind, customer_id, event_type, segment):
- one per decision (what happened to whom and why, applied or rejected),
- one daily digest (usage, events, billing that day),
- one monthly summary written on the 1st (counts per event type, active customers, billed revenue): the
  long-range patterns, so a search over a year reads 12 summaries, not 365 days,
- plus the synthetic history's lifecycle events (Jan 2025 - Sep 2026), so the agent can learn the company's
  past patterns ("how often do mid-market customers contract, and why?").

Search is hybrid: exact metadata filters (customer, event type, date range) narrow the set, then the query's
embedding (OpenAI text-embedding-3-small, ~$0.02 per million tokens) ranks what is left by cosine similarity,
inside DuckDB. Without an API key it falls back to keyword overlap, so tests and offline runs work.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

import duckdb

EMBED_MODEL = "text-embedding-3-small"


def embed(texts):
    key = os.environ.get("OPENAI_API_KEY")
    if not key or not texts:
        return [None] * len(texts)
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    out = []
    for i in range(0, len(texts), 256):
        req = urllib.request.Request(f"{base}/embeddings", data=json.dumps({"model": EMBED_MODEL, "input": texts[i:i + 256]}).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            out += [d["embedding"] for d in json.loads(resp.read())["data"]]
    return out


def _words(s):
    return set(re.findall(r"[a-z0-9_-]+", s.lower()))


class _Session:
    """One connection per operation, so another process (the memory-search CLI) can read between calls."""

    def __init__(self, path, read_only=False):
        self.path, self.read_only = path, read_only

    def __enter__(self):
        self.con = duckdb.connect(str(self.path), read_only=self.read_only)
        return self.con

    def __exit__(self, *exc):
        self.con.close()


class Memory:
    def __init__(self, path: Path, embedder=embed, read_only=False):
        self.path, self.embed, self.read_only = path, embedder, read_only
        if not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
            with _Session(path) as con:
                con.execute("""create table if not exists chunks (
                    chunk_id varchar primary key, date date, kind varchar, customer_id varchar, event_type varchar,
                    segment varchar, text varchar, embedding float[])""")

    def close(self):
        pass

    def count(self):
        with _Session(self.path, self.read_only) as con:
            return con.execute("select count(*) from chunks").fetchone()[0]

    def add(self, chunks):
        """chunks: dicts with chunk_id, date, kind, text and optional customer_id / event_type / segment."""
        with _Session(self.path) as con:
            new = [c for c in chunks if not con.execute("select 1 from chunks where chunk_id = ?", [c["chunk_id"]]).fetchone()]
        vectors = self.embed([c["text"] for c in new])
        with _Session(self.path) as con:
            for c, v in zip(new, vectors):
                con.execute("insert into chunks values (?, ?, ?, ?, ?, ?, ?, ?)",
                            [c["chunk_id"], c["date"], c["kind"], c.get("customer_id"), c.get("event_type"),
                             c.get("segment"), c["text"], v])
        return len(new)

    def search(self, query, customer_id=None, event_type=None, kind=None, since=None, until=None, k=8):
        """Filters first (exact), then rank by meaning; newest first on ties."""
        where, args = ["true"], []
        for col, val in (("customer_id", customer_id), ("event_type", event_type), ("kind", kind)):
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if since:
            where.append("date >= cast(? as date)")
            args.append(since)
        if until:
            where.append("date <= cast(? as date)")
            args.append(until)
        with _Session(self.path, self.read_only) as con:
            return self._search(con, query, where, args, k)

    def _search(self, con, query, where, args, k):
        rows = con.execute(f"select chunk_id, date, text, embedding from chunks where {' and '.join(where)}", args).fetchall()
        qv = self.embed([query])[0] if query else None
        if qv is not None and rows and rows[0][3] is not None:
            scored = con.execute(
                f"select date, text, list_cosine_similarity(embedding, ?::float[]) s from chunks "
                f"where {' and '.join(where)} order by s desc, date desc limit {int(k)}", [qv, *args]).fetchall()
            return [{"date": str(d), "text": t, "score": round(s, 3)} for d, t, s in scored]
        q = _words(query or "")
        ranked = sorted(rows, key=lambda r: (len(q & _words(r[2])), r[1]), reverse=True)[:k]
        return [{"date": str(d), "text": t} for _, d, t, _ in ranked]


# ---- chunk builders -------------------------------------------------------------------------------------

def decision_chunk(d, segment=None):
    e = d["event"]
    who = e.get("customer_id") or e.get("contract_id") or (f"new {e.get('segment')} customer" if e["type"] == "new_customer" else "")
    detail = ", ".join(f"{k}={v}" for k, v in e.items() if v is not None and k not in ("type", "reason", "customer_id"))
    text = f"{d['date']}: {e['type']} {who} ({detail}). Reason: {e['reason']}." + (
        f" REJECTED: {d['note']}" if d["status"] == "rejected" else "")
    n = d.get("n", 0)
    return {"chunk_id": f"decision|{d['date']}|{n}|{e['type']}|{who}", "date": d["date"], "kind": "decision",
            "customer_id": e.get("customer_id"), "event_type": e["type"], "segment": e.get("segment") or segment, "text": text}


def daily_chunk(day, out):
    hours = sum(float(u["audio_hours"]) for u in out.get("usage_daily", []))
    applied = [d["event"]["type"] for d in out.get("decisions", []) if d["status"] == "applied"]
    billed = sum(float(i["amount"]) for i in out.get("invoices", []))
    paid = sum(float(p["amount"]) for p in out.get("payments", []))
    text = (f"{day} ({day:%A}) digest: {hours:,.0f} audio hours across {len(out.get('usage_daily', []))} customer-products; "
            f"events: {', '.join(applied) or 'none'}; invoiced ${billed:,.2f}; collected ${paid:,.2f}.")
    return {"chunk_id": f"daily|{day}", "date": day.isoformat(), "kind": "daily", "text": text}


def monthly_chunk(month, decisions, world, invoices):
    """Written on the 1st for the month just ended."""
    m = month.isoformat()[:7]
    counts = {}
    for d in decisions:
        if d["date"].startswith(m) and d["status"] == "applied":
            counts[d["event"]["type"]] = counts.get(d["event"]["type"], 0) + 1
    segs = {}
    for c in world.active():
        segs[c.segment] = segs.get(c.segment, 0) + 1
    billed = sum(float(i["amount"]) for i in invoices if str(i["service_month"]).startswith(m))
    text = (f"Month {month:%B %Y} summary: events {json.dumps(counts) if counts else 'none'}; active customers {segs}; "
            f"usage billed ${billed:,.2f}.")
    return {"chunk_id": f"monthly|{m}", "date": month.isoformat(), "kind": "monthly", "text": text}


def history_chunks(lifecycle_rows, segment_of):
    """The synthetic past (lifecycle_events.csv) as chunks: the patterns the company already lived through."""
    return [{"chunk_id": f"history|{r['event_id']}", "date": r["event_date"], "kind": "history",
             "customer_id": r["customer_id"], "event_type": r["event_type"], "segment": segment_of.get(r["customer_id"]),
             "text": f"{r['event_date']}: {r['event_type']} {r['customer_id']} ({segment_of.get(r['customer_id'])}), "
                     f"usage x{r['multiplier']}. Reason: {r['reason']}."} for r in lifecycle_rows]


def main():
    """CLI used by the Claude Code provider: python -m finance_os.simulator.memory search "query" [filters]"""
    import argparse

    from finance_os.ingestion.ap_intake.__main__ import load_dotenv
    from finance_os.paths import ROOT
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["search"])
    p.add_argument("query")
    p.add_argument("--customer")
    p.add_argument("--type", dest="event_type")
    p.add_argument("--kind")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("-k", type=int, default=8)
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    m = Memory(ROOT / "data" / "live" / "memory.duckdb", read_only=True)
    print(json.dumps(m.search(a.query, customer_id=a.customer, event_type=a.event_type, kind=a.kind,
                              since=a.since, until=a.until, k=a.k), indent=1))


if __name__ == "__main__":
    main()
