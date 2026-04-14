import os
import pytest
import httpx
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.sqlite_safe


def _mock_response(status_code: int, json_body):
    mock = MagicMock(spec=httpx.Response)
    mock.status_code = status_code
    mock.json.return_value = json_body
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock
        )
    return mock


@pytest.fixture(autouse=True)
def set_embed_url(monkeypatch):
    monkeypatch.setenv("EMBED_SERVER_URL", "http://embed-server:8000")


def get_client():
    import importlib
    import app.services.embed_client as mod
    importlib.reload(mod)
    return mod.EmbedClient()


def test_encode_calls_embed_endpoint():
    expected = [[0.1] * 1024, [0.2] * 1024]
    with patch("httpx.post", return_value=_mock_response(200, expected)) as mock_post:
        client = get_client()
        result = client.encode(["hello", "world"])
    assert result == expected
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert url.endswith("/embed")
    assert mock_post.call_args[1]["json"]["texts"] == ["hello", "world"]


def test_encode_empty_returns_empty():
    client = get_client()
    result = client.encode([])
    assert result == []


def test_encode_query_calls_embed_query_endpoint():
    expected = [0.3] * 1024
    with patch("httpx.post", return_value=_mock_response(200, expected)):
        client = get_client()
        result = client.encode_query("my search")
    assert result == expected


def test_encode_query_empty_returns_zero_vector():
    client = get_client()
    result = client.encode_query("")
    assert result == [0.0] * 1024
    assert len(result) == 1024


def test_encode_single_wraps_encode():
    expected = [0.5] * 1024
    with patch("httpx.post", return_value=_mock_response(200, [expected])):
        client = get_client()
        result = client.encode_single("one doc")
    assert result == expected


def test_can_embed_true_when_server_healthy():
    health_resp = _mock_response(200, {"status": "healthy"})
    with patch("httpx.get", return_value=health_resp):
        client = get_client()
        assert client.can_embed is True


def test_can_embed_false_when_server_unreachable():
    with patch("httpx.get", side_effect=httpx.ConnectError("refused")):
        client = get_client()
        assert client.can_embed is False


def test_encode_returns_zero_vectors_on_connection_error():
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        client = get_client()
        result = client.encode(["hello"])
    assert result == [[0.0] * 1024]


def test_encode_query_returns_zero_vector_on_connection_error():
    with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
        client = get_client()
        result = client.encode_query("search")
    assert result == [0.0] * 1024


def test_encode_single_returns_zero_on_empty():
    client = get_client()
    assert client.encode_single("") == [0.0] * 1024
    assert client.encode_single("   ") == [0.0] * 1024
