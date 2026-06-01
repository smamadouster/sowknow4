"""Lightweight token estimation and prompt-size enforcement.

Provides a shared `estimate_tokens` utility that prefers tiktoken when
available and falls back to a conservative chars-per-token heuristic
suitable for mixed English/French text (SOWKNOW's primary content).

Also exports `enforce_prompt_ceiling` so the LLM gateway can enforce
hard prompt limits before any provider call.
"""

import logging
from typing import cast

logger = logging.getLogger(__name__)

# Conservative chars-per-token for mixed EN/FR family documents.
# French is denser (~3.2 chars/token) than English (~3.8). 3.5 is a safe
# middle ground that prevents overflow on West-African hosted queries.
_DEFAULT_CHARS_PER_TOKEN = 3.5

# Hard prompt ceilings by tier (tokens).  These are enforced *before*
# the individual provider's own truncation so we never emit an oversized
# payload to any LLM.
MAX_PROMPT_TOKENS: dict[str, int] = {
    "simple": 4_096,
    "standard": 16_384,
    "complex": 100_000,
}


def estimate_tokens(text: str, language: str = "fr") -> int:
    """Conservative token estimation.

    Tries tiktoken (cl100k_base, used by Claude / GPT-4 / Mistral) first;
    falls back to a language-aware chars-per-token heuristic so the
    function works even when tiktoken is not installed.
    """
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        chars_per_token: dict[str, float] = {
            "fr": 3.2,
            "en": 3.8,
            "default": _DEFAULT_CHARS_PER_TOKEN,
        }
        return int(len(text) / chars_per_token.get(language, _DEFAULT_CHARS_PER_TOKEN))


def enforce_prompt_ceiling(
    messages: list[dict[str, str]],
    tier: str = "standard",
) -> list[dict[str, str]]:
    """Truncate messages so total tokens stay within the tier ceiling.

    System messages are preserved; oldest non-system messages are dropped
    first.  This is a last-resort safety net — callers should still design
    prompts that fit comfortably within the budget.
    """
    max_tokens = MAX_PROMPT_TOKENS.get(tier, 16_384)
    total = sum(estimate_tokens(cast(str, m.get("content", ""))) for m in messages)
    if total <= max_tokens:
        return messages

    system_msgs = [m for m in messages if m.get("role") == "system"]
    user_msgs = [m for m in messages if m.get("role") != "system"]

    while user_msgs:
        current = sum(
            estimate_tokens(cast(str, m.get("content", "")))
            for m in system_msgs + user_msgs
        )
        if current <= max_tokens:
            break
        user_msgs.pop(0)

    return system_msgs + user_msgs
