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

# Clearly fake value; only used to prove the preflight subprocess
# environment does not inherit parent-process secrets.
DUMMY_KEY = "sk-ant-dummy-not-a-real-key"


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
    def fake_run(cmd, capture_output, text, timeout, env=None):
        calls.append({"cmd": cmd, "env": env})
        if cmd[1] == "info":
            return types.SimpleNamespace(returncode=info_rc, stderr="")
        return types.SimpleNamespace(returncode=inspect_rc, stderr="")
    return fake_run


def _assert_preflight_env_sanitized(calls):
    assert calls, "expected preflight subprocess calls"
    for call in calls:
        assert call["env"] is not None, "preflight subprocess inherited parent env"
        assert "ANTHROPIC_API_KEY" not in call["env"]
        assert "PATH" in call["env"]


def test_docker_preflight_passes_when_daemon_up_and_image_present(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls)),
    )
    run_agent._docker_preflight("swe-adapt-tester")
    assert [c["cmd"] for c in calls] == [
        ["docker", "info"],
        ["docker", "image", "inspect", "swe-adapt-tester"],
    ]
    _assert_preflight_env_sanitized(calls)


def test_docker_preflight_missing_image_raises_and_never_pulls(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls, inspect_rc=1)),
    )
    with pytest.raises(run_agent.DockerInfrastructureError, match="refusing to pull"):
        run_agent._docker_preflight("missing-image")
    assert all("pull" not in c["cmd"] for c in calls)
    _assert_preflight_env_sanitized(calls)


def test_docker_preflight_unreachable_daemon_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []
    monkeypatch.setattr(
        run_agent, "subprocess",
        types.SimpleNamespace(run=_fake_docker_run_factory(calls, info_rc=1)),
    )
    with pytest.raises(run_agent.DockerInfrastructureError, match="unreachable"):
        run_agent._docker_preflight("swe-adapt-tester")
    # daemon check fails first; image inspect never attempted
    assert [c["cmd"] for c in calls] == [["docker", "info"]]
    _assert_preflight_env_sanitized(calls)


# --- Hermetic live-mode tests (monkeypatched client; no network, no Docker) ---


class _FakeAnthropicFactory:
    """Records construction kwargs; instances run a scripted send() sequence."""

    def __init__(self, responses=None, exc=None):
        self.constructed = []
        self.responses = responses or []
        self.exc = exc

    def __call__(self, api_key, model, max_tokens=4096):
        self.constructed.append(
            {"api_key": api_key, "model": model, "max_tokens": max_tokens}
        )
        factory = self

        class _Stub:
            def __init__(self):
                self.call_count = 0

            def send(self, system_prompt, messages):
                if factory.exc is not None:
                    raise factory.exc
                resp = factory.responses[self.call_count]
                self.call_count += 1
                return resp

        return _Stub()


class _NoFallbackFakeClient:
    def __init__(self, *args, **kwargs):
        raise AssertionError("FakeClient must never be constructed in live mode")


@pytest.fixture
def no_docker_preflight(monkeypatch):
    monkeypatch.setattr(run_agent, "_docker_preflight", lambda image: None)


def test_build_client_dry_run_uses_fake_and_never_reads_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factory = _FakeAnthropicFactory()
    monkeypatch.setattr(run_agent, "AnthropicClient", factory)

    client = run_agent.build_client(live=False, model=None, max_tokens=4096)

    assert isinstance(client, run_agent.FakeClient)
    assert factory.constructed == []


def test_build_client_live_uses_env_key_and_passes_model_and_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    factory = _FakeAnthropicFactory(responses=[types.SimpleNamespace(tool_uses=[], text="Done.")])
    monkeypatch.setattr(run_agent, "AnthropicClient", factory)

    client = run_agent.build_client(live=True, model="claude-test", max_tokens=512)

    assert client is not None
    assert factory.constructed == [
        {"api_key": DUMMY_KEY, "model": "claude-test", "max_tokens": 512}
    ]


def test_build_client_live_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(run_agent.LiveConfigError, match="ANTHROPIC_API_KEY"):
        run_agent.build_client(live=True, model="claude-test", max_tokens=4096)


def test_live_requires_model_usage_error_exit_2():
    with pytest.raises(SystemExit) as exc_info:
        run_agent.main(["--live"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "4096.0"])
def test_live_invalid_max_tokens_usage_error_exit_2(bad):
    with pytest.raises(SystemExit) as exc_info:
        run_agent.main(["--live", "--model", "claude-test", "--max-tokens", bad])
    assert exc_info.value.code == 2


def test_live_missing_key_writes_incomplete_report(
    monkeypatch, no_docker_preflight, tmp_path
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    factory = _FakeAnthropicFactory()
    monkeypatch.setattr(run_agent, "AnthropicClient", factory)
    monkeypatch.setattr(run_agent, "FakeClient", _NoFallbackFakeClient)

    artifacts = tmp_path / "artifacts"
    rc = run_agent.run(
        artifacts, "img", 10, 60, 120, live=True, model="claude-test"
    )

    assert rc == run_agent.EXIT_API_FAILURE
    assert factory.constructed == []
    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == "live"
    assert report["run_status"] == "incomplete_error"
    assert report["final_acceptance_result"] == "NOT RUN"
    assert report["label"] == "LIVE AGENT RUN — INCOMPLETE: error"


def test_live_api_failure_exits_6_and_never_falls_back(
    monkeypatch, no_docker_preflight, tmp_path
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    factory = _FakeAnthropicFactory(
        exc=run_agent.AnthropicApiError("Provider error: rate_limit_error")
    )
    monkeypatch.setattr(run_agent, "AnthropicClient", factory)
    monkeypatch.setattr(run_agent, "FakeClient", _NoFallbackFakeClient)

    artifacts = tmp_path / "artifacts"
    rc = run_agent.run(
        artifacts, "img", 10, 60, 120, live=True, model="claude-test", max_tokens=512
    )

    assert rc == run_agent.EXIT_API_FAILURE
    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == "live"
    assert report["run_status"] == "incomplete_error"
    assert report["final_acceptance_result"] == "NOT RUN"


def test_live_text_only_before_pause_is_not_reported_successful(
    monkeypatch, no_docker_preflight, tmp_path
):
    """A live agent that answers text-only immediately never triggers the
    pause, so the run must be incomplete (exit 3), never PASSED."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    factory = _FakeAnthropicFactory(
        responses=[types.SimpleNamespace(tool_uses=[], text="Done.")]
    )
    monkeypatch.setattr(run_agent, "AnthropicClient", factory)
    monkeypatch.setattr(run_agent, "FakeClient", _NoFallbackFakeClient)

    artifacts = tmp_path / "artifacts"
    rc = run_agent.run(
        artifacts, "img", 10, 60, 120, live=True, model="claude-test"
    )

    assert rc == run_agent.EXIT_EVENT_NEVER_FIRED
    report = json.loads((artifacts / "report.json").read_text())
    assert report["mode"] == "live"
    assert report["run_status"] == "incomplete_error"
    assert report["final_acceptance_result"] == "NOT RUN"
    assert "INCOMPLETE" in report["label"]
