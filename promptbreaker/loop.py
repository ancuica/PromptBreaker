"""The adversarial loop that ties Attacker, Defender, and Judge together.

This is the heart of the "beyond Project 4" pattern: a single extraction call
cannot find injection vulnerabilities, because if the first payload bounces
off the system prompt you have nothing. Here we run up to N turns, feeding
the Defender's refusal back into the Attacker so it can analyze and pivot.
"""

from __future__ import annotations

from typing import Callable, Iterator, Optional

from openai import OpenAI

from .attacker import run_attacker
from .defender import run_defender
from .judge import judge_response
from .schemas import RunResult, TurnLog

DEFAULT_MAX_TURNS = 5


def run_attack_loop(
    client: OpenAI,
    defender_prompt: str,
    secret: str,
    *,
    attacker_model: str = "gpt-4o-mini",
    defender_model: str = "gpt-4o-mini",
    judge_model: str = "gpt-4o-mini",
    max_turns: int = DEFAULT_MAX_TURNS,
    on_turn: Optional[Callable[[TurnLog], None]] = None,
) -> RunResult:
    """Run a full attack against `defender_prompt`, stopping early on success.

    `on_turn` is an optional callback fired after every turn — used by the web
    UI to stream progress to the browser via SSE.
    """
    turns: list[TurnLog] = []

    for turn_idx in range(1, max_turns + 1):
        move = run_attacker(
            client=client,
            model=attacker_model,
            defender_system_prompt=defender_prompt,
            prior_turns=turns,
        )

        defender_reply = run_defender(
            client=client,
            model=defender_model,
            defender_system_prompt=defender_prompt,
            attacker_payload=move.payload,
        )

        verdict = judge_response(
            client=client,
            model=judge_model,
            secret=secret,
            response=defender_reply,
        )

        log = TurnLog(
            turn=turn_idx,
            attacker_move=move,
            defender_response=defender_reply,
            secret_revealed=verdict.revealed,
            judge_reason=verdict.reason,
        )
        turns.append(log)

        if on_turn is not None:
            on_turn(log)

        if verdict.revealed:
            return RunResult(
                defender_prompt=defender_prompt,
                secret=secret,
                max_turns=max_turns,
                success=True,
                turns_used=turn_idx,
                winning_payload=move.payload,
                turns=turns,
            )

    return RunResult(
        defender_prompt=defender_prompt,
        secret=secret,
        max_turns=max_turns,
        success=False,
        turns_used=max_turns,
        winning_payload=None,
        turns=turns,
    )


def iter_attack_loop(
    client: OpenAI,
    defender_prompt: str,
    secret: str,
    **kwargs,
) -> Iterator[TurnLog | RunResult]:
    """Generator wrapper: yields each TurnLog as it happens, then a final RunResult.

    Useful for the Flask SSE endpoint which needs to push updates incrementally.
    """
    collected: list[TurnLog] = []

    def _collect(log: TurnLog) -> None:
        collected.append(log)

    # We can't easily make run_attack_loop a true generator without rewriting
    # it, so we use a callback-driven buffer. For streaming we instead inline
    # the loop here.
    from .attacker import run_attacker  # local imports keep this module light
    from .defender import run_defender
    from .judge import judge_response

    attacker_model = kwargs.get("attacker_model", "gpt-4o-mini")
    defender_model = kwargs.get("defender_model", "gpt-4o-mini")
    judge_model = kwargs.get("judge_model", "gpt-4o-mini")
    max_turns = kwargs.get("max_turns", DEFAULT_MAX_TURNS)

    turns: list[TurnLog] = []
    for turn_idx in range(1, max_turns + 1):
        move = run_attacker(client, attacker_model, defender_prompt, turns)
        defender_reply = run_defender(client, defender_model, defender_prompt, move.payload)
        verdict = judge_response(client, judge_model, secret, defender_reply)

        log = TurnLog(
            turn=turn_idx,
            attacker_move=move,
            defender_response=defender_reply,
            secret_revealed=verdict.revealed,
            judge_reason=verdict.reason,
        )
        turns.append(log)
        yield log

        if verdict.revealed:
            yield RunResult(
                defender_prompt=defender_prompt,
                secret=secret,
                max_turns=max_turns,
                success=True,
                turns_used=turn_idx,
                winning_payload=move.payload,
                turns=turns,
            )
            return

    yield RunResult(
        defender_prompt=defender_prompt,
        secret=secret,
        max_turns=max_turns,
        success=False,
        turns_used=max_turns,
        winning_payload=None,
        turns=turns,
    )
