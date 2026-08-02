"""Query Planner — FR2.1/FR2.2/FR2.3 deterministic search planning.

Pure functions, no I/O: turns ``confirmed_params`` (from the clarification
stage) into a minimal list of ``SearchCallSpec`` objects the SearchAdapter
executes.

Rules:
- FR2.1  Filters are carried on every spec and pushed down to the DB by the
         adapter — never applied post-hoc over an unfiltered corpus.
- FR2.2  Decomposition: when doc_types are disjoint (more than one type),
         one spec per doc_type; otherwise a single spec. Minimum number of
         calls covering the request.
- FR2.3  Pagination: page size is clamped to <= 100; follow-up pages are
         computed lazily by ``paginate`` (materialising 1000 page specs for
         the 100k cap upfront would be wasteful) so the adapter can stop as
         soon as a result set is exhausted.
"""

from dataclasses import dataclass, replace
from typing import Any

MAX_PAGE_SIZE = 100  # hard ceiling per spec (FR2.3)


def _default_max_items() -> int:
    """Lazy settings access — keeps module import free of config/env requirements."""
    from app.core.config import settings

    return settings.COLLECTION_MAX_ITEMS


@dataclass(frozen=True)
class SearchCallSpec:
    """One search call to execute (payload + pushed-down filters)."""

    query_text: str
    doc_types: tuple[str, ...] = ()
    date_from: str | None = None
    date_to: str | None = None
    tags: tuple[str, ...] = ()
    limit: int = MAX_PAGE_SIZE
    offset: int = 0

    def filter_signature(self) -> tuple:
        """Identity of the pushed-down filter set (for adapter doc-id lookups)."""
        return (self.doc_types, self.date_from, self.date_to, self.tags)


def _base_query(confirmed_params: dict[str, Any]) -> str:
    """Query text for the search calls: original text, else entity names."""
    query_text = (confirmed_params.get("query_text") or "").strip()
    if query_text:
        return query_text
    names = [e.get("name", "") for e in confirmed_params.get("entities") or []]
    return " ".join(n for n in names if n).strip()


def plan_searches(
    confirmed_params: dict[str, Any],
    *,
    page_size: int = MAX_PAGE_SIZE,
) -> list[SearchCallSpec]:
    """Decompose confirmed params into the minimum set of search specs.

    Each returned spec is the first page (offset=0) of a paginated branch;
    the adapter requests follow-up pages via :func:`paginate`.
    """
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    query_text = _base_query(confirmed_params)
    if not query_text:
        return []

    filters = confirmed_params.get("filters") or {}
    doc_types = tuple(dt.lower().lstrip(".") for dt in (filters.get("doc_types") or []) if dt)
    tags = tuple(t for t in (filters.get("tags") or []) if t)
    date_range = confirmed_params.get("date_range") or {}
    date_from = date_range.get("from")
    date_to = date_range.get("to")

    # FR2.2: decompose per doc_type when filters are disjoint
    branches: list[tuple[str, ...]] = [(dt,) for dt in doc_types] if len(doc_types) > 1 else [doc_types]

    return [
        SearchCallSpec(
            query_text=query_text,
            doc_types=branch,
            date_from=date_from,
            date_to=date_to,
            tags=tags,
            limit=page_size,
            offset=0,
        )
        for branch in branches
    ]


def paginate(
    spec: SearchCallSpec,
    total: int,
    *,
    max_items: int | None = None,
) -> list[SearchCallSpec]:
    """Follow-up page specs needed to cover ``total`` results for a branch.

    Stops at the FR2.3 hard cap (settings.COLLECTION_MAX_ITEMS). The first
    page (offset=0) is NOT included — the caller already executed it.
    """
    max_items = max_items if max_items is not None else _default_max_items()
    pages: list[SearchCallSpec] = []
    offset = spec.offset + spec.limit
    while offset < total and offset < max_items:
        pages.append(replace(spec, offset=offset))
        offset += spec.limit
    return pages
