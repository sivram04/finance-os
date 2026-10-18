"""Rebuild a stored conversation into the same event stream the UI renders live, so a reloaded chat looks
exactly like it did: steps with their sources, approval cards with their *current* status, the answer and
its unverified numbers (re-checked by the validator), and the turn's usage."""
import json
import re

from finance_os.app.agent import is_internal
from finance_os.app.documents import Documents
from finance_os.app.state import AppState
from finance_os.app.validator import unverified_numbers


def replay(state: AppState, cid):
    messages = state.messages(cid)
    actions = {a["id"]: a for a in state.actions(cid=cid)}
    usage = state._q("""select steps, prompt_tokens, completion_tokens, stopped_reason from turns
                        where conversation_id = ? order by started_at""", [cid])
    docs = Documents(state, wh=None)
    turns, current, results = [], None, []
    for m in messages:
        if m["role"] == "user" and not is_internal(m):
            current = {"text": m["content"], "events": []}
            uploaded = re.search(r"document id (UP-[0-9A-F]{8})", m["content"])
            if uploaded and (doc := docs.get(uploaded.group(1))):
                current["doc"] = {k: v for k, v in doc.items() if k != "path"}
            results = []
            turns.append(current)
        elif current is None or (m["role"] == "user"):
            continue  # validator notes are not shown
        elif m["role"] == "assistant" and m.get("tool_calls"):
            for c in m["tool_calls"]:
                current["events"].append({"type": "step", "tool": c["function"]["name"],
                                          "args": json.loads(c["function"]["arguments"] or "{}")})
        elif m["role"] == "tool":
            try:
                result = json.loads(m["content"])
            except json.JSONDecodeError:
                result = {}
            results.append(result)
            step = next((e for e in reversed(current["events"]) if e["type"] == "step"), {})
            current["events"].append({"type": "tool_result", "tool": step.get("tool"), "ms": None,
                                      "source": result.get("source"), "rows": result.get("row_count"),
                                      "error": result.get("error")})
            aid = result.get("proposed_action_id")
            if aid in actions:
                current["events"].append({"type": "proposal", "action": actions[aid]})
        elif m["role"] == "assistant" and m.get("content"):
            # keep only the final answer of the turn (an earlier one may have been sent back by the validator)
            current["events"] = [e for e in current["events"] if e["type"] != "answer"]
            current["events"].append({"type": "answer", "text": m["content"],
                                      "unverified_numbers": unverified_numbers(m["content"], results)})
    for turn, u in zip(turns, usage):
        turn["events"].append({"type": "done", "steps": u["steps"], "prompt_tokens": u["prompt_tokens"],
                               "completion_tokens": u["completion_tokens"], "stopped": u["stopped_reason"]})
    return turns
