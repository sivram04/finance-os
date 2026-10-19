"""Alert delivery (design §11, FR-13): de-duplicated, logged, acknowledged.

    python -m finance_os.alerts [--dry-run]

Reads every alert condition true now (marts.fct_alerts), compares with the alert log (data/alerts.duckdb):
  - a key not seen before is logged as open and goes into today's digest;
  - a key still present is left alone (no repeat pings), acknowledged ones stay quiet;
  - a key that dropped out is marked resolved (listed under "resolved" in the digest).
The digest is one message per run, high severity first, each line linking to its workspace page. Channels are
whatever is configured in .env (any combination):
  SLACK_WEBHOOK_URL                                   Slack incoming webhook
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID                Telegram bot
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_FROM, ALERT_EMAIL_TO   email
With none configured (or --dry-run) the digest is written to data/live/alerts_outbox.md and nothing is sent.
APP_URL (default http://localhost:5173) is the base for page links.
"""
import argparse
import json
import os
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import duckdb

from finance_os.ingestion.ap_intake.__main__ import load_dotenv
from finance_os.paths import ROOT

WAREHOUSE = ROOT / "data" / "finance_os.duckdb"
LOG_DB = ROOT / "data" / "alerts.duckdb"
OUTBOX = ROOT / "data" / "live" / "alerts_outbox.md"
COLUMNS = ["alert_key", "rule_id", "severity", "entity_id", "period", "message", "recipients", "page"]


def _log():
    con = duckdb.connect(str(LOG_DB))
    con.execute("""create table if not exists alert_log (
        alert_key varchar primary key, rule_id varchar, severity varchar, entity_id varchar, period date,
        message varchar, recipients varchar, page varchar, status varchar, first_seen timestamp, last_seen timestamp,
        sent_at timestamp, channels varchar, acknowledged_at timestamp, acknowledged_by varchar, resolved_at timestamp)""")
    return con


def current_alerts():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    try:
        return [dict(zip(COLUMNS, r)) for r in con.execute(f"select {', '.join(COLUMNS)} from marts.fct_alerts").fetchall()]
    finally:
        con.close()


def reconcile(alerts, now=None):
    """Update the log; returns (new, resolved) alert dicts."""
    now = now or datetime.now()
    con = _log()
    try:
        known = {r[0]: r[1] for r in con.execute("select alert_key, status from alert_log").fetchall()}
        keys = {a["alert_key"] for a in alerts}
        new = []
        for a in alerts:
            if a["alert_key"] not in known or known[a["alert_key"]] == "resolved":
                con.execute("delete from alert_log where alert_key = ?", [a["alert_key"]])
                con.execute("insert into alert_log (alert_key, rule_id, severity, entity_id, period, message, recipients, page,"
                            " status, first_seen, last_seen) values (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                            [*(a[c] for c in COLUMNS), now, now])
                new.append(a)
            else:
                con.execute("update alert_log set last_seen = ?, message = ? where alert_key = ?", [now, a["message"], a["alert_key"]])
        resolved = []
        for key, status in known.items():
            if key not in keys and status in ("open", "acknowledged"):
                con.execute("update alert_log set status = 'resolved', resolved_at = ? where alert_key = ?", [now, key])
                row = con.execute(f"select {', '.join(COLUMNS)} from alert_log where alert_key = ?", [key]).fetchone()
                resolved.append(dict(zip(COLUMNS, row)))
        return new, resolved
    finally:
        con.close()


def digest(new, resolved, app_url):
    if not new and not resolved:
        return None
    order = {"high": 0, "medium": 1, "low": 2}
    lines = [f"Finance OS alerts — {datetime.now():%a %d %b %Y}", ""]
    if new:
        lines.append(f"{len(new)} new:")
        for a in sorted(new, key=lambda a: (order.get(a["severity"], 9), a["rule_id"])):
            lines.append(f"  [{a['severity'].upper()}] {a['message']}  → {a['recipients']}  {app_url}/#{a['page']}")
    if resolved:
        lines += ["", f"{len(resolved)} resolved:"] + [f"  ✓ {a['message']}" for a in resolved]
    return "\n".join(lines)


def send(text, log=print):
    """Deliver to every configured channel; returns the list of channels used."""
    used = []
    if os.environ.get("SLACK_WEBHOOK_URL"):
        req = urllib.request.Request(os.environ["SLACK_WEBHOOK_URL"], data=json.dumps({"text": text}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        used.append("slack")
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        url = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage"
        req = urllib.request.Request(url, data=json.dumps({"chat_id": os.environ["TELEGRAM_CHAT_ID"], "text": text,
                                                           "disable_web_page_preview": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20).read()
        used.append("telegram")
    if os.environ.get("SMTP_HOST") and os.environ.get("ALERT_EMAIL_TO"):
        msg = EmailMessage()
        msg["Subject"] = text.splitlines()[0]
        msg["From"] = os.environ.get("ALERT_EMAIL_FROM", os.environ.get("SMTP_USER", "finance-os@localhost"))
        msg["To"] = os.environ["ALERT_EMAIL_TO"]
        msg.set_content(text)
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
            s.send_message(msg)
        used.append("email")
    return used


def run(dry_run=False, log=print):
    load_dotenv(ROOT / ".env")
    new, resolved = reconcile(current_alerts())
    text = digest(new, resolved, os.environ.get("APP_URL", "http://localhost:5173"))
    if not text:
        log("alerts: nothing new")
        return {"new": 0, "resolved": 0, "channels": []}
    channels = [] if dry_run else send(text, log)
    if not channels:
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        with open(OUTBOX, "a", encoding="utf-8") as f:
            f.write(text + "\n\n")
    con = _log()
    try:
        con.execute("update alert_log set sent_at = ?, channels = ? where sent_at is null and status = 'open'",
                    [datetime.now(), ",".join(channels) or "outbox"])
    finally:
        con.close()
    log(f"alerts: {len(new)} new, {len(resolved)} resolved -> {', '.join(channels) or f'outbox ({OUTBOX.name})'}")
    return {"new": len(new), "resolved": len(resolved), "channels": channels}


def acknowledge(alert_key, who="finance"):
    con = _log()
    try:
        n = con.execute("update alert_log set status = 'acknowledged', acknowledged_at = ?, acknowledged_by = ? "
                        "where alert_key = ? and status = 'open' returning alert_key", [datetime.now(), who, alert_key]).fetchall()
        return bool(n)
    finally:
        con.close()


def list_alerts(status=None):
    con = _log()
    try:
        sql = "select * from alert_log" + (" where status = ?" if status else "") + \
              " order by case severity when 'high' then 0 else 1 end, first_seen desc"
        cur = con.execute(sql, [status] if status else [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="write the digest to the outbox; send nothing")
    a = p.parse_args()
    run(a.dry_run)


if __name__ == "__main__":
    main()
