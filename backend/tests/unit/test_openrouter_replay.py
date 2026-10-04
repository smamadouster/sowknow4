"""Replay de stream (dédoublonnage 60 s — parité avec le client Kodam).

Le cache Redis 1 h ne couvre que le non-streaming ; les requêtes streamées le
contournent par conception. Or le gouverneur SAKANAL bloque un doublon < 60 s
(``zombie_loop``) : le client rejoue donc localement la réponse complétée au
lieu de réémettre. Confidentialité : les requêtes confidentielles ne sont
jamais rejouées ni stockées.
"""

import pytest

from app.services import openrouter_service as ors


class _FakeRedis:
    def __init__(self, values=None):
        self.values = values or {}
        self.writes = []

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, ttl, value):
        self.writes.append((key, ttl, value))


def _bare_service():
    """OpenRouterService sans __init__ lourd : seules les méthodes du chemin
    replay sont exercées, les autres sont stubées par monkeypatch."""
    svc = ors.OpenRouterService.__new__(ors.OpenRouterService)
    svc.api_key = "sk-test"
    svc.base_url = "https://sakanal.test/v1"
    svc._cache_enabled = False
    svc._last_model = None
    return svc


def test_replay_key_stable_and_content_sensitive():
    msgs = [{"role": "user", "content": "q"}]
    k1 = ors.OpenRouterService._replay_key("m", msgs, "standard")
    k2 = ors.OpenRouterService._replay_key("m", msgs, "standard")
    k3 = ors.OpenRouterService._replay_key("m", [{"role": "user", "content": "q2"}], "standard")
    k4 = ors.OpenRouterService._replay_key("m", msgs, "simple")
    assert k1 == k2, "même entrée → même clé (sinon le replay ne tire jamais)"
    assert k1 != k3, "contenu différent → clé différente"
    assert k1 != k4, "tier différent → clé différente"
    assert k1.startswith("sowknow:openrouter:replay:")


@pytest.mark.asyncio
async def test_identical_streaming_request_is_replayed_without_http(monkeypatch):
    svc = _bare_service()
    monkeypatch.setattr(svc, "_truncate_messages", lambda m: m)
    monkeypatch.setattr(svc, "_check_cost_ceiling", lambda *a, **k: True)
    monkeypatch.setattr(svc, "_check_cost_anomaly", lambda *a, **k: "standard")
    monkeypatch.setattr(svc, "select_model_for_tier", lambda tier: "mock-model")

    messages = [{"role": "user", "content": "q"}]
    key = svc._replay_key("mock-model", messages, "standard")
    fake = _FakeRedis({key: "réponse mémorisée"})
    monkeypatch.setattr(ors, "_get_redis_client", lambda: fake)

    chunks = [
        chunk
        async for chunk in svc.chat_completion(messages, stream=True, tier="standard")
    ]
    assert chunks == ["réponse mémorisée"]


@pytest.mark.asyncio
async def test_confidential_streaming_request_is_never_replayed(monkeypatch):
    """PRIVACY : une requête confidentielle ignore le replay même si la clé
    existerait — aucune sortie mémorisée ne doit la servir."""
    svc = _bare_service()
    monkeypatch.setattr(svc, "_truncate_messages", lambda m: m)
    monkeypatch.setattr(svc, "_check_cost_ceiling", lambda *a, **k: True)
    monkeypatch.setattr(svc, "_check_cost_anomaly", lambda *a, **k: "standard")
    monkeypatch.setattr(svc, "select_model_for_tier", lambda tier: "mock-model")

    messages = [{"role": "user", "content": "q"}]
    key = svc._replay_key("mock-model", messages, "standard")
    fake = _FakeRedis({key: "réponse mémorisée"})
    monkeypatch.setattr(ors, "_get_redis_client", lambda: fake)

    # Sans mock HTTP, tout passage AU-DELÀ du replay échoue : c'est précisément
    # ce qu'on veut prouver (le chemin confidentiel ne court-circuite pas).
    chunks = []
    try:
        async for chunk in svc.chat_completion(
            messages, stream=True, tier="standard", is_confidential=True
        ):
            chunks.append(chunk)
    except Exception:
        pass
    assert "réponse mémorisée" not in chunks
