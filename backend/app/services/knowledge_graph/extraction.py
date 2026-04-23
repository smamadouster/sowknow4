"""
SOWKNOW Knowledge Graph — Entity Extraction & Edge Builder
===========================================================
Plugs into the existing RAG chunking pipeline.
After a document is chunked and embedded, this module:
  1. Extracts entities via spaCy NER
  2. Resolves them against existing graph nodes (dedup)
  3. Creates MENTIONED_IN edges
  4. Runs LLM-assisted relationship extraction for co-occurring entity pairs
  5. Applies domain rules (financial inference edges)
"""

from __future__ import annotations

import itertools
import json
import logging

import asyncpg

from .models import EdgeType, ExtractionMethod, NodeType

logger = logging.getLogger("sowknow.graph.extraction")

# Schema prefix
_S = "sowknow"

# Module-level spaCy model cache — loaded once per process (saves ~400-500MB
# per document when running in Celery prefork workers).
_SPACY_NLP_CACHE: dict = {}


def _vec_to_str(vec: list[float] | None) -> str | None:
    """Convert an embedding vector to a pgvector string literal.

    asyncpg does not ship with a codec for the ``vector`` type, so passing a
    Python list directly makes asyncpg fall back to text encoding and raises
    *expected str, got list*.  Returning ``'[1.0,2.0,...]'`` lets PostgreSQL
    cast the text parameter to ``vector`` via ``::vector`` in SQL.
    """
    if vec is None:
        return None
    return "[" + ",".join(str(v) for v in vec) + "]"


# ── spaCy NER type → SOWKNOW NodeType mapping ────────────────────

_SPACY_TO_NODE_TYPE = {
    "PER": NodeType.PERSON,
    "PERSON": NodeType.PERSON,
    "ORG": NodeType.ORGANIZATION,
    "GPE": NodeType.LOCATION,
    "LOC": NodeType.LOCATION,
    "MONEY": NodeType.AMOUNT,
    "DATE": NodeType.DATE_REF,
    "MISC": NodeType.CONCEPT,
}

# Financial terms that trigger ACCOUNT_LINE classification
_FINANCIAL_KEYWORDS = {
    "chiffre d'affaires", "turnover", "revenue",
    "salaire", "salary", "salaries", "masse salariale",
    "charges financières", "financial charges", "interest",
    "résultat net", "net income", "net profit",
    "résultat d'exploitation", "operating result",
    "charges de personnel", "personnel expenses",
    "bilan", "balance sheet",
    "compte de résultat", "income statement",
    "capitaux propres", "equity",
    "dettes", "liabilities",
    "actif", "assets",
    "amortissement", "depreciation",
    "provisions",
}


class EntityExtractor:
    """Extract entities from text chunks and populate the graph."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        embedding_fn=None,
        llm_fn=None,
        spacy_model: str = "fr_core_news_lg",
    ):
        """
        Args:
            pool: asyncpg connection pool.
            embedding_fn: async callable(text) -> list[float].
            llm_fn: async callable(prompt) -> str.
                    For LLM-assisted relationship extraction.
                    Route to Kimi 2.5 for public, Ollama for confidential.
            spacy_model: spaCy model name. Use fr_core_news_lg for French,
                         en_core_web_trf for English.
        """
        self._pool = pool
        self._embed = embedding_fn
        self._llm = llm_fn

        # Use module-level cache so the ~400-500MB model is loaded once per worker
        if spacy_model not in _SPACY_NLP_CACHE:
            try:
                import spacy
                _SPACY_NLP_CACHE[spacy_model] = spacy.load(spacy_model)
                logger.info("Loaded spaCy model '%s' into process cache", spacy_model)
            except ImportError:
                logger.warning(
                    "spaCy not installed. NER extraction disabled. "
                    "Install with: pip install spacy && python -m spacy download %s",
                    spacy_model,
                )
                _SPACY_NLP_CACHE[spacy_model] = None
            except OSError:
                logger.warning(
                    "spaCy model '%s' not found. Download with: "
                    "python -m spacy download %s",
                    spacy_model, spacy_model,
                )
                _SPACY_NLP_CACHE[spacy_model] = None
        self._nlp = _SPACY_NLP_CACHE.get(spacy_model)

    # ── Main pipeline entry point ─────────────────────────────────

    async def process_chunk(
        self,
        chunk_text: str,
        document_id: str,
        chunk_id: str,
        bucket: str = "public",
    ) -> dict:
        """
        Process a single text chunk through the full graph extraction pipeline.
        Call this from your existing chunking/embedding Celery task.

        Returns dict with counts: {nodes_created, edges_created, nodes_merged}.
        """
        stats = {"nodes_created": 0, "edges_created": 0, "nodes_merged": 0}

        # Step 1: NER extraction
        entities = self._extract_entities(chunk_text)
        if not entities:
            return stats

        # Step 2: Resolve or create nodes
        node_ids = []
        for ent_text, ent_type in entities:
            node_id, created = await self._resolve_or_create(
                ent_text, ent_type, bucket
            )
            node_ids.append(node_id)
            if created:
                stats["nodes_created"] += 1
            else:
                stats["nodes_merged"] += 1

        # Step 3: MENTIONED_IN edges (entity → document node)
        # Ensure the document itself is a graph node (node_type='document')
        doc_node_id = await self._ensure_document_node(document_id, bucket)
        for node_id in node_ids:
            created = await self._create_edge(
                source_id=node_id,
                target_id=doc_node_id,
                edge_type=EdgeType.MENTIONED_IN,
                confidence=0.95,
                method=ExtractionMethod.NER,
                document_id=document_id,
                chunk_id=chunk_id,
            )
            if created:
                stats["edges_created"] += 1

        # Step 4: Domain rules — financial inference edges
        financial_edges = await self._apply_financial_rules(
            entities, node_ids, document_id, chunk_id
        )
        stats["edges_created"] += financial_edges

        # Step 5: LLM-assisted relationship extraction (co-occurring pairs)
        if self._llm and len(node_ids) >= 2:
            llm_edges = await self._llm_relationship_extraction(
                chunk_text, entities, node_ids, document_id, chunk_id, bucket
            )
            stats["edges_created"] += llm_edges

        logger.info(
            "Chunk %s: %d nodes created, %d merged, %d edges",
            chunk_id[:8], stats["nodes_created"],
            stats["nodes_merged"], stats["edges_created"],
        )
        return stats

    # ── NER extraction ────────────────────────────────────────────

    def _extract_entities(self, text: str) -> list[tuple[str, NodeType]]:
        """Run spaCy NER and map to SOWKNOW node types."""
        if not self._nlp:
            # Fall back to financial keyword scanning only
            return self._financial_keyword_scan(text)

        doc = self._nlp(text)
        results = []

        for ent in doc.ents:
            node_type = _SPACY_TO_NODE_TYPE.get(ent.label_)
            if not node_type:
                continue
            # Override: financial keyword detection
            if ent.text.lower() in _FINANCIAL_KEYWORDS:
                node_type = NodeType.ACCOUNT_LINE
            results.append((ent.text.strip(), node_type))

        # Also scan for financial keywords not caught by NER
        text_lower = text.lower()
        for kw in _FINANCIAL_KEYWORDS:
            if kw in text_lower:
                already = any(e[0].lower() == kw for e in results)
                if not already:
                    results.append((kw, NodeType.ACCOUNT_LINE))

        return results

    def _financial_keyword_scan(self, text: str) -> list[tuple[str, NodeType]]:
        """Minimal extraction when spaCy is unavailable — financial terms only."""
        results = []
        text_lower = text.lower()
        for kw in _FINANCIAL_KEYWORDS:
            if kw in text_lower:
                results.append((kw, NodeType.ACCOUNT_LINE))
        return results

    # ── Document node management ──────────────────────────────────

    async def _ensure_document_node(self, document_id: str, bucket: str) -> str:
        """
        Get or create a graph node for this document (node_type='document').
        Documents must exist in graph_nodes so MENTIONED_IN edges satisfy the FK.
        Uses the document UUID as canonical_name so it is idempotent.
        """
        async with self._pool.acquire() as conn:
            existing = await conn.fetchval(
                f"SELECT id FROM {_S}.graph_nodes WHERE id = $1::uuid",
                document_id,
            )
            if existing:
                return str(existing)

            new_id = await conn.fetchval(
                f"""
                INSERT INTO {_S}.graph_nodes
                    (id, canonical_name, node_type, bucket)
                VALUES ($1::uuid, $2, 'document', $3)
                ON CONFLICT (id) DO UPDATE SET node_type = 'document'
                RETURNING id
                """,
                document_id,
                document_id,  # canonical_name = document UUID; consumers join to documents table
                bucket,
            )
            return str(new_id)

    # ── Entity resolution / dedup ──────────────────────────────────

    async def _resolve_or_create(
        self, surface_form: str, node_type: NodeType, bucket: str
    ) -> tuple[str, bool]:
        """
        Check if this entity already exists. If so, add alias. If not, create.
        Returns (node_id, was_created).
        """
        canonical = surface_form.strip().lower()

        # Pre-compute embedding so we don't hold a DB connection during the HTTP call
        embedding = await self._embed(surface_form) if self._embed else None
        embedding_str = _vec_to_str(embedding)
        # Defensive: asyncpg has no vector codec — ensure we always pass a string or None
        if embedding_str is not None and not isinstance(embedding_str, str):
            logger.warning("Embedding is not a string for '%s', skipping similarity", surface_form)
            embedding_str = None

        async with self._pool.acquire() as conn:
            # Check synonym table
            row = await conn.fetchrow(
                f"""
                SELECT canonical_id FROM {_S}.entity_synonyms
                WHERE lower(surface_form) = $1
                LIMIT 1
                """,
                canonical,
            )
            if row:
                existing = await conn.fetchrow(
                    f"SELECT aliases FROM {_S}.graph_nodes WHERE id = $1",
                    row["canonical_id"],
                )
                if existing and surface_form not in (existing["aliases"] or []):
                    await conn.execute(
                        f"UPDATE {_S}.graph_nodes SET aliases = array_append(aliases, $1) WHERE id = $2",
                        surface_form, row["canonical_id"],
                    )
                return str(row["canonical_id"]), False

            # Check embedding similarity if available
            if embedding_str:
                similar = await conn.fetchrow(
                    f"""
                    SELECT id, canonical_name,
                           1 - (embedding <=> $1::vector) AS score
                    FROM {_S}.graph_nodes
                    WHERE node_type = $2
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT 1
                    """,
                    embedding_str, node_type.value,
                )
                if similar and similar["score"] >= 0.85:
                    node_id = similar["id"]
                    await conn.execute(
                        f"UPDATE {_S}.graph_nodes SET aliases = array_append(aliases, $1) WHERE id = $2",
                        surface_form, node_id,
                    )
                    await conn.execute(
                        f"""
                        INSERT INTO {_S}.entity_synonyms (surface_form, canonical_id, language)
                        VALUES ($1, $2, 'fr')
                        ON CONFLICT DO NOTHING
                        """,
                        canonical, node_id,
                    )
                    return str(node_id), False

            # Create new node
            new_id = await conn.fetchval(
                f"""
                INSERT INTO {_S}.graph_nodes (canonical_name, aliases, node_type, embedding, bucket)
                VALUES ($1, $2, $3, $4::vector, $5)
                RETURNING id
                """,
                canonical,
                [surface_form],
                node_type.value,
                embedding_str,
                bucket,
            )
            await conn.execute(
                f"""
                INSERT INTO {_S}.entity_synonyms (surface_form, canonical_id)
                VALUES ($1, $2) ON CONFLICT DO NOTHING
                """,
                canonical, new_id,
            )
            return str(new_id), True

    # ── Edge creation ─────────────────────────────────────────────

    async def _create_edge(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType,
        confidence: float,
        method: ExtractionMethod,
        document_id: str,
        chunk_id: str,
    ) -> bool:
        """Create an edge, returning True if new (not duplicate)."""
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    f"""
                    INSERT INTO {_S}.graph_edges
                        (source_id, target_id, edge_type, confidence,
                         extraction_method, source_document_id, source_chunk_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (source_id, target_id, edge_type, source_document_id)
                    DO UPDATE SET confidence = GREATEST({_S}.graph_edges.confidence, $4)
                    """,
                    source_id, target_id, edge_type.value, confidence,
                    method.value, document_id, chunk_id,
                )
                return True
            except Exception as e:
                logger.error("Edge creation failed: %s", e)
                return False

    # ── Financial domain rules ────────────────────────────────────

    async def _apply_financial_rules(
        self,
        entities: list[tuple[str, NodeType]],
        node_ids: list[str],
        document_id: str,
        chunk_id: str,
    ) -> int:
        """
        If two ACCOUNT_LINE entities co-occur in the same chunk,
        create IMPACTS edges between them.
        """
        edges_created = 0
        account_pairs = [
            (node_ids[i], node_ids[j])
            for i, j in itertools.combinations(range(len(entities)), 2)
            if entities[i][1] == NodeType.ACCOUNT_LINE
            and entities[j][1] == NodeType.ACCOUNT_LINE
        ]
        for src, tgt in account_pairs:
            created = await self._create_edge(
                source_id=src,
                target_id=tgt,
                edge_type=EdgeType.IMPACTS,
                confidence=0.7,
                method=ExtractionMethod.RULE_BASED,
                document_id=document_id,
                chunk_id=chunk_id,
            )
            if created:
                edges_created += 1
        return edges_created

    # ── LLM-assisted relationship extraction ──────────────────────

    async def _llm_relationship_extraction(
        self,
        chunk_text: str,
        entities: list[tuple[str, NodeType]],
        node_ids: list[str],
        document_id: str,
        chunk_id: str,
        bucket: str,
    ) -> int:
        """
        For each pair of entities in a chunk, ask the LLM what
        relationship exists between them.

        Limit to top 5 pairs to control cost/latency.
        """
        pairs = list(itertools.combinations(range(len(entities)), 2))[:5]
        edges_created = 0

        for i, j in pairs:
            ent_a, type_a = entities[i]
            ent_b, type_b = entities[j]

            prompt = (
                f"Given this text excerpt:\n\n\"{chunk_text[:500]}\"\n\n"
                f"What is the relationship between \"{ent_a}\" ({type_a.value}) "
                f"and \"{ent_b}\" ({type_b.value})?\n\n"
                f"Respond ONLY with a JSON object:\n"
                f'{{"relationship": "<one of: component_of, derived_from, impacts, '
                f'causes, precedes, belongs_to, related_to>", '
                f'"confidence": <0.0-1.0>, "direction": "<a_to_b or b_to_a>"}}\n\n'
                f"If no meaningful relationship exists, respond: "
                f'{{"relationship": "none", "confidence": 0}}'
            )

            try:
                raw = await self._llm(prompt)
                raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
                result = json.loads(raw)

                rel = result.get("relationship", "none")
                conf = float(result.get("confidence", 0))

                if rel == "none" or conf < 0.4:
                    continue

                edge_type = _LLM_REL_TO_EDGE.get(rel)
                if not edge_type:
                    continue

                direction = result.get("direction", "a_to_b")
                src = node_ids[i] if direction == "a_to_b" else node_ids[j]
                tgt = node_ids[j] if direction == "a_to_b" else node_ids[i]

                created = await self._create_edge(
                    source_id=src,
                    target_id=tgt,
                    edge_type=edge_type,
                    confidence=conf,
                    method=ExtractionMethod.LLM_INFERRED,
                    document_id=document_id,
                    chunk_id=chunk_id,
                )
                if created:
                    edges_created += 1

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.warning("LLM relationship parse failed: %s", e)
                continue

        return edges_created


# ── LLM response → EdgeType mapping ──────────────────────────────

_LLM_REL_TO_EDGE = {
    "component_of": EdgeType.COMPONENT_OF,
    "derived_from": EdgeType.DERIVED_FROM,
    "impacts": EdgeType.IMPACTS,
    "causes": EdgeType.CAUSES,
    "precedes": EdgeType.PRECEDES,
    "belongs_to": EdgeType.BELONGS_TO,
    "related_to": EdgeType.RELATED_TO,
}
