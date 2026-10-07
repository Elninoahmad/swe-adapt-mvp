"""Harness tests for the SWE-Adapt orchestrator.

These are NOT real agent results.  They use a scripted mock agent
(sequence of write_file calls) to prove that the orchestrator:
  1. Does not deliver the change event before the pause condition fires
  2. Delivers the change event exactly once
  3. Preserves pre-pause work after the event is injected
  4. Does not log file content in the JSONL trace
"""

import json
from pathlib import Path

import pytest

from harness.orchestrator import Orchestrator


# ----------------------------------------------------------------------
# Fixture builders
# ----------------------------------------------------------------------
def _build_starter_repo(parent: Path) -> Path:
    repo = parent / "repo"
    repo.mkdir()
    (repo / "email_service.py").write_text(
        'import re\n\n'
        'def send_email(address):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'import re\n\n'
        'def create_user(email):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_email_service.py").write_text(
        'from email_service import send_email\n'
        'import pytest\n\n'
        'def test_send_email_success():\n'
        '    assert send_email("alice@example.com") == "Sent to alice@example.com"\n\n'
        'def test_send_email_invalid():\n'
        '    with pytest.raises(ValueError):\n'
        '        send_email("not-an-email")\n'
    )
    (tests / "test_user_service.py").write_text(
        'from user_service import create_user\n'
        'import pytest\n\n'
        'def test_create_user_success():\n'
        '    assert create_user("bob@example.com") == {"email": "bob@example.com", "created": True}\n\n'
        'def test_create_user_invalid():\n'
        '    with pytest.raises(ValueError):\n'
        '        create_user("bad-email")\n'
    )
    (repo / "requirements.txt").write_text("pytest==8.3.3")
    return repo


def _build_change_event(parent: Path) -> Path:
    p = parent / "CHANGE_EVENT.md"
    p.write_text(
        "Update validators.py to accept plus-addressed emails and pass mypy --strict."
    )
    return p


_VALIDATORS_BASE = (
    'import re\n\n'
    'def validate_email(address):\n'
    '    return bool(re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address))\n'
)

_EMAIL_REFACTORED = (
    'from validators import validate_email\n\n'
    'def send_email(address):\n'
    '    if not validate_email(address):\n'
    '        raise ValueError("Invalid email")\n'
    '    return f"Sent to {address}"\n'
)

_USER_REFACTORED = (
    'from validators import validate_email\n\n'
    'def create_user(email):\n'
    '    if not validate_email(email):\n'
    '        raise ValueError("Invalid email")\n'
    '    return {"email": email, "created": True}\n'
)

_VALIDATORS_TYPED_PLUS = (
    'import re\n\n'
    'def validate_email(address: str) -> bool:\n'
    '    return bool(re.match(r\'^[\\w.+-]+@[\\w.-]+\\.\\w+$\', address))\n'
)


# ----------------------------------------------------------------------
# Harness tests
# ----------------------------------------------------------------------
def test_event_not_delivered_early(tmp_path: Path) -> None:
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    orch = Orchestrator(repo, ce)

    orch.run_step("write_file", path="validators.py", content=_VALIDATORS_BASE)
    assert not orch.pause_injected

    orch.run_step("write_file", path="email_service.py", content=_EMAIL_REFACTORED)
    assert not orch.pause_injected


def test_event_delivered_once_and_pre_pause_work_preserved(tmp_path: Path) -> None:
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    trace = tmp_path / "trace.jsonl"
    orch = Orchestrator(repo, ce, trace)

    orch.run_step("write_file", path="validators.py", content=_VALIDATORS_BASE)
    assert not orch.pause_injected

    orch.run_step("write_file", path="email_service.py", content=_EMAIL_REFACTORED)
    assert not orch.pause_injected

    orch.run_step("write_file", path="user_service.py", content=_USER_REFACTORED)
    assert orch.pause_injected

    snapshot = orch.workspace.parent / "snapshots" / "pause"
    assert snapshot.exists()
    assert (snapshot / "validators.py").exists()

    orch.run_step("write_file", path="validators.py", content=_VALIDATORS_TYPED_PLUS)
    assert orch.pause_injected

    assert "from validators import validate_email" in (
        orch.workspace / "email_service.py"
    ).read_text()
    assert "from validators import validate_email" in (
        orch.workspace / "user_service.py"
    ).read_text()

    events = [e for e in orch.trace if e["event"] == "change_event_injected"]
    assert len(events) == 1

    assert trace.exists()
    lines = trace.read_text().strip().split("\n")
    assert len(lines) >= 6


def test_content_not_logged_in_trace(tmp_path: Path) -> None:
    """A distinctive payload must not appear in the JSONL trace."""
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    trace = tmp_path / "trace.jsonl"
    orch = Orchestrator(repo, ce, trace)

    distinctive = "DISTINCTIVE_PAYLOAD_42_XYZ"
    orch.run_step("write_file", path="validators.py", content=distinctive)

    assert trace.exists()
    raw = trace.read_text()
    assert distinctive not in raw
    assert "content_length" in raw
    assert "content_hash" in raw


def test_path_escape_dotdot(tmp_path: Path) -> None:
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    orch = Orchestrator(repo, ce)

    # Create a directory next to the copied workspace
    extra = orch.workspace.parent / "workspace-extra"
    extra.mkdir()
    (extra / "real.txt").write_text("secret")

    with pytest.raises(ValueError, match="escapes workspace"):
        orch.run_step("write_file", path="../workspace-extra/file.txt", content="bad")


def test_inward_pointing_symlink_rejected(tmp_path: Path) -> None:
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    orch = Orchestrator(repo, ce)

    # Symlink inside workspace pointing to another file inside workspace
    real_file = orch.workspace / "real.txt"
    real_file.write_text("real content")
    link_file = orch.workspace / "link.txt"
    link_file.symlink_to(real_file)

    with pytest.raises(ValueError, match="Symlink detected"):
        orch.run_step("write_file", path="link.txt", content="bad")


def test_dangling_symlink_rejected(tmp_path: Path) -> None:
    repo = _build_starter_repo(tmp_path)
    ce = _build_change_event(tmp_path)
    orch = Orchestrator(repo, ce)

    dangling = orch.workspace / "dangling.txt"
    dangling.symlink_to("nonexistent.txt")

    with pytest.raises(ValueError, match="Symlink detected"):
        orch.run_step("write_file", path="dangling.txt", content="bad")
