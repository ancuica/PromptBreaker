# 🔓 PromptBreaker

An automated AI red-teaming web app that pits two LLMs against each other to autonomously discover prompt-injection vulnerabilities in system prompts.

**CPSC 254 Final Project.** Built with Flask + OpenAI.

---

## What it does

You paste in a system prompt that contains a secret string. PromptBreaker spins up two LLMs:

- **Defender** — runs your system prompt and tries to refuse.
- **Attacker** — an autonomous red-teaming agent that produces structured, schema-validated attack moves. After each refusal it analyzes *why* it failed, picks a different strategy category, and tries again.

A judge (hybrid: deterministic substring + transformation checks, fallback to an LLM judge) decides whether the secret actually leaked. The browser streams each turn live via Server-Sent Events.

This goes well beyond a single extraction call: a one-shot script can't find injection vulnerabilities because the first payload usually bounces off any non-trivial system prompt. PromptBreaker keeps state across turns, forces the Attacker into a Pydantic-validated reasoning schema, and tracks already-tried strategies so it pivots instead of looping.

---

## Setup

Tested on macOS, Python 3.11+.

```bash
# 1. Clone and enter the repo
git clone https://github.com/ancuica/PromptBreaker
cd promptbreaker

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Add your OpenAI key
cp .env.example .env
# then edit .env and set OPENAI_API_KEY=sk-...
```

The grader-supplied `.env` containing only `OPENAI_API_KEY` is sufficient. No other API keys, hosted databases, or cloud services are required.

---

## Run the web app

```bash
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

The form is pre-filled with the proposal's Test Case 1 (`DRINK-MORE-MILK`). Click **Launch attack** and watch the turn log stream in.

While the server runs, the terminal prints one line per real OpenAI API call so you can confirm the model is actually being hit. Example:

```
[openai] #001 ATTACKER gpt-4o-mini  2.83s  in= 377  out= 135  (session: 1 calls, 377 in / 135 out)
[openai] #002 DEFENDER gpt-4o-mini  4.41s  in=  55  out=  66  (session: 2 calls, 432 in / 201 out)
[openai] #003 JUDGE    gpt-4o-mini  1.02s  in= 223  out=  22  (session: 3 calls, 655 in / 223 out)
```

Each turn fires 2 guaranteed calls (Attacker + Defender) plus 1 conditional call (Judge) when the fast deterministic check is inconclusive. Disable the trace by setting `PROMPTBREAKER_TRACE=0` in `.env`.

---

## Run the eval suite

The eval suite scores `ATTACK_SUCCESS_RATE` — the fraction of defender prompts whose secret the Attacker extracts within `max_turns` (default 5).

```bash
# Full run (12 test cases, ~3-6 minutes depending on network/model)
python eval/run_eval.py

# Smoke test on the first 3 cases
python eval/run_eval.py --limit 3

# Tune turn budget
python eval/run_eval.py --max-turns 5
```

Output:

- Per-case status printed to stdout.
- Final `ATTACK_SUCCESS_RATE = X/Y = ZZ%` line.
- Full per-case log written to `eval/eval_results.json` (gitignored).

---

## Agentic loop

One turn = one ATK call + one DEF call + (conditionally) one JDG call.
The loop runs until the secret leaks or `max_turns` is exhausted.

```
                      user: defender system prompt + secret
                                       |
                                       v
     +============== adversarial loop  (1 .. max_turns) =================+
     |                                                                  |
     |    +------------------+                                          |
     |    | ATK   attacker   |  reads prior turns + strategies tried,   |
     |    |       (amber)    |  picks a *new* strategy from 10,         |
     |    +------------------+  emits AttackerMove JSON                  |
     |             |                                                    |
     |             |  payload                                            |
     |             v                                                    |
     |    +------------------+                                          |
     |    | DEF   defender   |  stateless single-turn reply              |
     |    |       (cyan)     |  under the user's system prompt           |
     |    +------------------+                                          |
     |             |                                                    |
     |             |  reply text                                         |
     |             v                                                    |
     |    +------------------+                                          |
     |    | JDG   judge      |  fast: substring + reverse + base64;      |
     |    |       (mauve)    |  LLM fallback only if inconclusive        |
     |    +------------------+                                          |
     |             |                                                    |
     |             v                                                    |
     |     secret revealed?  ---yes--->  break, attacker wins            |
     |             |                                                    |
     |             no                                                   |
     |             |                                                    |
     |             v                                                    |
     |       next turn  (attacker now sees this turn in its history)    |
     |                                                                  |
     +==================================================================+
                                       |
                                       v
                       RunResult:  leaked / held
                                   + winning_payload (if leaked)
```

Key properties this diagram encodes:

- **Attacker is stateful, Defender is not.** ATK accumulates the full turn
  history; DEF answers each payload as if it were the first request, which
  models how a real production LLM endpoint behaves.
- **Judge is hybrid.** The deterministic path catches obvious leaks for free;
  the LLM judge only fires when normalization + reverse + base64 all come
  back inconclusive, so the eval suite stays cheap.
- **Strategy diversity is enforced upstream.** ATK is given the list of
  strategies already tried and is told not to repeat one until all 10 are
  exhausted -- this is what stops the loop from emitting the same
  "ignore previous instructions" payload N times.

---

## Safety / scope notes

This tool is intended for **authorized testing of system prompts in apps you own.** It is not a generic jailbreak generator and it does not target real services. The Defender is always an LLM you configure yourself, in the same process.

See `REPORT.md` § AI disclosure & safety for the specific risks and the mitigations chosen.
