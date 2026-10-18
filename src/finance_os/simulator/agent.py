"""The AI that decides what happens to the company each day; code checks every decision before it is applied.

The model (gpt-4.1-mini by default: cheap, ~$0.002 a day) sees a compact summary of the business and returns
events from a fixed menu. It never writes amounts: usage, prices and invoices are computed by the engine from
the price book. Each event passes `validate` (known customer, sane multiplier, funding left on the contract...)
or is logged as rejected.
"""
import json
import os
import urllib.request
from datetime import timedelta
from decimal import Decimal

EVENT_TYPES = ["new_customer", "expansion", "contraction", "churn", "spike", "late_payer", "payment_failure",
               "refund", "project_milestone", "vendor_price_increase", "duplicate_bill", "vendor_bill", "wrong_po_bill"]
CLOUD_VENDORS = ["gcp", "nimbus"]
BILL_CATEGORIES = ["legal", "consulting", "software", "marketing"]

BOUNDS = {"expansion": (Decimal("1.05"), Decimal("1.8")), "contraction": (Decimal("0.4"), Decimal("0.95")),
          "spike": (Decimal("1.5"), Decimal("4"))}
MAX_EVENTS = 4

PROMPT = """You simulate one day at Echo Labs, an AI speech-to-text SaaS (usage billed monthly per audio hour;
self-serve customers pay by card, mid-market and enterprise by invoice; some enterprise customers also buy
fixed-fee or T&M projects under contracts). Given today's state, decide what realistically happens TODAY.

Pace: over a typical month expect roughly 6-10 self-serve signups, 0-1 mid-market signup, 2-4 self-serve
churns, 0-1 mid-market churn, 3-6 expansions, 2-4 contractions, 1-2 late payers, 0-2 refunds, a payment failure
or two, about one milestone per live contract, 2-4 one-off vendor bills, and occasionally (every month or
two) a vendor price increase, a duplicate bill or a bill with a bad PO. Use allowed_today (already netted against the last 30 days) to keep that pace and make today's
events close the gap (so most days have 0-2 events, and not every day is quiet). allowed_today is how many more of each event the rules accept now (0 = none);
customers in usage_change_cooldown cannot expand, contract or spike yet. Base decisions on the state (usage trends, segment, overdue invoices,
remaining contract funding, weekday, month-end) and keep yearly rates plausible: self-serve churn ~3%/month,
mid-market ~1%/month, enterprise rare; a few self-serve signups per week; expansions follow growth; a project
milestone is billed only on a contract with funding left, at most a few per month company-wide.

Event fields (use null when not relevant):
- new_customer: segment, products (product ids), size ("small"|"medium"|"large")
- expansion / contraction: customer_id, multiplier (expansion 1.05-1.8, contraction 0.4-0.95)
- spike: customer_id, multiplier (1.5-4, one day only, e.g. archive backfill)
- churn: customer_id
- late_payer: customer_id, days (extra days past terms on their open invoices, 5-60)
- payment_failure: customer_id (self-serve card will be declined at next charge)
- refund: invoice_ref (a paid invoice), pct (0.05-1)
- project_milestone: contract_id, milestone_name, pct (share of the contract's remaining funding, 0.05-0.5)
Accounts payable (the bills Echo Labs receives; cloud and GPU bills, payroll and rent already run on schedule):
- vendor_price_increase: vendor_id ("gcp"|"nimbus"), pct (0.02-0.15): the next bill comes in higher than accrued
- duplicate_bill: vendor_id ("gcp"|"nimbus"): the vendor's next bill PDF is also sent a second time
- vendor_bill: category ("legal"|"consulting"|"software"|"marketing"), size: a one-off bill from a new vendor
- wrong_po_bill: category, size: a one-off bill that quotes a purchase order that doesn't exist
Before changing a specific customer, search_memory for its past (and similar customers' patterns) so the
story stays consistent. Always give a short business `reason` (e.g. competitor_price_cut, new_use_case, budget_cut)."""

_NULLABLE = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["events"],
    "properties": {"events": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["type", "customer_id", "segment", "products", "size", "multiplier", "days", "invoice_ref",
                     "pct", "contract_id", "milestone_name", "vendor_id", "category", "reason"],
        "properties": {
            "type": {"type": "string", "enum": EVENT_TYPES},
            "customer_id": _NULLABLE, "segment": {"type": ["string", "null"], "enum": ["self_serve", "mid_market", "enterprise", None]},
            "products": {"type": ["array", "null"], "items": {"type": "string"}},
            "size": {"type": ["string", "null"], "enum": ["small", "medium", "large", None]},
            "multiplier": {"type": ["number", "null"]}, "days": {"type": ["integer", "null"]},
            "invoice_ref": _NULLABLE, "pct": {"type": ["number", "null"]},
            "contract_id": _NULLABLE, "milestone_name": _NULLABLE,
            "vendor_id": {"type": ["string", "null"], "enum": CLOUD_VENDORS + [None]},
            "category": {"type": ["string", "null"], "enum": BILL_CATEGORIES + [None]},
            "reason": {"type": "string"}}}}}}


# Code-enforced rates, so a chatty model can't make the company unrealistic: (event, segment) -> (max, days)
CAPS = {("new_customer", "self_serve"): (3, 7), ("new_customer", "mid_market"): (1, 30),
        ("new_customer", "enterprise"): (1, 90), ("project_milestone", None): (2, 30),
        ("expansion", None): (6, 30), ("contraction", None): (4, 30), ("churn", None): (4, 30),
        ("spike", None): (2, 30), ("late_payer", None): (2, 30), ("payment_failure", None): (2, 30),
        ("refund", None): (2, 30), ("vendor_price_increase", None): (1, 90), ("duplicate_bill", None): (1, 30),
        ("vendor_bill", None): (4, 30), ("wrong_po_bill", None): (1, 60)}
COOLDOWN_DAYS = 60  # one usage change (expansion / contraction / spike) per customer per 60 days


def recent(history, today, days=30):
    cutoff = (today - timedelta(days=days)).isoformat()
    return [h for h in history if h["date"] >= cutoff]


def summarize(world, today, paid_invoices, history=()):
    """What the model sees: small enough to keep each call ~2-3k tokens."""
    by_seg = {}
    for c in world.active():
        s = by_seg.setdefault(c.segment, {"active": 0})
        s["active"] += 1
    big = sorted(world.active(), key=lambda c: -sum(Decimal(h) for h in c.daily_hours.values()))
    return {
        "today": today.isoformat(), "weekday": today.strftime("%A"),
        "segments": by_seg,
        "customers": [{"id": c.customer_id, "segment": c.segment, "daily_hours": {p: float(h) for p, h in c.daily_hours.items()},
                       "monthly_growth": c.monthly_growth, "pays_late_days": c.pays_late_days} for c in big[:40]],
        "overdue_invoices": [{"ref": r, "customer_id": i["customer_id"], "amount": i["amount"], "due": i["due"]}
                             for r, i in world.open_invoices.items() if i["due"] < today.isoformat()][:20],
        "recently_paid_invoices": paid_invoices[-15:],
        "contracts_with_funding": [{"id": k, "customer_id": v["customer_id"], "type": v["type"],
                                    "remaining": str(Decimal(v["funded"]) - Decimal(v["invoiced"])), "end": v["end"]}
                                   for k, v in world.contracts.items()
                                   if Decimal(v["funded"]) > Decimal(v["invoiced"]) and v["end"] >= today.isoformat()],
        "products": ["batch_base", "batch_pro", "stream"],
        "cash": world.ops.get("cash"),
        "open_vendor_bills": [{"bill_id": b, "vendor_id": v["vendor_id"], "amount": v["amount"], "due": v["due"]}
                              for b, v in sorted(world.ops.get("open_bills", {}).items())][:15],
        "vendor_price_factor": world.ops.get("price_factor"),
        "headcount": len(world.ops.get("employees", [])),
        "allowed_today": {f"{t} {s or 'any'}": n - sum(h["event"]["type"] == t and (s is None or h["event"].get("segment") == s)
                                                         for h in recent(history, today, d))
                          for (t, s), (n, d) in CAPS.items()},
        "usage_change_cooldown": sorted({h["event"]["customer_id"] for h in recent(history, today, COOLDOWN_DAYS)
                                         if h["event"]["type"] in ("expansion", "contraction", "spike")}),
    }


TOOLS = [
    {"type": "function", "function": {
        "name": "search_memory",
        "description": "Search the company's memory (past decisions and their reasons, daily digests, monthly summaries, "
                       "and the 2025-2026 history of churn/expansion/contraction). Use filters to narrow, the query to rank "
                       "by meaning. Look things up before deciding about a specific customer or pattern.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": ["query", "customer_id", "event_type", "kind", "since", "until"],
                       "properties": {"query": {"type": "string"},
                                      "customer_id": _NULLABLE,
                                      "event_type": {"type": ["string", "null"], "enum": EVENT_TYPES + ["reactivation", None]},
                                      "kind": {"type": ["string", "null"], "enum": ["decision", "daily", "monthly", "history", None]},
                                      "since": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
                                      "until": {"type": ["string", "null"], "description": "YYYY-MM-DD"}}},
        "strict": True}},
]
MAX_TOOL_ROUNDS = 4


def count_events(history, today, event_type, segment, days, segment_of):
    return sum(h["event"]["type"] == event_type and (segment is None or
               (h["event"].get("segment") or segment_of.get(h["event"].get("customer_id"))) == segment)
               for h in recent(history, today, days))


def _chat(body):
    """Any OpenAI-compatible API: SIM_API_KEY / SIM_BASE_URL (e.g. Groq's free tier), else OpenAI's."""
    key = os.environ.get("SIM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Neither SIM_API_KEY nor OPENAI_API_KEY is set (put one in .env)")
    base = os.environ.get("SIM_BASE_URL") or ("https://api.openai.com/v1" if not os.environ.get("SIM_API_KEY")
                                              else os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def _events(content):
    """The day's events; gpt-4.1-mini occasionally emits two JSON objects back to back after tool calls."""
    dec, i, events = json.JSONDecoder(), 0, []
    while i < len(content):
        obj, i = dec.raw_decode(content, i)
        events += obj["events"]
        while i < len(content) and content[i].isspace():
            i += 1
    return events


def decide(summary, tools):
    """Agent loop: the model may search memory / count events a few times, then returns the day's events.
    `tools` maps tool name -> callable(**args). Returns (events, usage incl. the searches it made)."""
    model = os.environ.get("SIM_MODEL") or os.environ.get("OPENAI_SIM_MODEL", "gpt-4.1-mini")
    messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(summary)}]
    usage = {"model": model, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "tool_calls": []}
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        body = {"model": model, "temperature": 0.8, "messages": messages,
                "response_format": {"type": "json_schema", "json_schema": {"name": "day", "schema": SCHEMA, "strict": True}}}
        if round_ < MAX_TOOL_ROUNDS:
            body["tools"] = TOOLS
        payload = _chat(body)
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[k] += payload.get("usage", {}).get(k, 0)
        msg = payload["choices"][0]["message"]
        if not msg.get("tool_calls"):
            return _events(msg["content"]), usage
        messages.append(msg)
        for call in msg["tool_calls"]:
            args = json.loads(call["function"]["arguments"])
            result = tools[call["function"]["name"]](**args)
            usage["tool_calls"].append({"tool": call["function"]["name"], **{k: v for k, v in args.items() if v is not None}})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, default=str)})
    raise RuntimeError("agent did not finish")


def decide_with_provider(summary, tools):
    """Try providers in SIM_PROVIDERS order. Default "claude_code": Claude Code headless only, on the user's
    Claude plan, no API keys. Add "api" (SIM_API_KEY or OpenAI) to the list for a fallback, e.g.
    "claude_code,api". The reason a provider was skipped is logged as fallback_from."""
    from finance_os.simulator import claude_provider
    providers = {"api": decide, "claude_code": claude_provider.decide}
    order = [p.strip() for p in os.environ.get("SIM_PROVIDERS", "claude_code").split(",") if p.strip()]
    skipped = []
    for name in order:
        try:
            events, usage = providers[name](summary, tools)
        except Exception as err:  # noqa: BLE001 - try the next provider; the reason is logged
            skipped.append(f"{name}: {str(err)[:200]}")
            continue
        return events, ({**usage, "fallback_from": "; ".join(skipped)} if skipped else usage)
    raise RuntimeError("every simulator provider failed: " + " | ".join(skipped))


def validate(e, world, today, paid_refs, products, history=()):
    """None if the event can be applied, else why not."""
    t, cid = e["type"], e.get("customer_id")
    seg = e.get("segment") if t == "new_customer" else None
    if (t, seg) in CAPS:
        n, days = CAPS[(t, seg)]
        if sum(h["event"]["type"] == t and (seg is None or h["event"].get("segment") == seg)
               for h in recent(history, today, days)) >= n:
            return f"rate limit: {t} {seg or ''} max {n} per {days} days"
    if t in ("expansion", "contraction", "spike") and any(
            h["event"]["type"] in ("expansion", "contraction", "spike") and h["event"].get("customer_id") == cid
            for h in recent(history, today, COOLDOWN_DAYS)):
        return f"{cid} already changed usage in the last {COOLDOWN_DAYS} days"
    if t == "project_milestone" and any(h["event"]["type"] == t and h["event"].get("contract_id") == e.get("contract_id")
                                        for h in recent(history, today, 30)):
        return f"{e.get('contract_id')} already billed a milestone in the last 30 days"
    customer = world.customers.get(cid) if cid else None
    if t in ("expansion", "contraction", "spike", "churn", "late_payer", "payment_failure"):
        if not customer or customer.status != "active":
            return f"{cid} is not an active customer"
    if t in BOUNDS:
        lo, hi = BOUNDS[t]
        if e.get("multiplier") is None or not lo <= Decimal(str(e["multiplier"])) <= hi:
            return f"multiplier {e.get('multiplier')} outside {lo}-{hi}"
    if t == "payment_failure" and customer.segment != "self_serve":
        return "only self-serve customers pay by card"
    if t == "late_payer" and not (e.get("days") and 5 <= e["days"] <= 60):
        return "days must be 5-60"
    if t == "new_customer":
        if e.get("segment") not in ("self_serve", "mid_market", "enterprise") or not e.get("size"):
            return "new customer needs segment and size"
        if not e.get("products") or any(p not in products for p in e["products"]):
            return f"unknown products {e.get('products')}"
    if t in ("vendor_price_increase", "duplicate_bill") and e.get("vendor_id") not in CLOUD_VENDORS:
        return f"vendor must be one of {CLOUD_VENDORS}"
    if t == "vendor_price_increase" and (e.get("pct") is None or not 0.02 <= e["pct"] <= 0.15):
        return "price increase pct must be 0.02-0.15"
    if t in ("vendor_bill", "wrong_po_bill") and (e.get("category") not in BILL_CATEGORIES or e.get("size") is None):
        return f"one-off bill needs a category in {BILL_CATEGORIES} and a size"
    if t == "refund":
        if e.get("invoice_ref") not in paid_refs:
            return f"{e.get('invoice_ref')} is not a paid invoice"
        if e.get("pct") is None or not 0.05 <= e["pct"] <= 1:
            return "refund pct must be 0.05-1"
    if t == "project_milestone":
        k = world.contracts.get(e.get("contract_id"))
        if not k or k["end"] < today.isoformat():
            return f"{e.get('contract_id')} is not a live contract"
        if Decimal(k["funded"]) <= Decimal(k["invoiced"]):
            return "no funding left on the contract"
        if e.get("pct") is None or not 0.05 <= e["pct"] <= 0.5 or not e.get("milestone_name"):
            return "milestone needs a name and pct 0.05-0.5"
    return None
