"""End-to-end test: fake agent through Adapter + Orchestrator(live_mode=True)
with Docker pause checks and Docker final acceptance.

Uses the actual Task 01 starter.  No real API key, no live provider request,
no host-side pytest on agent-written files.
"""

import copy
import shutil
from pathlib import Path

import pytest

from harness.adapter import Adapter
from harness.orchestrator import Orchestrator
from harness.test_runner import DockerAcceptanceRunner, DockerTestRunner


class FakeResponse:
    def __init__(self, tool_uses=None, text=None):
        self.tool_uses = tool_uses or []
        self.text = text


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.call_count = 0
        self.sent_calls = []

    def send(self, system_prompt, messages):
        self.sent_calls.append((
            copy.deepcopy(system_prompt),
            copy.deepcopy(messages),
        ))
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp


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


def test_end_to_end_task_01_with_docker(tmp_path: Path):
    """Fake agent refactors Task 01, pauses, adapts to change event,
    and passes final acceptance entirely inside Docker.
    """
    repo_root = Path(__file__).parent.parent
    starter_src = repo_root / "tasks" / "task_01_extract_and_type" / "repo"
    workspace_src = tmp_path / "repo"
    shutil.copytree(starter_src, workspace_src)

    change_event = (
        repo_root / "tasks" / "task_01_extract_and_type" / "CHANGE_EVENT.md"
    )
    acceptance_dir = (
        repo_root / "tasks" / "task_01_extract_and_type" / "tests_acceptance"
    )

    pause_runner = DockerTestRunner(image="swe-adapt-tester", timeout=60)
    acceptance_runner = DockerAcceptanceRunner(
        image="swe-adapt-tester", timeout=120
    )

    orch = Orchestrator(
        workspace_src,
        change_event,
        test_runner=pause_runner,
        live_mode=True,
    )

    assert isinstance(orch.test_runner, DockerTestRunner), (
        "live_mode=True must use DockerTestRunner"
    )

    event_text = change_event.read_text()

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
                        "path": "email_service.py",
                        "content": (
                            "from validators import validate_email\n\n"
                            "def send_email(address):\n"
                            '    if not validate_email(address):\n'
                            '        raise ValueError("Invalid email")\n'
                            '    return f"Sent to {address}"\n'
                        ),
                    },
                },
                {
                    "id": "tu_03",
                    "name": "write_file",
                    "input": {
                        "path": "user_service.py",
                        "content": (
                            "from validators import validate_email\n\n"
                            "def create_user(email):\n"
                            '    if not validate_email(email):\n'
                            '        raise ValueError("Invalid email")\n'
                            '    return {"email": email, "created": True}\n'
                        ),
                    },
                },
            ]
        ),
        FakeResponse(
            tool_uses=[
                {
                    "id": "tu_04",
                    "name": "write_file",
                    "input": {
                        "path": "validators.py",
                        "content": (
                            "import re\n\n"
                            "def validate_email(address: str) -> bool:\n"
                            "    return bool(re.match(r'^[\\w.+-]+@[\\w.-]+\\.\\w+$', address))\n"
                        ),
                    },
                },
            ]
        ),
        FakeResponse(text="Done."),
    ]

    client = FakeClient(responses)
    adapter = Adapter(orch, client, max_turns=10)
    adapter.run(
        system_prompt="You are a helpful assistant.",
        task_prompt="Refactor the code to eliminate duplicated validation logic.",
    )

    assert orch.pause_injected, "Pause should have fired after user_service.py"
    assert client.call_count == 3, f"Expected 3 turns, got {client.call_count}"

    snapshot = orch.workspace.parent / "snapshots" / "pause"
    assert snapshot.exists(), "Pause snapshot should exist"
    assert (snapshot / "validators.py").exists()
    assert (snapshot / "email_service.py").exists()
    assert (snapshot / "user_service.py").exists()

    # Change event absent from first request
    assert not _contains_change_event(
        client.sent_calls[0][1], event_text
    ), "Change event found in first request"

    # Change event present in second request (before typed-plus validator write)
    assert _contains_change_event(
        client.sent_calls[1][1], event_text
    ), "Change event missing from second request"

    # Change event appears exactly once in adapter.messages
    event_count = sum(
        1 for msg in adapter.messages if _contains_change_event([msg], event_text)
    )
    assert event_count == 1, f"Change event appeared {event_count} times in adapter.messages, expected 1"

    # Final acceptance inside Docker
    ok, reason = acceptance_runner.run(orch.workspace, acceptance_dir)
    assert ok, reason
