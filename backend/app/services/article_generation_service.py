"""
Article Generation Service — extracts self-contained knowledge articles from document chunks.

Uses a sliding window over chunks and calls an LLM to extract structured articles.
Each article has a title, summary, body, tags, and entities.
"""

import asyncio
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _content_hash(title: str, body: str) -> str:
    """SHA256 hash of normalized title+body for deduplication."""
    normalized = (title.strip().lower() + "|" + body.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _title_similarity(a: str, b: str) -> float:
    """Jaccard similarity on words for near-duplicate detection."""
    words_a = set(a.strip().lower().split())
    words_b = set(b.strip().lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


SYSTEM_PROMPT_TEMPLATE = """You are a knowledge extraction engine for a document management system.
Given a set of document text chunks, extract self-contained knowledge articles.

Rules:
- Each article must be independently readable without the source document
- Title: descriptive, specific, searchable (not generic like "Information" or "Details")
- Summary: 1-2 sentences capturing the key point
- Body: 200-500 words synthesizing the knowledge from the chunks
- Write in {language}
- Extract ALL distinct knowledge topics — one article per topic
- If chunks contain no extractable knowledge (e.g. table of contents, headers only), return an empty array
- Tags: 2-5 relevant keywords
- Categories: 1-3 broad categories (e.g. "legal", "finance", "family", "health", "education")
- Entities: named entities found (people, organizations, locations, dates)

Return ONLY a valid JSON array. No markdown, no explanation.
[{{"title": "...", "summary": "...", "body": "...", "tags": ["..."], "categories": ["..."], "entities": [{{"name": "...", "type": "person|organization|location|date|concept"}}], "confidence": 85}}]

If no knowledge can be extracted, return: []"""


USER_PROMPT_TEMPLATE = """Document: {filename}
Language: {language}

--- CHUNKS ---
{chunk_texts}
--- END CHUNKS ---

Extract knowledge articles from the above chunks."""


class ArticleGenerationService:
    """Generates articles from document chunks using LLM."""

    def __init__(self, window_size: int = 5, window_overlap: int = 2, max_concurrent: int = 3):
        self.window_size = window_size
        self.window_overlap = window_overlap
        self.max_concurrent = max_concurrent

    def create_chunk_windows(self, chunks: list[dict]) -> list[list[dict]]:
        """Create sliding windows over chunks with overlap."""
        return self._create_windows(chunks, self.window_size, self.window_overlap)

    @staticmethod
    def _create_windows(chunks: list[dict], window_size: int, overlap: int) -> list[list[dict]]:
        """Create sliding windows over chunks with configurable size and overlap."""
        if not chunks:
            return []
        windows = []
        step = max(1, window_size - overlap)
        for i in range(0, len(chunks), step):
            window = chunks[i : i + window_size]
            if window:
                windows.append(window)
        return windows

    async def extract_articles_from_window(
        self,
        window_chunks: list[dict],
        filename: str,
        language: str,
        llm_service: Any,
        provider_name: str,
    ) -> list[dict]:
        """Call LLM to extract articles from a window of chunks."""
        chunk_texts = "\n\n".join(
            f"[Chunk {c['index']}]\n{c['text']}" for c in window_chunks
        )

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(language=language)
        user_prompt = USER_PROMPT_TEMPLATE.format(
            filename=filename,
            language=language,
            chunk_texts=chunk_texts,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Collect full response from streaming generator
        response_text = ""
        try:
            async for chunk in llm_service.chat_completion(
                messages=messages,
                stream=False,
                temperature=0.3,
                max_tokens=4096,
            ):
                if chunk and not chunk.startswith("__USAGE__"):
                    response_text += chunk
        except Exception as e:
            logger.error(f"LLM call failed for article extraction: {e}")
            return []

        # Detect error responses from LLM service
        if response_text.startswith("Error:"):
            logger.warning(f"LLM returned error for article extraction: {response_text}")
            return []

        # Parse JSON response
        return self._parse_articles_json(response_text, window_chunks, provider_name)

    def _parse_articles_json(
        self, response_text: str, window_chunks: list[dict], provider_name: str
    ) -> list[dict]:
        """Parse LLM JSON response into article dicts."""
        # Try to extract JSON array from response
        text = response_text.strip()
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            articles = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON array in the response
            start = text.find("[")
            end = text.rfind("]")
            if start >= 0 and end > start:
                try:
                    articles = json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse article JSON: {text[:200]}")
                    return []
            else:
                logger.warning(f"No JSON array found in LLM response: {text[:200]}")
                return []

        if not isinstance(articles, list):
            return []

        chunk_ids = [c.get("id", "") for c in window_chunks]
        result = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            title = art.get("title", "").strip()
            body = art.get("body", "").strip()
            if not title or not body or len(body) < 50:
                continue

            result.append({
                "title": title,
                "summary": art.get("summary", "").strip(),
                "body": body,
                "tags": art.get("tags", [])[:10],
                "categories": art.get("categories", [])[:5],
                "entities": art.get("entities", [])[:20],
                "confidence": min(100, max(0, int(art.get("confidence", 50)))),
                "source_chunk_ids": chunk_ids,
                "llm_provider": provider_name,
                "content_hash": _content_hash(title, body),
            })

        return result

    def deduplicate_articles(self, articles: list[dict]) -> list[dict]:
        """Remove duplicate articles by content hash and title similarity."""
        seen_hashes = set()
        unique = []
        for art in articles:
            h = art["content_hash"]
            if h in seen_hashes:
                continue

            # Check title similarity with existing articles
            is_near_dup = False
            for existing in unique:
                if _title_similarity(art["title"], existing["title"]) > 0.7:
                    # Keep higher confidence version
                    if art["confidence"] > existing["confidence"]:
                        unique.remove(existing)
                        seen_hashes.discard(existing["content_hash"])
                    else:
                        is_near_dup = True
                    break

            if not is_near_dup:
                seen_hashes.add(h)
                unique.append(art)

        return unique

    async def generate_articles_for_document(
        self,
        document_id: str,
        chunks: list[dict],
        filename: str,
        language: str,
        bucket: str,
        llm_service: Any,
        provider_name: str,
    ) -> list[dict]:
        """
        Generate articles from document chunks.

        Args:
            document_id: UUID of the source document
            chunks: List of chunk dicts with 'id', 'index', 'text' keys
            filename: Original filename for context
            language: Detected language (e.g. 'french', 'english')
            bucket: Document bucket ('public' or 'confidential')
            llm_service: LLM service instance (from llm_router)
            provider_name: Name of the LLM provider

        Returns:
            List of article dicts ready for DB insertion
        """
        if not chunks:
            return []

        # Adapt window size and concurrency for local vs cloud LLMs
        is_local = provider_name == "ollama"
        MAX_WINDOWS = 50  # Cap to prevent huge docs from blocking workers for hours
        if is_local:
            # Local LLM: larger windows (fewer calls), sequential processing
            window_size = 15
            window_overlap = 3
            concurrency = 1
        else:
            # Cloud LLM: larger windows for efficiency, parallel processing
            window_size = 20
            window_overlap = 5
            concurrency = self.max_concurrent

        windows = self._create_windows(chunks, window_size, window_overlap)
        if len(windows) > MAX_WINDOWS:
            logger.info(
                f"Capping {len(windows)} windows to {MAX_WINDOWS} for {filename}"
            )
            windows = windows[:MAX_WINDOWS]
        logger.info(
            f"Generating articles for {filename}: {len(chunks)} chunks, "
            f"{len(windows)} windows (size={window_size}, overlap={window_overlap}, "
            f"concurrency={concurrency}, provider={provider_name})"
        )

        # Process windows with early-exit on consecutive failures
        semaphore = asyncio.Semaphore(concurrency)
        all_articles = []
        consecutive_failures = 0
        max_consecutive_failures = 3

        async def process_window(window):
            async with semaphore:
                return await self.extract_articles_from_window(
                    window, filename, language, llm_service, provider_name,
                )

        # Process in batches to allow early exit if LLM is unreachable
        batch_size = self.max_concurrent
        for batch_start in range(0, len(windows), batch_size):
            if consecutive_failures >= max_consecutive_failures:
                logger.warning(
                    f"Aborting article generation for {filename}: "
                    f"{consecutive_failures} consecutive failures — LLM likely unreachable"
                )
                break

            batch_windows = windows[batch_start : batch_start + batch_size]
            tasks = [process_window(w) for w in batch_windows]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Window {batch_start + i} failed: {result}")
                    consecutive_failures += 1
                    continue
                if not result:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 0
                    all_articles.extend(result)

        # Deduplicate
        unique_articles = self.deduplicate_articles(all_articles)

        # Add document-level metadata
        for art in unique_articles:
            art["document_id"] = document_id
            art["bucket"] = bucket
            art["language"] = language

        logger.info(
            f"Generated {len(unique_articles)} unique articles from {len(all_articles)} raw "
            f"(deduped {len(all_articles) - len(unique_articles)}) for {filename}"
        )
        return unique_articles


# Singleton
article_generation_service = ArticleGenerationService()
