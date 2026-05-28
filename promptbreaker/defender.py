"""The Defender LLM: plays the role of the target application under test.

Given a user-supplied system prompt that contains a secret, the Defender tries
to follow that system prompt and refuse the Attacker's payload.
"""

from __future__ import annotations

from openai import OpenAI


def run_defender(
    client: OpenAI,
    model: str,
    defender_system_prompt: str,
    attacker_payload: str,
) -> str:
    """Send one attacker payload to the defender and return its plain-text reply.

    The defender is a single-turn responder by design: it does not see prior
    attack attempts. That matches how most real LLM apps are deployed (each
    request is independent), and it keeps the difficulty source the *system
    prompt*, not the conversation history.
    """
    completion = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": defender_system_prompt},
            {"role": "user", "content": attacker_payload},
        ],
    )
    return completion.choices[0].message.content or ""
