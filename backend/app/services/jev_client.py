"""
JEV shadow client — bounded decisions (``date_range.type``) through the SAKANAL gateway.

WHY IT CALLS SAKANAL AND NOT TYPESAFE. JEV is an OpenRouter *decisions* model: OpenRouter refuses
``~typesafe/jev-latest`` on ``/v1/chat/completions`` and names ``/api/alpha/decisions`` instead.
Calling the vendor (or OpenRouter) directly from here would create exactly the invisible leg this
platform spent eight waves eliminating — the MiniMax/Kimi blind spot, the 402 storm nobody could
see. So the call goes to the gateway's decisions route and lands in ``sakanal.spans`` with its own
provider, tokens and measured cost.

SHADOW ONLY, AND ALWAYS SOFT. Nothing here changes what a user receives. The incumbent LLM still
answers; this runs alongside it. Every failure path — no key, timeout, non-200, unparseable answer
— returns ``None`` and is logged. A bounded decision that cannot be made must never break the
request that was already answered.

PRIVACY (Playbook Pillar 8). The ``state`` sent to JEV is the USER'S QUERY and nothing else —
never a retrieved document chunk. The class is computed from what is actually SENT:

  * PII detected in the query  -> ``never_cloud`` (the gateway refuses it outright)
  * otherwise                  -> ``cloud_allowed``

The vault hint is deliberately NOT the input. It describes the documents a query *retrieved*, and
those documents are never sent here, so mapping "confidential vault" to ``never_cloud`` would
block benign queries for no privacy gain. The class must describe the payload, not the session.

THE JOIN. Every call carries the enclosing request's ``x-sakanal-request-id``, so the JEV span and
the incumbent span it shadows share one ``agent_trace_id``. The incumbent's answer rides along as
``x-sakanal-incumbent-decision``, which is what makes the agreement gate a single ledger query
instead of a hand-join.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.sakanal_attribution import current_request_id

logger = logging.getLogger(__name__)

# The incumbent's vocabulary, and the ONLY vocabulary JEV may answer in. `DateRange` in
# intent_parser plus `all_time`, which its prompt uses for "no period mentioned". A Choice whose
# options are spelled differently compares dialects rather than decisions, so this list is the
# contract between the two sides — see migration 019's header comment.
QUESTION_ID = "date_range_type"

DATE_RANGE_CRITERIA: dict[str, str] = {
    "today": "the current 24-hour day only",
    "yesterday": "the previous 24-hour day only",
    "this_week": "the current calendar week, Monday to today",
    "last_week": "the previous full calendar week",
    "this_month": "the current calendar month to date",
    "last_month": "the previous calendar month - NOT the last 30 days",
    "this_year": "the current calendar year to date",
    "last_year": "the previous calendar year",
    "custom": "an explicit start and end date the user named",
    "all_time": "no time period is mentioned at all",
}

DEFAULT_TIMEOUT_S = 3.0

# Adopt JEV's answer only at or above this confidence; below it the incumbent's stands. 0.90 is the
# pilot's own threshold, and the pilot measured JEV's confidence on the 60-query set rather than
# assuming a calibration curve. Changing it changes the fallback rate, so it is a named constant
# rather than a literal at the call site.
JEV_AUTO_EXECUTE_CONFIDENCE = 0.90
# The shadow leg's feature. Allowlisted on the Sowknow key, and honest about what this call is.
SHADOW_FEATURE = "intent"


@dataclass
class JevDecision:
    """One bounded decision, as measured."""

    choice: str
    confidence: float
    latency_ms: int
    cost_usd: float


def decisions_url() -> str:
    """
    The gateway's decisions endpoint.

    Defaults to the ``/v1/decisions`` alias on the base URL the app already uses, so the shadow
    leg needs no new configuration and no nginx dependency. ``SAKANAL_JEV_URL`` overrides it for
    the canonical ``/api/alpha/decisions`` path.
    """
    explicit = os.getenv("SAKANAL_JEV_URL", "").strip()
    if explicit:
        return explicit
    base = os.getenv("OPENROUTER_BASE_URL", "https://sakanal.gollamtech.com/v1").rstrip("/")
    return f"{base}/decisions"


def build_question() -> dict[str, Any]:
    """
    The Choice question, with a rubric per option.

    The rubric matters: `last_month` is a calendar month, not "the last 30 days", and without
    that sentence the two sides disagree on boundary cases and the gate blames the engine.
    """
    return {
        "type": "choice",
        "instructions": (
            "Which time period does the user's query refer to? "
            "Answer all_time when the query mentions no period at all."
        ),
        "criteria": DATE_RANGE_CRITERIA,
    }


def privacy_class_for(query: str) -> str:
    """
    The privacy class of the payload we are about to send.

    Reuses the app's own PII scanner rather than inventing a second notion of "confidential":
    two definitions of that word is how a leak happens. Import is local so an InputGuard change
    cannot break module import.
    """
    try:
        from app.services.input_guard import InputGuard

        if InputGuard._scan_pii(query):  # noqa: SLF001 - the app's own scanner, reused on purpose
            return "never_cloud"
    except Exception:  # pragma: no cover - scanner unavailable must not block the request
        logger.debug("JEV privacy scan unavailable; treating payload as cloud_allowed")
    return "cloud_allowed"


async def decide_date_range(
    query: str,
    *,
    request_id: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> JevDecision | None:
    """
    Ask JEV for the query's date range. Returns None on ANY failure — never raises.

    ``incumbent_decision`` is not a parameter: the gateway reads it from the header the shadow
    scheduler sets, so this function stays a pure "ask JEV one question" call.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        logger.debug("JEV shadow skipped: no OPENROUTER_API_KEY")
        return None
    if not query.strip():
        return None

    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        # Strict mode on the Sowknow key requires this, on every route.
        "x-sakanal-feature": SHADOW_FEATURE,
        "x-sakanal-privacy": privacy_class_for(query),
        # The join to the incumbent's span.
        "x-sakanal-request-id": request_id or current_request_id(),
    }
    payload = {
        "model": "jev-latest",
        "state": query,
        "questions": {QUESTION_ID: build_question()},
    }

    started = asyncio.get_event_loop().time()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(decisions_url(), headers=headers, json=payload)
        latency_ms = int((asyncio.get_event_loop().time() - started) * 1000)
        if resp.status_code != 200:
            logger.info("JEV shadow non-200: %s %s", resp.status_code, resp.text[:160])
            return None
        body = resp.json()
    except Exception as exc:
        logger.info("JEV shadow failed (soft): %s", exc)
        return None

    answers = body.get("answers") or {}
    answer = answers.get(QUESTION_ID) or {}
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice == "":
        logger.info("JEV shadow returned no usable choice: %s", str(body)[:160])
        return None

    usage = body.get("usage") or {}
    return JevDecision(
        choice=choice,
        confidence=float(answer.get("confidence") or 0.0),
        latency_ms=latency_ms,
        cost_usd=float(usage.get("cost") or 0.0),
    )


async def shadow_compare(
    query: str,
    incumbent_decision: str,
    *,
    request_id: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> JevDecision | None:
    """
    Fire one shadow comparison: ask JEV, and hand the incumbent's answer to the gateway so BOTH
    land on the JEV span.

    The incumbent's value is a HEADER, not a JEV input. It cannot ride on the incumbent's own span
    because that call has already returned by the time its answer exists — so the comparison row
    is the JEV span, and ``agent_trace_id`` ties the two together.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key or not query.strip():
        return None

    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
        "x-sakanal-feature": SHADOW_FEATURE,
        "x-sakanal-privacy": privacy_class_for(query),
        "x-sakanal-request-id": request_id or current_request_id(),
        "x-sakanal-incumbent-decision": incumbent_decision,
    }
    payload = {
        "model": "jev-latest",
        "state": query,
        "questions": {QUESTION_ID: build_question()},
    }

    started = asyncio.get_event_loop().time()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(decisions_url(), headers=headers, json=payload)
        latency_ms = int((asyncio.get_event_loop().time() - started) * 1000)
        if resp.status_code != 200:
            logger.info("JEV shadow non-200: %s %s", resp.status_code, resp.text[:160])
            return None
        body = resp.json()
    except Exception as exc:
        logger.info("JEV shadow failed (soft): %s", exc)
        return None

    answer = (body.get("answers") or {}).get(QUESTION_ID) or {}
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice == "":
        return None
    usage = body.get("usage") or {}
    decision = JevDecision(
        choice=choice,
        confidence=float(answer.get("confidence") or 0.0),
        latency_ms=latency_ms,
        cost_usd=float(usage.get("cost") or 0.0),
    )
    logger.info(
        "JEV shadow: jev=%s(%.2f) incumbent=%s agree=%s latency=%dms cost=$%.7f",
        decision.choice,
        decision.confidence,
        incumbent_decision,
        decision.choice == incumbent_decision,
        decision.latency_ms,
        decision.cost_usd,
    )
    return decision


def schedule_shadow(query: str, incumbent_decision: str, *, request_id: str | None = None) -> None:
    """
    Fire the shadow comparison without making the user wait for it.

    Fire-and-forget is the point: this changes nothing yet, so adding a bounded-decision round trip
    to the request path would be a self-inflicted latency regression. Exceptions are logged inside
    ``shadow_compare`` and never propagate.
    """
    if not incumbent_decision:
        return

    async def _run() -> None:
        try:
            await shadow_compare(query, incumbent_decision, request_id=request_id)
        except Exception:  # pragma: no cover - shadow_compare is already total
            logger.warning("JEV shadow task failed", exc_info=True)

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        logger.debug("JEV shadow skipped: no running loop")
