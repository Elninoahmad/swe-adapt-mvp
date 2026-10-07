"""Anthropic Messages API client for the SWE-Adapt adapter.

The default transport makes real HTTP calls to api.anthropic.com.
Mocked transports are used only in tests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Protocol


class AnthropicApiError(Exception):
    pass


class AgentResponse:
    def __init__(self, text: str | None = None, tool_uses: list[dict[str, Any]] | None = None):
        self.text = text
        self.tool_uses = tool_uses or []


class HttpTransport(Protocol):
    def post(self, url: str, headers: dict[str, str], json_data: dict[str, Any]) -> dict[str, Any]:
        ...


class _DefaultHttpTransport:
    """urllib-based transport with finite timeout.  Makes real HTTP calls."""

    TIMEOUT = 120  # seconds

    def post(self, url: str, headers: dict[str, str], json_data: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(json_data).encode(),
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            # Non-2xx response: raise even if body is not shaped like {"type":"error"}
            body = exc.read()
            try:
                body_text = body.decode()
            except UnicodeDecodeError:
                body_text = "<binary response>"
            raise AnthropicApiError(f"HTTP {exc.code}: {body_text}") from exc
        except urllib.error.URLError as exc:
            # Network error (timeout, connection refused, etc.)
            # exc.reason does not contain the API key.
            raise AnthropicApiError(f"Network error: {exc.reason}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise AnthropicApiError(f"Invalid JSON in response: {exc}") from exc


class AnthropicClient:
    BASE_URL = "https://api.anthropic.com/v1/messages"

    TOOLS = [
        {
            "name": "list_files",
            "description": "List all files under a directory path relative to the workspace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to workspace root",
                    }
                },
            },
        },
        {
            "name": "read_file",
            "description": "Read the contents of a file relative to the workspace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root",
                    }
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to a file relative to the workspace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path relative to workspace root",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file content to write",
                    },
                },
                "required": ["path", "content"],
            },
        },
    ]

    def __init__(
        self,
        api_key: str,
        model: str,
        http_transport: HttpTransport | None = None,
    ):
        self.api_key = api_key
        self.model = model
        self.http = http_transport or _DefaultHttpTransport()

    def send(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
    ) -> AgentResponse:
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
            "tools": self.TOOLS,
        }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        raw = self.http.post(self.BASE_URL, headers, payload)

        # 2xx response with structured error body
        if isinstance(raw, dict) and raw.get("type") == "error":
            err = raw["error"]
            raise AnthropicApiError(f"{err.get('type')}: {err.get('message')}")

        return _parse_response(raw)


def _parse_response(raw: dict[str, Any]) -> AgentResponse:
    stop_reason = raw.get("stop_reason")
    if stop_reason == "max_tokens":
        raise AnthropicApiError("Response truncated: max_tokens reached")

    content = raw.get("content")
    if not isinstance(content, list) or len(content) == 0:
        raise AnthropicApiError("Missing or empty content in response")

    text_parts: list[str] = []
    tool_uses: list[dict[str, Any]] = []

    for idx, block in enumerate(content):
        if not isinstance(block, dict):
            raise AnthropicApiError(
                f"Malformed content block at index {idx}: {block!r}"
            )

        block_type = block.get("type")
        if block_type == "text":
            if "text" not in block:
                raise AnthropicApiError(
                    f"Text block at index {idx} missing 'text' field"
                )
            text_parts.append(block["text"])
        elif block_type == "tool_use":
            for required in ("id", "name", "input"):
                if required not in block:
                    raise AnthropicApiError(
                        f"tool_use block at index {idx} missing '{required}'"
                    )
            tool_uses.append(
                {
                    "id": block["id"],
                    "name": block["name"],
                    "input": block["input"],
                }
            )
        else:
            raise AnthropicApiError(
                f"Unknown content block type at index {idx}: {block_type!r}"
            )

    if stop_reason == "tool_use" and not tool_uses:
        raise AnthropicApiError(
            "stop_reason is 'tool_use' but no tool_use blocks found"
        )

    return AgentResponse(
        text="\n".join(text_parts) if text_parts else None,
        tool_uses=tool_uses,
    )
