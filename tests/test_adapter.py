"""Tests for the provider-backed agent adapter.

Uses a fake client with canned responses.  No HTTP, no API key, no
shell tool.  These are harness tests, not claims about real agents.
"""

import copy
from pathlib import Path

import pytest

from harness.adapter import Adapter
from harness.orchestrator import Orchestrator


class FakeResponse:
    def __init__(self, tool_uses=None, text=None):
        self.tool_uses = tool_uses or []
        self.text = text


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
        self.sent_calls = []  # list of (system_prompt, messages) tuples

    def send(self, system_prompt, messages):
        self.sent_calls.append((
            copy.deepcopy(system_prompt),
            copy.deepcopy(messages),
        ))
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


def _build_almost_paused_repo(parent: Path) -> Path:
    """Services refactored to import validators, but validators.py missing."""
    repo = parent / "repo"
    repo.mkdir()
    (repo / "email_service.py").write_text(
        "from validators import validate_email\n\n"
        "def send_email(address):\n"
        '    if not validate_email(address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        "from validators import validate_email\n\n"
        "def create_user(email):\n"
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_email_service.py").write_text(
        "from email_service import send_email\n"
        "import pytest\n\n"
        "def test_send_email_success():\n"
        '    assert send_email("alice@example.com") == "Sent to alice@example.com"\n\n'
        "def test_send_email_invalid():\n"
        "    with pytest.raises(ValueError):\n"
        '        send_email("not-an-email")\n'
    )
    (tests / "test_user_service.py").write_text(
        "from user_service import create_user\n"
        "import pytest\n\n"
        "def test_create_user_success():\n"
        '    assert create_user("bob@example.com") == {"email": "bob@example.com", "created": True}\n\n'
        "def test_create_user_invalid():\n"
        "    with pytest.raises(ValueError):\n"
        '        create_user("bad-email")\n'
    )
    (repo / "requirements.txt").write_text("pytest==8.3.3")
    return repo


def _contains_change_event(messages, event_text):
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text" and event_text in block.get("text", ""):
                    return True
        elif isinstance(content, str) and event_text in content:
            return True
    return False


def test_two_writes_first_triggers_pause_second_skipped(tmp_path: Path) -> None:
    """A response with two writes: the first triggers pause, the second does not execute."""
    repo = _build_almost_paused_repo(tmp_path)
    ce = tmp_path / "CHANGE_EVENT.md"
    ce.write_text(
        "Update validators.py to accept plus-addressed emails and pass mypy --strict."
    )

    orch = Orchestrator(repo, ce)

    responses = [
        FakeResponse(
            tool_uses=[
                {
                    "id": "tu_01",
                    "name": "write_file",
                    "input": {
                        "path": "validators.py",
                        "content": (
                            "import re\n\n"
                            "def validate_email(address):\n"
                            "    return bool(re.match(r'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$', address))\n"
                        ),
                    },
                },
                {
                    "id": "tu_02",
                    "name": "write_file",
                    "input": {
                        "path": "should_not_exist.py",
                        "content": "print('this must not be written')\n",
                    },
                },
            ]
        ),
        FakeResponse(text="Done."),
    ]

    client = FakeClient(responses)
    adapter = Adapter(orch, client, max_turns=10)
    adapter.run("You are a helpful assistant.", "Refactor the code.")

    # First write executed; second skipped
    assert (orch.workspace / "validators.py").exists()
    assert not (orch.workspace / "should_not_exist.py").exists()
    assert orch.pause_injected

    # System prompt present in both requests, absent from conversation messages
    assert len(client.sent_calls) == 2
    for call_idx, (sys_prompt, msgs) in enumerate(client.sent_calls):
        assert sys_prompt == "You are a helpful assistant.", f"Missing system prompt in call {call_idx}"
        assert not any(
            msg.get("role") == "user" and "You are a helpful assistant" in str(msg.get("content", ""))
            for msg in msgs
        ), f"System prompt leaked into conversation messages in call {call_idx}"

    # Change event absent from first request, present in second
    assert not _contains_change_event(
        client.sent_calls[0][1], "plus-addressed"
    ), "Change event found in first request"
    assert _contains_change_event(
        client.sent_calls[1][1], "plus-addressed"
    ), "Change event missing from second request"

    # Roles alternate correctly
    roles = [msg["role"] for msg in adapter.messages]
    assert roles == ["user", "assistant", "user", "assistant"]

    # Both tool uses have matching results; second was skipped with is_error
    user_msg = adapter.messages[2]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    tool_results = [b for b in user_msg["content"] if b.get("type") == "tool_result"]
    assert len(tool_results) == 2
    assert tool_results[0]["tool_use_id"] == "tu_01"
    assert tool_results[1]["tool_use_id"] == "tu_02"
    assert "not executed because requirements changed" in tool_results[1]["content"]
    assert tool_results[1].get("is_error") is True


def test_message_ordering(tmp_path: Path) -> None:
    """Assistant/tool_use must be followed by user/tool_result with matching id."""
    repo = _build_almost_paused_repo(tmp_path)
    ce = tmp_path / "CHANGE_EVENT.md"
    ce.write_text("Change event text.")

    orch = Orchestrator(repo, ce)

    responses = [
        FakeResponse(
            tool_uses=[
                {
                    "id": "tu_01",
                    "name": "write_file",
                    "input": {
                        "path": "validators.py",
                        "content": (
                            "import re\n\n"
                            "def validate_email(address):\n"
                            "    return bool(re.match(r'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$', address))\n"
                        ),
                    },
                },
            ]
        ),
        FakeResponse(text="Done."),
    ]

    client = FakeClient(responses)
    adapter = Adapter(orch, client, max_turns=10)
    adapter.run("System prompt.", "Task prompt.")

    # System prompt stored separately, passed to client, not in messages
    assert adapter.system_prompt == "System prompt."
    assert not any(
        msg.get("role") == "user" and "System prompt." in str(msg.get("content", ""))
        for msg in adapter.messages
    )

    # System prompt present in recorded calls
    assert len(client.sent_calls) == 2
    for sys_prompt, _ in client.sent_calls:
        assert sys_prompt == "System prompt."

    # Roles alternate: user, assistant, user, assistant
    roles = [msg["role"] for msg in adapter.messages]
    assert roles == ["user", "assistant", "user", "assistant"]

    # Assistant message contains tool_use
    assistant_msg = adapter.messages[1]
    assert assistant_msg["role"] == "assistant"
    assistant_content = assistant_msg["content"]
    assert isinstance(assistant_content, list)
    assert assistant_content[0]["type"] == "tool_use"
    assert assistant_content[0]["id"] == "tu_01"

    # User message contains matching tool_result
    user_msg = adapter.messages[2]
    assert user_msg["role"] == "user"
    user_content = user_msg["content"]
    assert isinstance(user_content, list)
    tool_results = [b for b in user_content if b.get("type") == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["tool_use_id"] == "tu_01"

    # Change event is in the same user message as the tool_result
    text_blocks = [b for b in user_content if b.get("type") == "text"]
    assert len(text_blocks) == 1
    assert "Change event text." in text_blocks[0]["text"]
