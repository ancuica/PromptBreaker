"""Optional debug tracer for OpenAI chat-completion calls.

Wraps `client.chat.completions.create` so each call prints a one-line summary
to stdout. Useful when running `python app.py` to confirm the API is actually
being hit and to see token usage per request.

Enable by setting PROMPTBREAKER_TRACE=1 in the environment (or .env).
"""

from __future__ import annotations

import itertools
import sys
import time
from threading import Lock

# Cheap heuristic: classify a call by the start of its system prompt.
def _role_for(messages: list[dict]) -> str:
    if not messages:
        return "?"
    sys_content = (messages[0].get("content") or "").lower()
    if "promptbreaker" in sys_content or "offensive security" in sys_content:
        return "ATTACKER"
    if "impartial judge" in sys_content:
        return "JUDGE   "
    return "DEFENDER"


def install_tracer(client) -> None:
    """Monkey-patch `client.chat.completions.create` to log every call."""
    original = client.chat.completions.create
    counter = itertools.count(1)
    totals = {"calls": 0, "tokens_in": 0, "tokens_out": 0}
    lock = Lock()

    def traced(**kwargs):
        n = next(counter)
        role = _role_for(kwargs.get("messages", []))
        model = kwargs.get("model", "?")
        t0 = time.time()
        try:
            resp = original(**kwargs)
        except Exception as e:  # noqa: BLE001
            dt = time.time() - t0
            with lock:
                print(
                    f"[openai] #{n:03d} {role} {model} FAILED in {dt:5.2f}s — {str(e)[:80]}",
                    file=sys.stderr,
                    flush=True,
                )
            raise

        dt = time.time() - t0
        usage = getattr(resp, "usage", None)
        tin = getattr(usage, "prompt_tokens", 0) if usage else 0
        tout = getattr(usage, "completion_tokens", 0) if usage else 0

        with lock:
            totals["calls"] += 1
            totals["tokens_in"] += tin
            totals["tokens_out"] += tout
            print(
                f"[openai] #{n:03d} {role} {model} {dt:5.2f}s  "
                f"in={tin:>4}  out={tout:>4}  "
                f"(session: {totals['calls']} calls, "
                f"{totals['tokens_in']} in / {totals['tokens_out']} out)",
                file=sys.stderr,
                flush=True,
            )
        return resp

    client.chat.completions.create = traced
