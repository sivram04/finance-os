"""Run the live company up to today, one day at a time (real dates, never ahead of the clock).

    python -m finance_os.simulator            # catch up from the last simulated day to today
    python -m finance_os.simulator --no-stripe # same, without touching the Stripe sandbox
    python -m finance_os.simulator --reset     # start again from the end of the synthetic history

Schedule it daily (Task Scheduler / cron) and the business keeps moving: data/live/*.jsonl grows and the
Stripe sandbox gets real invoices, charges, declines and refunds on their real dates.
"""
import argparse
import shutil
from datetime import date, timedelta

from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT
from finance_os.simulator.engine import Day
from finance_os.simulator.memory import Memory, history_chunks
from finance_os.simulator.stripe_live import NoStripe, SandboxStripe
from finance_os.simulator.world import LIVE, World, _rows, from_history


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--no-stripe", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument("--max-days", type=int, default=60, help="cap on days caught up in one run (cost guard)")
    a = p.parse_args()
    load_dotenv(ROOT / ".env")
    live = ROOT / LIVE
    if a.reset and live.exists():
        shutil.rmtree(live)
    world = World.load(live) if (live / "world.json").exists() else from_history(ROOT / "data/synthetic")
    stripe = NoStripe() if a.no_stripe else SandboxStripe()
    memory = Memory(live / "memory.duckdb")
    if memory.count() == 0:  # first run: the synthetic past becomes searchable memory
        segment_of = {c.customer_id: c.segment for c in world.customers.values()}
        print(f"memory: seeded {memory.add(history_chunks(_rows('lifecycle_events', ROOT / 'data/synthetic'), segment_of))} history chunks")
    tokens, days, searches = 0, 0, 0
    try:
        day = world.day() + timedelta(days=1)
        while day <= date.today() and days < a.max_days:
            out = Day(world, day, stripe, live).run(memory=memory)
            world.save(live)  # after every day, so a crash loses at most one day
            applied = [d["event"]["type"] + (f" {d['event']['customer_id']}" if d["event"].get("customer_id") else "")
                       for d in out["decisions"] if d["status"] == "applied"]
            rejected = sum(d["status"] == "rejected" for d in out["decisions"])
            tokens += sum(c.get("total_tokens", 0) for c in out["agent_calls"])
            searches += sum(len(c.get("tool_calls", [])) for c in out["agent_calls"])
            print(f"{day}: {len(out['usage_daily'])} usage rows, {len(out['invoices'])} invoices, "
                  f"{len(out['payments'])} payments | {', '.join(applied) or 'quiet day'}"
                  + (f" ({rejected} rejected)" if rejected else ""))
            day += timedelta(days=1)
            days += 1
    finally:
        stripe.close()
        memory.close()
    print(f"simulated through {world.as_of}; {tokens:,} tokens; {searches} memory lookups")


if __name__ == "__main__":
    main()
