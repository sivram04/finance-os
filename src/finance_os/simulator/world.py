"""The live company's state: who the customers are, what they use, what is billed and owed.

Built once from the synthetic history (data/synthetic), then carried forward day by day in data/live/world.json.
Everything the simulator writes is appended to data/live/*.jsonl, so the history is an append-only log.
"""
import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from finance_os.generator.__main__ import load_config

SYNTH = Path("data/synthetic")
LIVE = Path("data/live")


@dataclass
class Customer:
    customer_id: str
    name: str
    segment: str
    status: str                      # active | churned
    daily_hours: dict                # product_id -> baseline audio hours per day (string decimals)
    monthly_growth: str
    pays_late_days: int = 0          # extra days past terms this customer usually takes
    payment_risk: bool = False       # next card charge fails
    stripe_id: str | None = None


@dataclass
class World:
    as_of: str                       # last simulated day (ISO)
    customers: dict = field(default_factory=dict)
    contracts: dict = field(default_factory=dict)   # contract_id -> {customer_id, funded, invoiced, terms, end}
    open_invoices: dict = field(default_factory=dict)  # erp ref -> {customer_id, amount, due, stripe_id, kind}
    paid: dict = field(default_factory=dict)            # erp ref -> {customer_id, amount, charge, refunded}
    seq: dict = field(default_factory=lambda: {"customer": 0, "invoice": 0, "project_invoice": 0, "event": 0})

    def day(self):
        return date.fromisoformat(self.as_of)

    def active(self):
        return [c for c in self.customers.values() if c.status == "active"]

    def next_id(self, kind, prefix, width=5):
        self.seq[kind] += 1
        return f"{prefix}{self.seq[kind]:0{width}d}"

    def save(self, live=LIVE):
        live.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        (live / "world.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")

    @classmethod
    def load(cls, live=LIVE):
        data = json.loads((live / "world.json").read_text(encoding="utf-8"))
        data["customers"] = {k: Customer(**v) for k, v in data["customers"].items()}
        return cls(**data)


def _rows(name, src=SYNTH):
    with open(src / f"{name}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def from_history(src=SYNTH):
    """Starting state at the end of the synthetic window: baselines from each customer's last 14 days of usage."""
    cfg = load_config()
    end = cfg["window"]["end"]
    recent = defaultdict(Decimal)
    last_seen = {}
    for u in _rows("usage_daily", src):
        d = date.fromisoformat(u["usage_date"])
        last_seen[u["customer_id"]] = max(last_seen.get(u["customer_id"], d), d)
        if d > end - timedelta(days=14):
            recent[(u["customer_id"], u["product_id"])] += Decimal(u["audio_hours"])
    world = World(as_of=end.isoformat())
    for c in _rows("customers", src):
        cid = c["customer_id"]
        hours = {p: str((h / 14).quantize(Decimal("0.0001"))) for (k, p), h in recent.items() if k == cid}
        active = cid in last_seen and last_seen[cid] >= end - timedelta(days=7) and hours
        world.customers[cid] = Customer(cid, c["customer_name"], c["segment"], "active" if active else "churned",
                                        hours or {}, c["monthly_growth"])
    invoiced = defaultdict(Decimal)
    for i in _rows("project_invoices", src):
        invoiced[i["contract_id"]] += Decimal(i["amount"])
    for k in _rows("contracts", src):
        world.contracts[k["contract_id"]] = {
            "customer_id": k["customer_id"], "type": k["contract_type"], "funded": k["funded_amount"],
            "invoiced": str(invoiced[k["contract_id"]]), "terms_days": int(k["payment_terms_days"]),
            "end": k["end_date"], "is_federal": k["is_federal"] == "True"}
    world.seq["customer"] = sum(1 for _ in world.customers)
    world.seq["project_invoice"] = len(_rows("project_invoices", src))
    return world


def append(name, rows, live=LIVE):
    """Append records to data/live/<name>.jsonl (the simulator's output tables)."""
    live.mkdir(parents=True, exist_ok=True)
    with open(live / f"{name}.jsonl", "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, default=str, separators=(",", ":")) + "\n")
