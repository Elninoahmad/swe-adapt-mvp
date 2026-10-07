"""Tests for the Task 01 dry-run CLI (scripts/run_agent.py).

The subprocess tests require Docker and the swe-adapt-tester image (same
prerequisite as tests/test_end_to_end.py) and are intended to run in
GitHub Actions.  The preflight unit tests are hermetic.
"""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.run_agent as run_agent


def _run_cli(artifacts: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_agent.py"),
            "--artifacts",
            str(artifacts),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )


# --- Subprocess end-to-end tests (require Docker + swe-adapt-tester image) ---


def test_task_01_dry_run_cli_success(tmp_path: Path):
    artifacts = tmp_path / "dry-run-artifacts"

    result = _run_cli(artifacts)

    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    report = json.loads((artifacts / "report.json").read_text())
    assert report["label"] == "DRY RUN — not a real agent result"
    assert report["mode"] == "dry-run"
    assert report["run_status"] == "completed"
    assert report["final_acceptance_result"] == "PASSED"

    assert (artifacts / "report.md").is_file()
    assert (artifacts / "trace.jsonl").is_file()
    assert (artifacts / "pause-snapshot").is_dir()
    assert (artifacts / "final-workspace").is_dir()
    assert (artifacts / "final-workspace" / "validators.py").is_file()

    events = [
        json.loads(line)
        for line in (artifacts / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert any(e.get("event") == "change_event_injected" for e in events)
    assert any(e.get("event") == "pause_snapshot" for e in events)


def test_task_01_dry_run_cli_max_turns_2_is_incomplete(tmp_path: Path):
    artifacts = tmp_path / "dry-run-artifacts"

    result = _run_cli(artifacts, "--max-turns", "2")

    assert result.returncode == run_agent.EXIT_TURN_LIMIT, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    report = json.loads((artifacts / "report.json").read_text())
    assert report["label"] == "DRY RUN — INCOMPLETE: not a real agent result"
    assert report["run_status"] == "incomplete_turn_limit"
    assert report["final_acceptance_result"] == "NOT RUN"

    assert (artifacts / "trace.jsonl").is_file()
    assert (artifacts / "final-workspace").is_dir()


def test_task_01_dry_run_cli_missing_image_fails_before_agent(tmp_path: Path):
    artifacts = tmp_path / "dry-run-artifacts"
    missing_image = "swe-adapt-tester-image-that-does-not-exist"

    result = _run_cli(artifacts, "--image", missing_image)

    assert result.returncode == run_agent.EXIT_DOCKER_FAILURE
    assert "refusing to pull" in result.stderr

    # Preflight failure: the agent never executed, so no trace or
    # workspace artifacts exist.  (A partial report may exist.)
    assert not (artifacts / "trace.jsonl").exists()
    assert not (artifacts / "pause-snapshot").exists()
    assert not (artifacts / "final-workspace").exists()


# --- Hermetic preflight unit tests ---


def _fake_docker_run_factory(calls: list, info_rc: int = 0, inspect_rc: int = 0):
    def fake_run(cmd, capture_output, text, timeout):
        calls.append(cmd)
        if cmd[1] == "info":
            return types.SimpleNamespace(returncode=info_rc, stderr="")
        return types.SimpleNamespace(returncode=inspect_rc, stderr="")
    return fake_run


def test_docker_preflight_passes_when_daemon_up_and_image_present(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls)),
    )
    run_agent._docker_preflight("swe-adapt-tester")
    assert calls == [["docker", "info"], ["docker", "image", "inspect", "swe-adapt-tester"]]


def test_docker_preflight_missing_image_raises_and_never_pulls(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls, inspect_rc=1)),
    )
    with pytest.raises(run_agent.DockerInfrastructureError, match="refusing to pull"):
        run_agent._docker_preflight("missing-image")
    assert all("pull" not in cmd for cmd in calls)


def test_docker_preflight_unreachable_daemon_raises(monkeypatch):
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls, info_rc=1)),
    )
    with pytest.raises(run_agent.DockerInfrastructureError, match="unreachable"):
        run_agent._docker_preflight("swe-adapt-tester")
    # daemon check fails first; image inspect never attempted
    assert calls == [["docker", "info"]]
