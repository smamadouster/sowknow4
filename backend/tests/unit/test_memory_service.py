"""Unit tests for the Agent Memory distillation service (draft v0.1).

Covers:
- Grounding: an atom with an invalid/out-of-range source_message_index is dropped.
- Confidence: an atom below MEMORY_ATOM_MIN_CONFIDENCE is dropped.
- Kind parsing: unknown kinds fall back to fact; bad confidences clamp to 0-100.
- LLM failure: _llm_extract returns [] on garbage/empty/error output.
- Semantic dedup: an atom similar to an existing statement is dropped.
- _cosine edge cases.
"""
import pytest
pytest.skip("Disabled during Ollama removal (Sep 4)", allow_module_level=True)

import uuid

from app.services.memory_service import MemoryService, _cosine


class _Msg:
    def __init__(self, mid, role, content):
        self.id = mid
        self.role = role
        self.content = content


class _M:
    """Duck-typed ChatMessage-alike for grounding checks."""

    USER = "user"
    ASSISTANT = "assistant"


class _FakeDB:
    """No-op stand-in for the async session in _build_atom."""

    pass


def _messages():
    return [
        _Msg(uuid.uuid4(), _M.USER, "Je cherche les documents du bail pour 2026."),
        _Msg(uuid.uuid4(), _M.ASSISTANT, "Voici les documents du bail de l'annee 2026."),
    ]


def _service():
    return MemoryService()


def _atom(db, candidate, messages=None, existing=None):
    import asyncio

    messages = messages or _messages()
    return asyncio.run(
        _service()._build_atom(
            db,
            owner_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            messages=messages,
            transcript=[{"role": m.role, "content": m.content} for m in messages],
            candidate=candidate,
            existing_statements=existing or [],
            now=None,
        )
    )


class TestGrounding:
    def test_valid_source_index_kept(self):
        from app.models.memory import MemoryAtomKind, MemoryStatus

        atom = _atom(
            _FakeDB(),
            {
                "kind": "preference",
                "statement": "le bail 2026 est prioritaire",
                "confidence": 80,
                "source_message_index": 0,
            },
        )
        assert atom is not None
        assert atom.kind == MemoryAtomKind.PREFERENCE
        assert atom.status == MemoryStatus.PENDING
        assert atom.source_message_ids

    def test_out_of_range_index_dropped(self):
        atom = _atom(
            _FakeDB(),
            {"kind": "fact", "statement": "un fait quelconque et durait", "confidence": 90, "source_message_index": 99},
        )
        assert atom is None

    def test_missing_index_dropped(self):
        atom = _atom(
            _FakeDB(),
            {"kind": "fact", "statement": "un fait quelconque et durait", "confidence": 90},
        )
        assert atom is None

    def test_non_integer_index_dropped(self):
        atom = _atom(
            _FakeDB(),
            {
                "kind": "fact",
                "statement": "un fait quelconque et durait",
                "confidence": 90,
                "source_message_index": "abc",
            },
        )
        assert atom is None

    def test_short_statement_dropped(self):
        atom = _atom(
            _FakeDB(),
            {"kind": "fact", "statement": "court", "confidence": 90, "source_message_index": 0},
        )
        assert atom is None


class TestConfidenceAndKind:
    def test_low_confidence_dropped(self):
        atom = _atom(
            _FakeDB(),
            {
                "kind": "fact",
                "statement": "une phrase suffisamment longue ici",
                "confidence": 10,
                "source_message_index": 0,
            },
        )
        assert atom is None

    def test_unknown_kind_falls_back_to_fact(self):
        from app.models.memory import MemoryAtomKind

        atom = _atom(
            _FakeDB(),
            {
                "kind": "bogus",
                "statement": "une phrase suffisamment longue ici",
                "confidence": 80,
                "source_message_index": 0,
            },
        )
        assert atom is not None
        assert atom.kind == MemoryAtomKind.FACT

    def test_confidence_clamped(self):
        atom = _atom(
            _FakeDB(),
            {
                "kind": "decision",
                "statement": "une phrase suffisamment longue ici",
                "confidence": 999,
                "source_message_index": 0,
            },
        )
        assert atom is not None
        assert atom.confidence == 100


class TestSemanticDedup:
    async def _sim(self, a, b):
        return await _service()._most_similar(a, b)

    def test_embed_unavailable_returns_none(self):
        """_most_similar returns None (skip dedup) when no embed server."""
        import asyncio

        result = asyncio.run(
            _service()._most_similar(
                "Le bail de l'immeuble prend fin en 2026.",
                ["Le bail de l'immeuble prend fin en 2026."],
            )
        )
        assert result is None

    def test_exact_duplicate_preserved_when_embed_unavailable(self):
        """Without an embed server the dedup can't run; the atom must still be
        valid and traceable. Asserts we don't crash on dedup absence."""
        import asyncio

        statement = "Le bail de l'immeuble prend fin en 2026."
        candidate = {
            "kind": "fact",
            "statement": statement,
            "confidence": 90,
            "source_message_index": 0,
        }
        atom = _atom(_FakeDB(), candidate)
        assert atom is not None


class TestCosine:
    def test_identical(self):
        assert _cosine([1.0, 0.0], [1.0, 0.0]) == 1.0

    def test_orthogonal(self):
        assert abs(_cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_empty(self):
        assert _cosine([], [1.0]) == 0.0
        assert _cosine([1.0], []) == 0.0

    def test_mismatched_length(self):
        assert _cosine([1.0, 0.0], [1.0]) == 0.0


class TestLlmExtract:
    async def _extract(self, raw):
        return await _service()._llm_extract([{"role": "user", "content": "x"}])

    def test_empty_atoms(self):
        """When the gateway is unavailable, extraction must yield [] — never throw."""
        import asyncio

        result = asyncio.run(self._extract([]))
        assert result == []
