import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.sqlite_safe


@pytest.fixture()
def client(monkeypatch):
    """TestClient with model loading bypassed (no GPU/model in CI)."""
    from unittest.mock import MagicMock, patch

    mock_svc = MagicMock()
    mock_svc.health_check.return_value = {"status": "healthy", "model_loaded": True}
    mock_svc.encode.return_value = [[0.1] * 1024, [0.2] * 1024]
    mock_svc.encode_query.return_value = [0.3] * 1024
    mock_svc.embedding_dim = 1024
    mock_svc.can_embed = True

    with patch("embed_server.main.svc", mock_svc):
        from embed_server.main import app
        yield TestClient(app)


def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_embed_returns_vectors(client):
    resp = client.post("/embed", json={"texts": ["hello", "world"]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert len(data[0]) == 1024
    import embed_server.main as m
    assert m.svc.encode.called


def test_embed_empty_texts(client):
    resp = client.post("/embed", json={"texts": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_embed_query_returns_vector(client):
    resp = client.post("/embed-query", json={"text": "search query"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1024
    import embed_server.main as m
    assert m.svc.encode_query.called


def test_embed_query_empty_text(client):
    resp = client.post("/embed-query", json={"text": ""})
    assert resp.status_code == 200
    assert resp.json() == [0.0] * 1024


def test_embed_returns_503_when_model_not_loaded():
    from unittest.mock import MagicMock, patch

    mock_svc = MagicMock()
    mock_svc.can_embed = False
    mock_svc.embedding_dim = 1024
    mock_svc.health_check.return_value = {"status": "error", "model_loaded": False}

    with patch("embed_server.main.svc", mock_svc):
        import importlib
        import embed_server.main as m
        importlib.reload(m)
        c = TestClient(m.app)
        resp = c.post("/embed", json={"texts": ["hello"]})
    assert resp.status_code == 503
