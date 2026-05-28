"""Flask server for PromptBreaker.

Routes:
  GET  /              -> single-page UI
  POST /api/attack    -> Server-Sent Events stream of TurnLogs + final RunResult
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from flask import Flask, Response, render_template, request, stream_with_context
from openai import OpenAI

from promptbreaker.loop import DEFAULT_MAX_TURNS, iter_attack_loop
from promptbreaker.schemas import RunResult, TurnLog
from promptbreaker.tracer import install_tracer

load_dotenv()

DEFAULT_MODEL = os.getenv("PROMPTBREAKER_MODEL", "gpt-4o-mini")
# Set PROMPTBREAKER_TRACE=1 in .env to print every OpenAI call to the terminal.
TRACE_ENABLED = os.getenv("PROMPTBREAKER_TRACE", "1") not in ("0", "", "false", "False")

app = Flask(__name__, static_folder="static", template_folder="templates")


def _get_client() -> OpenAI | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    client = OpenAI(api_key=key)
    if TRACE_ENABLED:
        install_tracer(client)
    return client


@app.route("/")
def index():
    return render_template("index.html", default_max_turns=DEFAULT_MAX_TURNS)


@app.route("/api/attack", methods=["POST"])
def api_attack():
    """Run an attack loop and stream each turn back to the browser via SSE."""
    payload = request.get_json(silent=True) or {}
    defender_prompt = (payload.get("defender_prompt") or "").strip()
    secret = (payload.get("secret") or "").strip()
    try:
        max_turns = int(payload.get("max_turns") or DEFAULT_MAX_TURNS)
    except (TypeError, ValueError):
        max_turns = DEFAULT_MAX_TURNS
    max_turns = max(1, min(max_turns, 10))  # clamp for cost safety

    # Input validation. We return a one-shot SSE error event so the UI can
    # render the failure path without a separate code path.
    def _error_stream(msg: str):
        yield f"event: error\ndata: {json.dumps({'error': msg})}\n\n"

    if not defender_prompt:
        return Response(_error_stream("Defender system prompt is required."),
                        mimetype="text/event-stream")
    if not secret:
        return Response(_error_stream("Secret string is required."),
                        mimetype="text/event-stream")
    if secret.lower() not in defender_prompt.lower():
        return Response(
            _error_stream("The secret must appear inside the defender prompt — otherwise the defender can't leak it."),
            mimetype="text/event-stream",
        )

    client = _get_client()
    if client is None:
        return Response(
            _error_stream("OPENAI_API_KEY is not set on the server. Add it to .env and restart."),
            mimetype="text/event-stream",
        )

    @stream_with_context
    def generate():
        try:
            for item in iter_attack_loop(
                client=client,
                defender_prompt=defender_prompt,
                secret=secret,
                attacker_model=DEFAULT_MODEL,
                defender_model=DEFAULT_MODEL,
                judge_model=DEFAULT_MODEL,
                max_turns=max_turns,
            ):
                if isinstance(item, TurnLog):
                    yield f"event: turn\ndata: {item.model_dump_json()}\n\n"
                elif isinstance(item, RunResult):
                    yield f"event: result\ndata: {item.model_dump_json()}\n\n"
        except Exception as e:  # noqa: BLE001
            # Surface the failure to the UI instead of dropping the connection.
            yield f"event: error\ndata: {json.dumps({'error': f'Server error: {e!s}'})}\n\n"

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    if TRACE_ENABLED:
        print("[promptbreaker] OpenAI call tracing is ON. "
              "Set PROMPTBREAKER_TRACE=0 in .env to disable.", flush=True)
    # debug=False so the Flask reloader doesn't double-print every trace line.
    app.run(host="127.0.0.1", port=5000, debug=False)
