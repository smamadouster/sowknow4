"""
SAKANAL attribution — ``X-Sakanal-Feature`` and ``x-sakanal-request-id``.

WHY THIS EXISTS. The gateway recorded ~98.9% of Sowknow's spans under
``feature='unknown'``/``'unattributed'``. That makes per-module cost, latency and quality
impossible to compute, and it blocks the exact dual-ledger join. Two headers close it:

  ``X-Sakanal-Feature``     what this call is FOR (``interactive_chat``, ``entity_extraction``, ...)
  ``x-sakanal-request-id``  a UUID for the *logical* request: every LLM call made while serving one
                            user action shares it, so this app's logs join exactly to
                            ``sakanal.spans``.

WHERE IT IS APPLIED. In ``openrouter_service._get_headers()``, the single place outbound headers
are constructed. That placement is deliberate: injecting in ``llm_router`` would miss the callers
that bypass it (``silent_agent_loop`` calls the service directly), and a header that covers *most*
traffic is worse than none, because the unattributed remainder looks like a data gap rather than a
bug.

RESOLUTION ORDER, most specific first:

  1. the context override — one per HTTP request, one per Celery task;
  2. ``SAKANAL_FEATURE`` in the environment — a per-container default;
  3. ``"unattributed"``, which is a bug to fix and never a resting state.
"""

from __future__ import annotations

import contextvars
import logging
import os
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

UNATTRIBUTED = "unattributed"

_feature: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sakanal_feature", default=None
)
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "sakanal_request_id", default=None
)
# Provenance: did this traffic come from a person, or from a scheduled monitor?
#
# WHY IT IS SEPARATE FROM `feature`. A monitor is still billable to the feature it exercised, so
# provenance is orthogonal to attribution: encoding it in the feature name (`search_agent_monitor`)
# would break the `sakanal.spans.feature <-> this app's module` join that the whole attribution
# module exists to make exact, and it would need an allowlist edit on BOTH sides to survive.
# SAKANAL records the flag directly.
_synthetic: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "sakanal_synthetic", default=False
)

# The in-app convention for declaring provenance. `X-Synthetic-Monitor` already carries a probe
# NAME and is the programme-wide marker (golegal's canary and MFA drill send it; golegal's
# magistrate middleware consumes it). `x-sakanal-synthetic` is the gateway's transport flag.
# ONE definition, honoured the same way on every app — a second dialect here is how the two ends
# of one header end up disagreeing about what was declared.
SYNTHETIC_NAME_HEADER = "x-synthetic-monitor"
SYNTHETIC_FLAG_HEADER = "x-sakanal-synthetic"


def synthetic_from_headers(headers: Any) -> bool:
    """
    Read a provenance DECLARATION off inbound headers. Absent means organic.

    A monitoring NAME declares by its presence; the transport flag requires an explicit
    true/1. Anything else stays organic, so a monitor that fails to declare itself
    understates monitor burn and can never inflate the organic population it is measured
    against. The asymmetry is deliberate and it matches the gateway's own parser.
    """
    try:
        marker = headers.get(SYNTHETIC_NAME_HEADER)
    except Exception:
        marker = None
    if marker and str(marker).strip():
        return True
    try:
        flag = headers.get(SYNTHETIC_FLAG_HEADER)
    except Exception:
        flag = None
    return str(flag or "").strip().lower() in ("true", "1")


def current_synthetic() -> bool:
    """True when the call being made right now belongs to a declared monitor."""
    return bool(_synthetic.get())

# Longest matching prefix wins, so the order of this tuple does not matter.
_PATH_FEATURES: tuple[tuple[str, str], ...] = (
    ("/api/v1/chat", "interactive_chat"),
    ("/api/v1/collection-requests", "collection_search"),
    ("/api/v1/collections", "collection_search"),
    ("/api/v1/smart-folders", "smart_folder"),
    ("/api/v1/graph-rag", "graph_rag"),
    ("/api/v1/knowledge-graph", "entity_extraction"),
    ("/api/v1/search-agent", "search_agent"),
    ("/api/v1/search", "search_agent"),
    ("/api/v1/reports", "report_generation"),
    ("/api/v1/memory", "memory_distill"),
    ("/api/v1/voice", "voice"),
    ("/api/v1/documents", "document_ingest"),
    ("/api/v1/articles", "article_drafting"),
)

# Celery task-name prefix -> feature.
_TASK_FEATURES: tuple[tuple[str, str], ...] = (
    ("app.tasks.article", "article_drafting"),
    ("app.tasks.entity", "entity_extraction"),
    ("app.tasks.collection", "collection_search"),
    ("app.tasks.document", "document_ingest"),
    ("app.tasks.pipeline", "document_ingest"),
)


def feature_for_path(path: str) -> str:
    """Map an HTTP path to a feature. Unknown paths stay UNATTRIBUTED, visibly."""
    match = ""
    feature = UNATTRIBUTED
    for prefix, name in _PATH_FEATURES:
        if path.startswith(prefix) and len(prefix) > len(match):
            match, feature = prefix, name
    return feature


def feature_for_task(task_name: str) -> str:
    """Map a Celery task name to a feature."""
    for prefix, name in _TASK_FEATURES:
        if task_name.startswith(prefix):
            return name
    return UNATTRIBUTED


def current_feature() -> str:
    """The feature to report for the call being made right now."""
    bound = _feature.get()
    if bound:
        return bound
    return os.getenv("SAKANAL_FEATURE") or UNATTRIBUTED


def current_request_id() -> str:
    """
    The id for the current logical request, minted on first use.

    Minting lazily (rather than only at the boundary) means a call made outside any bound
    request still carries an id, so the span is always traceable — it simply will not share
    one with sibling spans.
    """
    rid = _request_id.get()
    if rid is None:
        rid = str(uuid.uuid4())
        _request_id.set(rid)
    return rid


def bind(
    feature: str | None = None,
    request_id: str | None = None,
    synthetic: bool = False,
) -> tuple[Any, Any, Any]:
    """Bind attribution for the current context. Pass the result to :func:`unbind`."""
    return (_feature.set(feature), _request_id.set(request_id), _synthetic.set(synthetic))


def unbind(tokens: tuple[Any, ...]) -> None:
    ftok, rtok, stok = tokens
    _feature.reset(ftok)
    _request_id.reset(rtok)
    _synthetic.reset(stok)


def install_celery_hooks() -> None:
    """
    Bind attribution per Celery task, from the task name and id.

    Using Celery's own ``task_id`` as the request id is the point: it already appears in this
    app's worker logs, so the join to the gateway ledger needs no extra bookkeeping.
    """
    try:
        from celery import signals
    except Exception:  # pragma: no cover - celery absent outside the workers
        return

    @signals.task_prerun.connect
    def _prerun(sender: Any = None, task_id: str | None = None, **_kw: Any) -> None:
        name = getattr(sender, "name", "") or ""
        _feature.set(feature_for_task(name))
        _request_id.set(str(task_id) if task_id else str(uuid.uuid4()))

    @signals.task_postrun.connect
    def _postrun(**_kw: Any) -> None:
        _feature.set(None)
        _request_id.set(None)
        _synthetic.set(False)


class SakanalAttributionMiddleware(BaseHTTPMiddleware):
    """
    Bind the logical request's feature + id, and echo the id back on the response.

    Only binds for paths that map to a feature. Binding an id to a health probe would put ids
    in the gateway ledger that join to nothing — noise dressed as observability.
    """

    async def dispatch(self, request: Any, call_next: Any) -> Any:  # type: ignore[override]
        feature = feature_for_path(request.url.path)
        if feature == UNATTRIBUTED:
            return await call_next(request)
        rid = str(uuid.uuid4())
        # Provenance rides the same per-request context as the feature, read from the inbound
        # declaration so a probe does not have to know anything about the gateway's header names.
        tokens = bind(feature, rid, synthetic_from_headers(request.headers))
        try:
            response = await call_next(request)
        finally:
            unbind(tokens)
        response.headers["x-sakanal-request-id"] = rid
        return response
