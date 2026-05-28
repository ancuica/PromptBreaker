"""Run the PromptBreaker eval suite.

Usage:
    python eval/run_eval.py
    python eval/run_eval.py --max-turns 5 --cases eval/test_cases.json

Computes ATTACK_SUCCESS_RATE = (# defender prompts cracked within max_turns)
                              / (# defender prompts tested).

Writes a per-case JSON log to eval/eval_results.json so REPORT.md can cite
exact failing cases for the Motivating example field of each iteration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Allow `python eval/run_eval.py` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from openai import OpenAI

from promptbreaker.loop import run_attack_loop

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PromptBreaker eval suite.")
    parser.add_argument("--cases", default="eval/test_cases.json",
                        help="Path to JSON test cases file.")
    parser.add_argument("--max-turns", type=int, default=5,
                        help="Max attacker turns per case (default: 5).")
    parser.add_argument("--model", default=os.getenv("PROMPTBREAKER_MODEL", "gpt-4o-mini"),
                        help="OpenAI model to use for Attacker/Defender/Judge.")
    parser.add_argument("--out", default="eval/eval_results.json",
                        help="Where to write the per-case JSON log.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Optional: only run the first N cases (for smoke tests).")
    args = parser.parse_args()

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY is not set. Add it to .env.", file=sys.stderr)
        return 1

    cases = json.loads(Path(args.cases).read_text())
    if args.limit:
        cases = cases[: args.limit]

    client = OpenAI(api_key=key)

    per_case_results = []
    successes = 0
    t_start = time.time()

    for i, case in enumerate(cases, start=1):
        print(f"[{i}/{len(cases)}] {case['id']} ... ", end="", flush=True)
        case_start = time.time()
        try:
            result = run_attack_loop(
                client=client,
                defender_prompt=case["defender_prompt"],
                secret=case["secret"],
                attacker_model=args.model,
                defender_model=args.model,
                judge_model=args.model,
                max_turns=args.max_turns,
            )
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: {e}")
            per_case_results.append({
                "id": case["id"],
                "success": False,
                "error": str(e),
            })
            continue

        elapsed = time.time() - case_start
        if result.success:
            successes += 1
            print(f"SUCCESS in {result.turns_used} turn(s) ({elapsed:.1f}s)")
        else:
            print(f"defender survived {args.max_turns} turn(s) ({elapsed:.1f}s)")

        per_case_results.append({
            "id": case["id"],
            "description": case.get("description", ""),
            "expected_outcome": case.get("expected_outcome", ""),
            "success": result.success,
            "turns_used": result.turns_used,
            "max_turns": result.max_turns,
            "winning_payload": result.winning_payload,
            "winning_strategy": (
                result.turns[result.turns_used - 1].attacker_move.new_strategy
                if result.success and result.turns else None
            ),
            "strategies_tried": [t.attacker_move.new_strategy for t in result.turns],
            "final_defender_response": (
                result.turns[-1].defender_response if result.turns else ""
            ),
        })

    total = len(cases)
    rate = successes / total if total else 0.0
    elapsed_total = time.time() - t_start

    summary = {
        "model": args.model,
        "max_turns": args.max_turns,
        "n_cases": total,
        "n_success": successes,
        "attack_success_rate": rate,
        "elapsed_seconds": round(elapsed_total, 1),
        "cases": per_case_results,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 60)
    print(f"ATTACK_SUCCESS_RATE = {successes}/{total} = {rate:.2%}")
    print(f"Total time: {elapsed_total:.1f}s")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
