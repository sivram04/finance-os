"""The assistant's agent loop (design §9.2, §9.5).

plan → call a tool → read the result → … → answer, yielding an event for every step so the UI can show it.
Read tools run freely; propose_* tools only record pending actions. The final answer goes through the number
validator; if it quotes numbers no tool returned, the model gets one retry, and anything still unverified is
flagged on the answer. Steps and input tokens per turn are capped.

A second code check: if the model answers without calling any tool this turn, it gets one retry telling it to
check the data first (out-of-scope questions just repeat their refusal). Both checks are code, not prompts.

The model is called through OpenAI's Chat Completions HTTP API. `complete` is injectable, so tests run the
whole loop with a scripted fake model and no network.
"""
import json
import os
import time

import httpx

from finance_os.app import actions as act
from finance_os.app import tools
from finance_os.app.documents import Documents
from finance_os.app.state import AppState, now
from finance_os.app.validator import unverified_numbers

MAX_STEPS = 12
MAX_INPUT_TOKENS = 60_000

SYSTEM = """You are the Finance OS assistant for Echo Labs, a voice-AI API company. You help the finance team \
(VP Finance, controller, AP and AR specialists, project managers) understand and act on their numbers.

How you work:
- Use tools to get every fact, including definitions (get_metric_definition). Never answer from general knowledge. Plan briefly, call the tools you need (several if useful), then answer.
- A question naming a metric ("What is ARR?", "What's DSO?") asks for Echo Labs' current value: give the number first, then one line on what it means.
- For counts, use the count fields tools return; don't count rows yourself.
- Every number you write must be copied from a tool result. Never compute, add, subtract, average or estimate a \
number yourself; if a figure you want isn't returned by a tool, say what the tools do show instead. You may \
round (e.g. $30.3K, 46.4%).
- Cite where numbers come from by naming the source table in a short "Sources:" line at the end.
- Reconciliation status for this data is given below. If a check relevant to the question is failing, say the \
number is not trusted and why.
- When the user uploads a document, call get_uploaded_document with its id, report what was read and every issue the checks found, and always finish by calling propose_ap_document_decision for it: approve when there are no issues, reject when there is any issue (the reason names the issue). The user can still reject your proposal.
- To change anything (approve or reject a vendor bill or a reminder, fix a cash application) call a propose_* \
tool. That only creates an approval card for the user; never claim something was approved, sent or fixed.
- Keep answers short and concrete: lead with the answer, then the key drivers, as a short list or small table.
- Decline investment, legal or tax advice, and anything outside Echo Labs' finance data.

Data runs through {as_of}. Reconciliation: {recon}."""


def openai_complete(messages, tool_specs, model):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set (put it in .env)")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    r = httpx.post(f"{base}/chat/completions", timeout=120,
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "temperature": 0, "messages": messages, "tools": tool_specs})
    r.raise_for_status()
    return r.json()


VALIDATOR_PREFIX = "Validator:"


def is_internal(message):
    """Validator retry notes are sent to the model as user messages but are not the user's words."""
    return message["role"] == "user" and str(message.get("content", "")).startswith(VALIDATOR_PREFIX)


UPLOAD_SPEC = {"type": "function", "function": {
    "name": "get_uploaded_document",
    "description": "A document the user uploaded in the chat (id UP-…): the fields read from it (text or OCR), "
                   "and the control checks run against POs and the ledger.",
    "parameters": {"type": "object", "properties": {"document_id": {"type": "string"}}, "required": ["document_id"],
                   "additionalProperties": False}}}


def default_model():
    return os.environ.get("OPENAI_ASSISTANT_MODEL", "gpt-4.1")


class Agent:
    def __init__(self, state: AppState, wh: tools.Warehouse | None = None, complete=openai_complete, model=None):
        self.state, self.wh, self.complete = state, wh or tools.Warehouse(), complete
        self.model = model or default_model()

    def _system(self):
        as_of = self.wh.query("select max(entry_date) as d from staging.stg_erp__journal_entries")[0]["d"]
        r = tools.get_reconciliation_status(self.wh)
        if r["all_passing"]:
            recon = f"all {sum(x['periods'] for x in r['rows'])} check-periods passing"
        else:
            recon = "FAILING: " + "; ".join(f"{x['check_name']} {x['failing']} periods" for x in r["rows"] if x["failing"])
        return SYSTEM.format(as_of=as_of, recon=recon)

    def _history(self, cid):
        """Earlier turns are kept, but old tool results are shortened to keep the prompt small."""
        msgs = self.state.messages(cid)
        last_user = max((i for i, m in enumerate(msgs) if m["role"] == "user" and not is_internal(m)), default=-1)
        out = []
        for i, m in enumerate(msgs):
            if m["role"] == "tool" and i < last_user:
                m = {**m, "content": '{"note": "earlier result omitted; call the tool again if needed"}'}
            out.append(m)
        return out

    def run(self, cid, user_text):
        """Generator of events: step, tool_result, proposal, answer, error, done."""
        started, steps, p_tok, c_tok, stopped = now(), 0, 0, 0, "answered"
        self.state.add_message(cid, {"role": "user", "content": user_text})
        self.state.set_title(cid, user_text.strip().splitlines()[0])
        specs = tools.openai_tool_specs(act.action_specs() + [UPLOAD_SPEC])
        turn_results = []
        retried = False
        grounding_retried = False
        try:
            while True:
                if steps >= MAX_STEPS:
                    stopped = "step_limit"
                    yield {"type": "error", "message": f"Stopped after {MAX_STEPS} tool steps."}
                    break
                if p_tok >= MAX_INPUT_TOKENS:
                    stopped = "token_limit"
                    yield {"type": "error", "message": "Stopped: this turn reached its token budget."}
                    break
                messages = [{"role": "system", "content": self._system()}] + self._history(cid)
                resp = self.complete(messages, specs, self.model)
                usage = resp.get("usage", {})
                p_tok += usage.get("prompt_tokens", 0)
                c_tok += usage.get("completion_tokens", 0)
                msg = resp["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                stored = {"role": "assistant", "content": msg.get("content")}
                if calls:
                    stored["tool_calls"] = calls
                self.state.add_message(cid, stored)

                if calls:
                    for call in calls:
                        steps += 1
                        name = call["function"]["name"]
                        try:
                            args = json.loads(call["function"]["arguments"] or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        yield {"type": "step", "tool": name, "args": args}
                        t0 = time.perf_counter()
                        result = self._call(cid, name, args)
                        turn_results.append(result)
                        self.state.add_message(cid, {"role": "tool", "tool_call_id": call["id"],
                                                     "content": json.dumps(result, default=str)})
                        event = {"type": "tool_result", "tool": name, "ms": round((time.perf_counter() - t0) * 1000),
                                 "source": result.get("source"), "rows": result.get("row_count"),
                                 "error": result.get("error")}
                        yield event
                        if "proposed_action_id" in result:
                            yield {"type": "proposal", "action": self.state.action(result["proposed_action_id"])}
                    continue

                text = msg.get("content") or ""
                if steps == 0 and not grounding_retried:
                    grounding_retried = True
                    self.state.add_message(cid, {"role": "user", "content": (
                        f"{VALIDATOR_PREFIX} you answered without calling any tool. If the question is about Echo "
                        "Labs' data or definitions, call the relevant tools and answer from their results. If it is "
                        "out of scope, repeat your refusal. Do not mention this check.")})
                    yield {"type": "validator_retry", "reason": "no_tools"}
                    continue
                bad = unverified_numbers(text, turn_results)
                if bad and not retried:
                    retried = True
                    self.state.add_message(cid, {"role": "user", "content": (
                        f"{VALIDATOR_PREFIX} these numbers in your answer do not appear in any tool result: "
                        f"{', '.join(bad)}. Rewrite the answer using only numbers returned by tools "
                        "(call more tools if needed). Do not mention this check.")})
                    yield {"type": "validator_retry", "reason": "unverified_numbers", "unverified": bad}
                    continue
                yield {"type": "answer", "text": text, "unverified_numbers": bad}
                break
        except Exception as e:  # surface model/network errors to the UI instead of dying silently
            stopped = "error"
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
        finally:
            self.state.record_turn(cid, self.model, steps, p_tok, c_tok, stopped, started)
        yield {"type": "done", "steps": steps, "prompt_tokens": p_tok, "completion_tokens": c_tok, "stopped": stopped}

    def _call(self, cid, name, args):
        try:
            if name == "get_uploaded_document":
                doc = Documents(self.state, self.wh).get(args.get("document_id", ""))
                if not doc:
                    return {"error": f"No uploaded document {args.get('document_id')}."}
                return {k: v for k, v in doc.items() if k != "path"}
            if name in tools.TOOLS:
                return tools.run_tool(self.wh, name, args)
            if name in act.ACTIONS:
                return act.ACTIONS[name][0](self.wh, self.state, cid, **args)
            return {"error": f"Unknown tool {name}"}
        except TypeError as e:
            return {"error": f"Bad arguments for {name}: {e}"}
        except Exception as e:
            return {"error": f"{name} failed: {type(e).__name__}: {e}"}
