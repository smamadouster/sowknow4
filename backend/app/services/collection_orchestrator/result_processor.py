"""Result Processor — FR3 dedup, ranking, and annotation for source items.

- FR3.3  Dedup: exact duplicates via sha256 of normalized text; near-duplicates
         via 64-bit simhash over token shingles (stdlib only, hamming <= 3).
         The canonical item is the most recent; duplicates are NOT dropped —
         they are returned in a duplicates map for "related items" display.
- FR3.4  Ranking: versioned formula ``RANKING_VERSION = "1.0"``:
         final = 0.55*search + 0.25*rerank + 0.10*recency + 0.10*type_weight.
         All weights overridable via kwargs. Formula + weights are written
         into every item's ``ranking_detail`` and audited.
- FR3.1  Annotations: LLM (tier SIMPLE) writes 2-3 sentence annotations
         citing only evidence present in the item's snippet, batched to bound
         cost; a deterministic template fallback covers LLM failure.
- FR3.2  Category tags: deterministic, from metadata only (no LLM).
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from app.services.collection_orchestrator import audit_logger
from app.services.llm_router import TaskTier, llm_router
from app.services.rerank_service import rerank_passages

logger = logging.getLogger(__name__)

# ── FR3.4 versioned ranking formula ─────────────────────────────────────────
RANKING_VERSION = "1.0"

DEFAULT_WEIGHTS: dict[str, float] = {
    "search": 0.55,
    "rerank": 0.25,
    "recency": 0.10,
    "type": 0.10,
}

# Type weights: official/work documents outrank ephemeral mail and plain text.
TYPE_WEIGHTS: dict[str, float] = {
    "pdf": 1.0,
    "docx": 1.0,
    "doc": 1.0,
    "xlsx": 1.0,
    "xls": 1.0,
    "pptx": 0.9,
    "ppt": 0.9,
    "odt": 0.9,
    "eml": 0.6,
    "msg": 0.6,
    "email": 0.6,
    "txt": 0.5,
    "md": 0.5,
}
DEFAULT_TYPE_WEIGHT = 0.5

RECENCY_FULL_DAYS = 30          # <= 30 days old → recency 1.0
RECENCY_ZERO_DAYS = 5 * 365     # >= 5 years old → recency 0.0 (linear between)
RECENCY_MISSING_DATE = 0.5      # neutral score when no item_date is known

SIMHASH_BITS = 64
SIMHASH_NEAR_DUPE_DISTANCE = 3  # hamming distance <= 3 → near-duplicate

_FALLBACK_SNIPPET_CHARS = 200


# ── Text normalisation / hashing (module-level for testability) ─────────────
def normalize_text(text: str) -> str:
    """Lowercased, punctuation-stripped, whitespace-collapsed text."""
    return " ".join(re.findall(r"\w+", (text or "").lower()))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def _token_shingles(tokens: list[str], n: int = 3) -> list[str]:
    if len(tokens) >= n:
        return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
    return tokens or [""]


def simhash64(text: str) -> int:
    """64-bit simhash over 3-token shingles (stdlib only, FR3.3)."""
    tokens = normalize_text(text).split()
    if not tokens:
        return 0
    bit_counts = [0] * SIMHASH_BITS
    for shingle in _token_shingles(tokens):
        digest = int.from_bytes(hashlib.sha256(shingle.encode("utf-8")).digest()[:8], "big")
        for i in range(SIMHASH_BITS):
            bit_counts[i] += 1 if (digest >> i) & 1 else -1
    fingerprint = 0
    for i, count in enumerate(bit_counts):
        if count > 0:
            fingerprint |= 1 << i
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _item_text(item: dict[str, Any]) -> str:
    return item.get("snippet") or item.get("title") or ""


def _metadata_completeness(item: dict[str, Any]) -> int:
    return sum(
        1
        for key in ("uri", "title", "item_type", "source", "author", "item_date", "snippet")
        if item.get(key)
    )


def _as_naive_utc(dt: Any) -> datetime | None:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def recency_score(item_date: Any, now: datetime | None = None) -> float:
    """Linear decay: 1.0 at <= 30 days → 0.0 at >= 5 years."""
    dt = _as_naive_utc(item_date)
    if dt is None:
        return RECENCY_MISSING_DATE
    now_naive = _as_naive_utc(now) if now else datetime.now(timezone.utc).replace(tzinfo=None)
    age_days = max(0, (now_naive - dt).days)
    if age_days <= RECENCY_FULL_DAYS:
        return 1.0
    if age_days >= RECENCY_ZERO_DAYS:
        return 0.0
    return 1.0 - (age_days - RECENCY_FULL_DAYS) / (RECENCY_ZERO_DAYS - RECENCY_FULL_DAYS)


class ResultProcessor:
    """FR3 processing over retrieved SourceItem dicts."""

    def __init__(
        self,
        *,
        rerank_top_n: int = 200,
        weights: dict[str, float] | None = None,
        type_weights: dict[str, float] | None = None,
        now: datetime | None = None,
        annotation_batch_size: int = 10,
    ):
        self.rerank_top_n = rerank_top_n
        self.weights = dict(DEFAULT_WEIGHTS | (weights or {}))
        self.type_weights = dict(TYPE_WEIGHTS | (type_weights or {}))
        self.now = now
        self.annotation_batch_size = annotation_batch_size

    # ── FR3.3 dedup ─────────────────────────────────────────────────────────
    def dedup(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """Group exact + near duplicates.

        Returns (canonical_items, duplicates_map) where duplicates_map maps the
        canonical item's content_hash to its duplicate items (retained for
        "related items" display, never dropped). Each duplicate gets a
        ``canonical_hash`` pointer; canonical items get ``content_hash`` and
        ``simhash`` set.
        """
        # Pass 1: exact duplicates via content hash
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            h = content_hash(_item_text(item))
            item["content_hash"] = h
            groups.setdefault(h, []).append(item)

        # Pass 2: near-duplicates via simhash on group representatives
        representatives: list[tuple[str, int]] = []  # (hash, simhash)
        cluster_of: dict[str, str] = {}              # hash → cluster root hash
        for h, group in groups.items():
            fp = simhash64(_item_text(group[0]))
            for item in group:
                item["simhash"] = f"{fp:016x}"
            root = h
            for rep_hash, rep_fp in representatives:
                if hamming_distance(fp, rep_fp) <= SIMHASH_NEAR_DUPE_DISTANCE:
                    root = cluster_of[rep_hash]
                    break
            cluster_of[h] = root
            representatives.append((h, fp))

        clusters: dict[str, list[dict[str, Any]]] = {}
        for h, group in groups.items():
            clusters.setdefault(cluster_of[h], []).extend(group)

        canonical_items: list[dict[str, Any]] = []
        duplicates_map: dict[str, list[dict[str, Any]]] = {}
        for cluster_items in clusters.values():
            canonical = max(
                cluster_items,
                key=lambda it: (_as_naive_utc(it.get("item_date")) or datetime.min, _metadata_completeness(it)),
            )
            canonical_items.append(canonical)
            dups = [it for it in cluster_items if it is not canonical]
            if dups:
                for dup in dups:
                    dup["canonical_hash"] = canonical["content_hash"]
                duplicates_map[canonical["content_hash"]] = dups

        return canonical_items, duplicates_map

    # ── FR3.4 ranking ───────────────────────────────────────────────────────
    async def rank(
        self,
        items: list[dict[str, Any]],
        query: str,
        *,
        weights: dict[str, float] | None = None,
        top_n: int | None = None,
        db: Any = None,
        request_id: Any = None,
        user_id: Any = None,
    ) -> list[dict[str, Any]]:
        """Score and order items with the versioned ranking formula.

        rerank_score comes from the cross-encoder over the top-N items by
        search score. If the reranker is unavailable (empty result) or an
        item is outside the reranked top-N, its search score is used as the
        rerank component so ordering degrades gracefully (documented fallback).
        """
        w = dict(self.weights | (weights or {}))
        top_n = top_n if top_n is not None else self.rerank_top_n

        rerank_scores: dict[int, float] = {}
        if items and top_n > 0:
            candidates = sorted(
                range(len(items)),
                key=lambda i: items[i].get("relevance_score") or 0.0,
                reverse=True,
            )[:top_n]
            passages = [items[i].get("snippet") or "" for i in candidates]
            try:
                for position, score in await rerank_passages(query, passages):
                    rerank_scores[candidates[position]] = score
            except Exception as exc:  # rerank_passages already swallows; belt+braces
                logger.debug("Collection ranking: rerank skipped (%s)", exc)

        for index, item in enumerate(items):
            search_score = float(item.get("relevance_score") or 0.0)
            rerank_score = rerank_scores.get(index, search_score)  # fallback: search score
            recency = recency_score(item.get("item_date"), self.now)
            type_weight = self.type_weights.get(str(item.get("item_type") or "").lower(), DEFAULT_TYPE_WEIGHT)
            final = (
                w["search"] * search_score
                + w["rerank"] * rerank_score
                + w["recency"] * recency
                + w["type"] * type_weight
            )
            item["ranking_detail"] = {
                "version": RANKING_VERSION,
                "weights": w,
                "components": {
                    "search_score": search_score,
                    "rerank_score": rerank_score,
                    "recency": recency,
                    "type_weight": type_weight,
                },
                "final_score": final,
            }
            item["_final_score"] = final
            # Relevance signal for the absolute gate + display (2026-08-04):
            # the cross-encoder rerank score discriminates relevant from
            # unrelated far better than the blended final score, which
            # compresses every match into ~0.5-0.6 and let unrelated docs
            # (e.g. a Salesforce migration report) slip past the gate.
            item["_gate_score"] = rerank_score

        ranked = sorted(items, key=lambda it: it["_final_score"], reverse=True)
        for position, item in enumerate(ranked, start=1):
            item["rank_position"] = position
            item.pop("_final_score", None)

        if db is not None:
            await audit_logger.log_event(
                db,
                request_id=request_id,
                user_id=user_id,
                stage="process",
                action="ranking",
                detail={"version": RANKING_VERSION, "weights": w, "item_count": len(ranked)},
            )
        return ranked

    # ── FR3.1 / FR3.2 annotation ────────────────────────────────────────────
    async def annotate(
        self,
        items: list[dict[str, Any]],
        confirmed_params: dict[str, Any],
        user: Any,
        *,
        batch_size: int | None = None,
    ) -> list[dict[str, Any]]:
        """Generate per-item annotations and deterministic category tags.

        Returns a list of annotation dicts aligned with ``items``:
        {item_index, annotation_text, category_tags, evidence_offsets,
        rank_position} — ready to persist as Annotation rows. Each item also
        gets ``category_tags`` and ``annotation_text`` set in place.
        """
        batch_size = batch_size or self.annotation_batch_size
        for item in items:
            item["category_tags"] = self._category_tags(item)

        has_confidential = any(it.get("acl_stamp") == "confidential" for it in items)
        request_summary = self._request_summary(confirmed_params)

        annotations: list[dict[str, Any] | None] = [None] * len(items)
        for batch_start in range(0, len(items), batch_size):
            batch = list(enumerate(items))[batch_start : batch_start + batch_size]
            texts = await self._annotate_batch(batch, request_summary, has_confidential)
            for (index, _item), text in zip(batch, texts):
                annotations[index] = text

        result: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            text = annotations[index] or self._fallback_annotation(item, confirmed_params)
            item["annotation_text"] = text
            result.append({
                "item_index": index,
                "annotation_text": text,
                "category_tags": item["category_tags"],
                "evidence_offsets": [],
                "rank_position": item.get("rank_position"),
            })
        return result

    async def _annotate_batch(
        self,
        batch: list[tuple[int, dict[str, Any]]],
        request_summary: str,
        has_confidential: bool,
    ) -> list[str | None]:
        """One LLM call for a batch; per-item None means 'use fallback'."""
        lines = [f"Collection request: {request_summary}", "", "Items:"]
        for local_index, (_global_index, item) in enumerate(batch):
            lines.append(
                f"[{local_index}] title={item.get('title')!r} "
                f"page={item.get('page_number')} snippet={item.get('snippet', '')[:600]!r}"
            )
        messages = [
            {"role": "system", "content": (
                "You annotate retrieved source items for a knowledge collection. "
                "For each item, write a 2-3 sentence annotation explaining why it is "
                "relevant to the collection request, citing specific evidence from the "
                "item's snippet. NEVER assert content that is not present in the "
                "snippet. Output ONLY valid JSON: "
                '{"annotations": [{"index": <int>, "text": "..."}]}.'
            )},
            {"role": "user", "content": "\n".join(lines)},
        ]
        try:
            chunks = []
            async for chunk in llm_router.generate_completion(
                messages=messages,
                query=request_summary,
                has_confidential=has_confidential,
                stream=False,
                temperature=0.2,
                max_tokens=2048,
                tier=TaskTier.SIMPLE,
            ):
                chunks.append(chunk)
            data = self._parse_json("".join(chunks))
            by_index = {
                int(a["index"]): str(a["text"]).strip()
                for a in data.get("annotations", [])
                if isinstance(a, dict) and "index" in a and a.get("text")
            }
            return [by_index.get(local_index) for local_index in range(len(batch))]
        except Exception as exc:
            logger.warning("Annotation batch failed (%s) — fallback annotations used", exc)
            return [None] * len(batch)

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Defensive JSON parse via the shared balanced-JSON extractor.

        Handles markdown fences, leading prose, and the "__USAGE__" stream
        sentinel (base_llm_service convention) that otherwise makes
        ``find("{")…rfind("}")`` span two JSON objects.
        """
        from app.services.smart_folder.query_parser import extract_first_json

        return extract_first_json(raw)

    @staticmethod
    def _fallback_annotation(item: dict[str, Any], confirmed_params: dict[str, Any]) -> str:
        """Deterministic fallback citing the matched snippet and page."""
        snippet = (item.get("snippet") or "").strip()
        excerpt = snippet[:_FALLBACK_SNIPPET_CHARS]
        if len(snippet) > _FALLBACK_SNIPPET_CHARS:
            excerpt += "…"
        page = item.get("page_number")
        page_ref = f", page {page}" if page else ""
        title = item.get("title") or "untitled document"
        return (
            f"Relevant excerpt from '{title}'{page_ref}: \"{excerpt}\" "
            f"This passage matched the collection request and is cited verbatim "
            f"from the retrieved text."
        )

    @staticmethod
    def _category_tags(item: dict[str, Any]) -> list[str]:
        """FR3.2: deterministic tags from metadata only (no LLM)."""
        tags: list[str] = []
        if item.get("item_type"):
            tags.append(str(item["item_type"]).lower())
        dt = _as_naive_utc(item.get("item_date"))
        if dt is not None:
            tags.append(str(dt.year))
        if item.get("source"):
            tags.append(str(item["source"]))
        seen: set[str] = set()
        return [t for t in tags if not (t in seen or seen.add(t))]

    @staticmethod
    def _request_summary(confirmed_params: dict[str, Any]) -> str:
        if confirmed_params.get("query_text"):
            return str(confirmed_params["query_text"])
        names = [e.get("name", "") for e in confirmed_params.get("entities") or []]
        return " ".join(n for n in names if n) or "knowledge collection"


# Module-level singleton
result_processor = ResultProcessor()
