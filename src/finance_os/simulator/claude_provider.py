"""Claude Code as the simulator's decision-maker, run headless (`claude -p`) under the user's Claude plan.

The briefing goes in on stdin. Claude may search the company's memory, and nothing else: the only tool it is
allowed is the memory-search command (`python -m finance_os.simulator.memory search ...`), so a scheduled run
cannot edit files or run anything else. It answers with the day's events as JSON, which then go through the
same validation as any other provider's.
"""
import json
import os
import shutil
import subprocess

from finance_os.paths import ROOT
from finance_os.simulator import agent

SEARCH_CMD = "python -m finance_os.simulator.memory search"

INSTRUCTIONS = f"""

## How to work
You may look things up before deciding, with this command (and only this one):
  {SEARCH_CMD} "<what you want to know>" [--customer ID] [--type EVENT_TYPE] [--kind decision|daily|monthly|history] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
It prints matching memory chunks as JSON. Use at most 3 searches, then answer.

## Answer
Reply with ONLY a JSON object, no prose and no code fence:
{{"events": [{{"type": ..., "customer_id": ..., "segment": ..., "products": ..., "size": ..., "multiplier": ...,
  "days": ..., "invoice_ref": ..., "pct": ..., "contract_id": ..., "milestone_name": ..., "vendor_id": ...,
  "category": ..., "reason": ...}}]}}
Every event has every key; use null where a key does not apply. An empty list is a valid quiet day.
"""


def _claude():
    path = os.environ.get("SIM_CLAUDE_PATH") or shutil.which("claude")
    if not path:
        raise RuntimeError("Claude Code CLI not found (install it or set SIM_CLAUDE_PATH)")
    return path


def _json_object(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"no JSON object in Claude's answer: {text[:200]!r}")
    return text[start:end + 1]


def decide(summary, tools=None, timeout=600):
    """Returns (events, usage) like agent.decide. `tools` is unused: Claude searches memory via the CLI."""
    briefing = agent.PROMPT + "\n\n## Today's state\n" + json.dumps(summary, default=str) + INSTRUCTIONS
    # A clean environment, as in a terminal: drop the variables a parent Claude Code session (the desktop app)
    # sets for its own children, so the CLI uses the user's own terminal sign-in.
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC") or k == "CLAUDECODE")}
    env["PATH"] = str(ROOT / ".venv" / "Scripts") + os.pathsep + os.environ.get("PATH", "")
    cmd = [_claude(), "-p", "Decide today's events for the company described on stdin.",
           "--output-format", "json", "--max-turns", "5",
           "--model", os.environ.get("SIM_CLAUDE_MODEL", "sonnet"),
           "--allowedTools", f"Bash({SEARCH_CMD}:*)",
           "--disallowedTools", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
    run = subprocess.run(cmd, input=briefing, capture_output=True, text=True, encoding="utf-8",
                         cwd=ROOT, env=env, timeout=timeout)
    if run.returncode != 0:
        raise RuntimeError(f"claude exited {run.returncode}: {(run.stderr or run.stdout)[-400:]}")
    result = json.loads(run.stdout)
    if result.get("is_error"):
        raise RuntimeError(f"claude reported an error: {result.get('result', '')[:400]}")
    events = agent._events(_json_object(result["result"]))
    usage = {"model": "claude-code/" + os.environ.get("SIM_CLAUDE_MODEL", "sonnet"),
             "total_tokens": sum(v for k, v in (result.get("usage") or {}).items() if k.endswith("tokens") and isinstance(v, int)),
             "num_turns": result.get("num_turns"), "cost_usd_equivalent": result.get("total_cost_usd"), "tool_calls": []}
    return events, usage
