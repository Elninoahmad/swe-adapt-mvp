"""Tests for the Anthropic Messages API client.

All tests use a mocked HTTP transport.  No real API key, no network
calls, no shell tool.
"""

import traceback
from pathlib import Path

import pytest

from harness.anthropic_client import AnthropicApiError, AnthropicClient


class MockTransport:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[dict] = []

    def post(self, url: str, headers: dict, json_data: dict):
        self.calls.append({"url": url, "headers": dict(headers), "json": dict(json_data)})
        if not self.responses:
            raise RuntimeError("No more mock responses")
        return self.responses.pop(0)


class RaisingTransport:
    def __init__(self, exc: Exception):
        self.exc = exc

    def post(self, url: str, headers: dict, json_data: dict):
        raise self.exc


def test_text_only_response():
    transport = MockTransport(
        [
            {
                "content": [{"type": "text", "text": "Done."}],
                "stop_reason": "end_turn",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)
    resp = client.send("You are helpful.", [{"role": "user", "content": "Hello"}])

    assert resp.text == "Done."
    assert resp.tool_uses == []

    assert len(transport.calls) == 1
    payload = transport.calls[0]["json"]
    assert payload["system"] == "You are helpful."
    assert payload["messages"] == [{"role": "user", "content": "Hello"}]
    assert payload["model"] == "claude-test"
    assert transport.calls[0]["headers"]["x-api-key"] == "fake-key"


def test_one_tool_use():
    transport = MockTransport(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_01",
                        "name": "read_file",
                        "input": {"path": "foo.py"},
                    }
                ],
                "stop_reason": "tool_use",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)
    resp = client.send("Sys", [])

    assert resp.text is None
    assert len(resp.tool_uses) == 1
    assert resp.tool_uses[0]["id"] == "tu_01"
    assert resp.tool_uses[0]["name"] == "read_file"
    assert resp.tool_uses[0]["input"] == {"path": "foo.py"}


def test_multiple_tool_uses():
    transport = MockTransport(
        [
            {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_01",
                        "name": "read_file",
                        "input": {"path": "a.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "tu_02",
                        "name": "write_file",
                        "input": {"path": "b.py", "content": "x"},
                    },
                ],
                "stop_reason": "tool_use",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)
    resp = client.send("Sys", [])

    assert len(resp.tool_uses) == 2
    assert resp.tool_uses[0]["name"] == "read_file"
    assert resp.tool_uses[1]["name"] == "write_file"


def test_api_error_known_type():
    dummy_key = "sk-ant-test-key-LEAK-STRUCTURED-999"
    transport = MockTransport(
        [
            {
                "type": "error",
                "error": {
                    "type": "authentication_error",
                    "message": f"Invalid API key: {dummy_key}",
                },
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "Provider error" in str(exc_info.value)
    assert "authentication_error" in str(exc_info.value)
    assert dummy_key not in str(exc_info.value)
    assert "Invalid API key" not in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc


def test_api_error_unknown_type_sanitized():
    dummy_key = "sk-ant-test-key-LEAK-UNKNOWN-888"
    transport = MockTransport(
        [
            {
                "type": "error",
                "error": {
                    "type": "malicious_injection_key=" + dummy_key,
                    "message": "Something went wrong",
                },
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "Provider error" in str(exc_info.value)
    assert "provider_error" in str(exc_info.value)
    assert "malicious_injection" not in str(exc_info.value)
    assert dummy_key not in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc


def test_max_tokens_stop_reason():
    transport = MockTransport(
        [
            {
                "content": [{"type": "text", "text": "Partial..."}],
                "stop_reason": "max_tokens",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError, match="max_tokens"):
        client.send("Sys", [])


def test_missing_content():
    transport = MockTransport(
        [{"stop_reason": "end_turn"}]  # no content field
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError, match="Missing or empty content"):
        client.send("Sys", [])


def test_empty_content_list():
    transport = MockTransport(
        [{"content": [], "stop_reason": "end_turn"}]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError, match="Missing or empty content"):
        client.send("Sys", [])


def test_malformed_content_block():
    transport = MockTransport(
        [
            {
                "content": ["not a dict"],
                "stop_reason": "end_turn",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError, match="Malformed content block"):
        client.send("Sys", [])


def test_non_2xx_response_not_error_shape():
    transport = RaisingTransport(
        AnthropicApiError("HTTP 503: upstream unavailable")
    )
    client = AnthropicClient("fake-key", "claude-test", transport)

    with pytest.raises(AnthropicApiError, match="HTTP 503"):
        client.send("Sys", [])


def test_tools_exclude_shell():
    transport = MockTransport(
        [
            {
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
            }
        ]
    )
    client = AnthropicClient("fake-key", "claude-test", transport)
    client.send("Sys", [])

    tools = transport.calls[0]["json"]["tools"]
    names = [t["name"] for t in tools]
    assert "list_files" in names
    assert "read_file" in names
    assert "write_file" in names
    assert "bash" not in names
    assert "shell" not in names


def test_default_transport_timeout(monkeypatch):
    """Default transport passes finite timeout and raises on socket timeout."""
    import socket
    import urllib.request

    dummy_key = "sk-ant-test-key-LEAK-789"

    def fake_urlopen(req, timeout=None):
        assert timeout == 120, f"Expected timeout 120, got {timeout}"
        raise urllib.error.URLError(socket.timeout("timed out"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = AnthropicClient(dummy_key, "claude-test")
    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "Network error" in str(exc_info.value)
    assert "connection failed" in str(exc_info.value)
    assert dummy_key not in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc
    assert "timed out" not in str(exc_info.value)


def test_default_transport_http_error(monkeypatch):
    """Default transport raises AnthropicApiError on HTTP 5xx without raw body."""
    from io import BytesIO
    import urllib.request

    dummy_key = "sk-ant-test-key-LEAK-123"

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(
            url="https://api.anthropic.com/v1/messages",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=BytesIO(f"upstream unavailable, key={dummy_key}".encode()),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = AnthropicClient("sk-ant-test-key-ABC123", "claude-test")
    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "HTTP 503" in str(exc_info.value)
    assert "server error" in str(exc_info.value)
    assert dummy_key not in str(exc_info.value)
    assert "upstream unavailable" not in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc


def test_default_transport_url_error(monkeypatch):
    """Default transport raises AnthropicApiError on connection failure without reason."""
    import urllib.request

    dummy_key = "sk-ant-test-key-LEAK-456"

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(f"Connection refused, key={dummy_key}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = AnthropicClient("sk-ant-test-key-ABC123", "claude-test")
    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "Network error" in str(exc_info.value)
    assert "connection failed" in str(exc_info.value)
    assert dummy_key not in str(exc_info.value)
    assert "Connection refused" not in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc


def test_default_transport_invalid_json(monkeypatch):
    """Default transport raises AnthropicApiError on unparseable response body."""
    import urllib.request

    dummy_key = "sk-ant-test-key-LEAK-000"

    class FakeResponse:
        def read(self):
            return b"not json {"
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=None):
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    client = AnthropicClient(dummy_key, "claude-test")
    with pytest.raises(AnthropicApiError) as exc_info:
        client.send("Sys", [])

    assert "Invalid JSON" in str(exc_info.value)

    full_exc = "".join(traceback.format_exception(exc_info.value))
    assert dummy_key not in full_exc
