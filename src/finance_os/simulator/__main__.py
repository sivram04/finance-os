"""Run the live company up to today, one day at a time (real dates, never ahead of the clock).

    python -m finance_os.simulator            # catch up from the last simulated day to today
    python -m finance_os.simulator --no-stripe # same, without touching the Stripe sandbox
    python -m finance_os.simulator --reset     # start again from the end of the synthetic history

The daily job (python -m finance_os.daily) calls run() every morning; data/live/*.jsonl grows, vendor bill
PDFs land in the AP inbox, and the Stripe sandbox gets real invoices, charges, declines and refunds.
"""
import argparse
import shutil
from datetime import date, datetime, timedelta, timezone

from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT
from finance_os.simulator import ap_approvals
from finance_os.simulator.engine import Day
from finance_os.simulator.memory import Memory, history_chunks
from finance_os.simulator.stripe_live import NoStripe, SandboxStripe
from finance_os.simulator.world import LIVE, World, _rows, from_history


def run(no_stripe=False, reset=False, max_days=60, log=print):
    """Simulate every day from the last simulated one through today. Returns a summary dict."""
    load_dotenv(ROOT / ".env")
    live = ROOT / LIVE
    if reset and live.exists():
        shutil.rmtree(live)
    world = World.load(live) if (live / "world.json").exists() else from_history(ROOT / "data/synthetic")
    stripe = NoStripe() if no_stripe else SandboxStripe()
    if not no_stripe and "stripe_live_since" not in world.ops:
        world.ops["stripe_live_since"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    memory = Memory(live / "memory.duckdb")
    if memory.count() == 0:  # first run: the synthetic past becomes searchable memory
        segment_of = {c.customer_id: c.segment for c in world.customers.values()}
        log(f"memory: seeded {memory.add(history_chunks(_rows('lifecycle_events', ROOT / 'data/synthetic'), segment_of))} history chunks")
    summary = {"days": 0, "tokens": 0, "fallbacks": 0, "events": 0, "rejected": 0}
    approvals = ap_approvals.load()
    if not approvals["decisions_readable"]:
        log("AP approvals could not be read (app database busy and app not running): bills in review are held")
    try:
        day = world.day() + timedelta(days=1)
        while day <= date.today() and summary["days"] < max_days:
            out = Day(world, day, stripe, live, approvals=approvals).run(memory=memory)
            world.save(live)  # after every day, so a crash loses at most one day
            applied = [d["event"]["type"] + (f" {d['event'].get('customer_id') or d['event'].get('vendor_id') or d['event'].get('category') or ''}")
                       for d in out["decisions"] if d["status"] == "applied"]
            rejected = sum(d["status"] == "rejected" for d in out["decisions"])
            calls = out["agent_calls"]
            summary["tokens"] += sum(c.get("total_tokens", 0) or 0 for c in calls)
            summary["fallbacks"] += sum(1 for c in calls if c.get("fallback_from"))
            summary["events"] += len(applied)
            summary["rejected"] += rejected
            ap = f", {len(out['vendor_bills'])} bills in" if out["vendor_bills"] else ""
            ap += f", {len(out['ap_payments'])} bills paid" if out["ap_payments"] else ""
            ap += f", {len(out['ap_holds'])} held for approval" if out["ap_holds"] else ""
            log(f"{day}: {len(out['invoices'])} invoices, {len(out['payments'])} payments{ap} | "
                f"{', '.join(applied) or 'quiet day'}" + (f" ({rejected} rejected)" if rejected else "")
                + (" [fallback provider]" if any(c.get("fallback_from") for c in calls) else ""))
            day += timedelta(days=1)
            summary["days"] += 1
    finally:
        stripe.close()
    summary.update(as_of=world.as_of, cash=world.ops.get("cash"))
    log(f"simulated through {world.as_of}; cash {world.ops.get('cash')}; {summary['tokens']:,} tokens")
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-stripe", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--max-days", type=int, default=60, help="cap on days caught up in one run (cost guard)")
    a = p.parse_args()
    run(a.no_stripe, a.reset, a.max_days)


if __name__ == "__main__":
    main()
