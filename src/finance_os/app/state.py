"""App state: everything a person or the assistant does, in data/app.duckdb (design §9.5).

The warehouse is rebuilt from scratch by the generator and dbt, so conversations, proposed actions,
decisions and the audit log live here instead, where builds never touch them. History is append-only:
an undo is a new audit row and a status change, never a delete.
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from finance_os.paths import ROOT

DEFAULT_PATH = ROOT / "data" / "app.duckdb"
USER = "you"  # single local user in phase 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (id VARCHAR PRIMARY KEY, title VARCHAR, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS messages (
    conversation_id VARCHAR, seq INTEGER, role VARCHAR, payload JSON, created_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS turns (
    id VARCHAR PRIMARY KEY, conversation_id VARCHAR, model VARCHAR, steps INTEGER,
    prompt_tokens INTEGER, completion_tokens INTEGER, stopped_reason VARCHAR,
    started_at TIMESTAMP, finished_at TIMESTAMP);
CREATE TABLE IF NOT EXISTS actions (
    id VARCHAR PRIMARY KEY, conversation_id VARCHAR, kind VARCHAR, target_id VARCHAR, payload JSON,
    preview VARCHAR, status VARCHAR, created_at TIMESTAMP, decided_at TIMESTAMP, decided_by VARCHAR);
CREATE TABLE IF NOT EXISTS deals (
    id VARCHAR PRIMARY KEY, customer VARCHAR, payload JSON, evaluation JSON, route VARCHAR, action_id VARCHAR,
    created_at TIMESTAMP);
CREATE SEQUENCE IF NOT EXISTS audit_seq;
CREATE TABLE IF NOT EXISTS audit_log (
    seq BIGINT DEFAULT nextval('audit_seq'), id VARCHAR PRIMARY KEY, action_id VARCHAR, event VARCHAR, actor VARCHAR, occurred_at TIMESTAMP,
    before_status VARCHAR, after_status VARCHAR, note VARCHAR);
"""


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


class AppState:
    def __init__(self, path: Path = DEFAULT_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(SCHEMA)
        self.lock = threading.Lock()
        self._supersede_duplicates()

    def _q(self, sql, params=None):
        with self.lock:
            cur = self.con.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, r)) for r in cur.fetchall()] if cols else []

    # conversations and messages
    def new_conversation(self, title="New conversation"):
        cid = uuid.uuid4().hex[:12]
        self._q("INSERT INTO conversations VALUES (?, ?, ?)", [cid, title, now()])
        return cid

    def conversations(self, limit=30):
        return self._q("""select c.id, c.title, c.created_at, max(m.created_at) as updated_at
                          from conversations c left join messages m on m.conversation_id = c.id
                          group by all having count(m.seq) > 0 order by updated_at desc limit ?""", [limit])

    def set_title(self, cid, title):
        self._q("UPDATE conversations SET title = ? WHERE id = ? AND title = 'New conversation'", [title[:80], cid])

    def conversation_exists(self, cid):
        return bool(self._q("SELECT 1 FROM conversations WHERE id = ?", [cid]))

    def add_message(self, cid, message: dict):
        seq = self._q("SELECT coalesce(max(seq), 0) + 1 AS n FROM messages WHERE conversation_id = ?", [cid])[0]["n"]
        self._q("INSERT INTO messages VALUES (?, ?, ?, ?, ?)", [cid, seq, message["role"], json.dumps(message), now()])

    def messages(self, cid):
        rows = self._q("SELECT payload FROM messages WHERE conversation_id = ? ORDER BY seq", [cid])
        return [json.loads(r["payload"]) for r in rows]

    def record_turn(self, cid, model, steps, prompt_tokens, completion_tokens, stopped_reason, started_at):
        self._q("INSERT INTO turns VALUES (?,?,?,?,?,?,?,?,?)",
                [uuid.uuid4().hex[:12], cid, model, steps, prompt_tokens, completion_tokens, stopped_reason,
                 started_at, now()])

    # actions: proposals, decisions, audit
    def propose(self, cid, kind, target_id, payload, preview):
        aid = uuid.uuid4().hex[:10]
        self._q("INSERT INTO actions VALUES (?,?,?,?,?,?, 'pending', ?, NULL, NULL)",
                [aid, cid, kind, target_id, json.dumps(payload), preview, now()])
        self._audit(aid, "proposed", "assistant", None, "pending", preview)
        return aid

    def _supersede_duplicates(self):
        """Pending cards raised twice for the same thing (before the cross-conversation check): keep the oldest."""
        dupes = self._q("""SELECT id FROM (SELECT id, row_number() OVER (PARTITION BY kind, target_id ORDER BY created_at, id) AS n
                                          FROM actions WHERE status = 'pending') WHERE n > 1""")
        for r in dupes:
            self._q("UPDATE actions SET status = 'superseded', decided_at = ? WHERE id = ?", [now(), r["id"]])
            self._audit(r["id"], "superseded", "system", "pending", "superseded", "duplicate of an older pending card")

    def action(self, aid):
        rows = self._q("SELECT * FROM actions WHERE id = ?", [aid])
        return rows[0] if rows else None

    def actions(self, status=None, cid=None):
        sql, params = "SELECT * FROM actions WHERE 1=1", []
        if status:
            sql += " AND status = ?"; params.append(status)
        if cid:
            sql += " AND conversation_id = ?"; params.append(cid)
        return self._q(sql + " ORDER BY created_at", params)

    def decide(self, aid, new_status, note=None):
        """approved / rejected from pending; reverted from approved. Anything else is refused."""
        a = self.action(aid)
        if a is None:
            raise KeyError(aid)
        allowed = {"pending": {"approved", "rejected"}, "approved": {"reverted"}}
        if new_status not in allowed.get(a["status"], set()):
            raise ValueError(f"cannot move action {aid} from {a['status']} to {new_status}")
        self._q("UPDATE actions SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?", [new_status, now(), USER, aid])
        self._audit(aid, {"approved": "approved", "rejected": "rejected", "reverted": "undone"}[new_status],
                    USER, a["status"], new_status, note)
        return self.action(aid)

    # deals (deal desk)
    def save_deal(self, customer, payload, evaluation):
        n = self._q("SELECT count(*) AS n FROM deals")[0]["n"] + 1
        did = f"Q-{now():%Y%m}-{n:04d}"
        self._q("INSERT INTO deals VALUES (?, ?, ?, ?, ?, NULL, ?)",
                [did, customer, json.dumps(payload), json.dumps(evaluation), evaluation["route"], now()])
        return did

    def link_deal_action(self, did, aid):
        self._q("UPDATE deals SET action_id = ? WHERE id = ?", [aid, did])

    def deals(self):
        rows = self._q("""SELECT d.id, d.customer, d.route, d.created_at, d.evaluation, a.status AS approval_status,
                                 a.decided_at, date_diff('minute', d.created_at, coalesce(a.decided_at, d.created_at)) AS cycle_minutes
                          FROM deals d LEFT JOIN actions a ON a.id = d.action_id ORDER BY d.created_at DESC""")
        for r in rows:
            r["evaluation"] = json.loads(r["evaluation"]) if isinstance(r["evaluation"], str) else r["evaluation"]
        return rows

    def deal(self, did):
        rows = [r for r in self.deals() if r["id"] == did]
        return rows[0] if rows else None

    def audit(self, aid=None):
        if aid:
            return self._q("SELECT * FROM audit_log WHERE action_id = ? ORDER BY seq", [aid])
        return self._q("SELECT * FROM audit_log ORDER BY seq DESC LIMIT 200")

    def _audit(self, aid, event, actor, before, after, note):
        self._q("INSERT INTO audit_log (id, action_id, event, actor, occurred_at, before_status, after_status, note) "
                "VALUES (?,?,?,?,?,?,?,?)",
                [uuid.uuid4().hex[:12], aid, event, actor, now(), before, after, note])
