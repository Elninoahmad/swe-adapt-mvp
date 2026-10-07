import subprocess
import types
from pathlib import Path

import pytest

import harness.test_runner as test_runner
from harness.test_runner import DockerAcceptanceRunner, DockerTestRunner

DUMMY_KEY = "sk-ant-dummy-not-a-real-key"


def _assert_docker_run_flags_preserved(cmd):
    assert "--pull=never" in cmd
    assert "--name" in cmd
    name_idx = cmd.index("--name")
    assert cmd[name_idx + 1].startswith("swe-adapt-")


def _assert_sanitized_env(calls):
    assert calls, "expected at least one docker subprocess"
    for call in calls:
        assert call["env"] is not None, "docker subprocess inherited parent env"
        assert "ANTHROPIC_API_KEY" not in call["env"]
        assert "PATH" in call["env"]


def test_pause_runner_env_sanitized_and_flags_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []

    def fake_run(cmd, capture_output=None, text=None, timeout=None, env=None):
        calls.append({"cmd": cmd, "env": env})
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    repo = tmp_path / "repo"
    repo.mkdir()
    ok, _ = DockerTestRunner(image="img").run(repo)

    assert ok
    assert len(calls) == 1
    _assert_docker_run_flags_preserved(calls[0]["cmd"])
    _assert_sanitized_env(calls)


def test_acceptance_runner_env_sanitized_and_flags_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []

    def fake_run(cmd, capture_output=None, text=None, timeout=None, env=None):
        calls.append({"cmd": cmd, "env": env})
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    workspace = tmp_path / "ws"
    acceptance = tmp_path / "acc"
    workspace.mkdir()
    acceptance.mkdir()
    ok, _ = DockerAcceptanceRunner(image="img").run(workspace, acceptance)

    assert ok
    assert len(calls) == 1
    _assert_docker_run_flags_preserved(calls[0]["cmd"])
    _assert_sanitized_env(calls)


def test_pause_runner_timeout_cleanup_env_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []

    def fake_run(cmd, capture_output=None, text=None, timeout=None, env=None):
        calls.append({"cmd": cmd, "env": env})
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(test_runner.DockerInfrastructureError):
        DockerTestRunner(image="img", timeout=5).run(repo)

    assert len(calls) == 2
    assert calls[1]["cmd"][:3] == ["docker", "rm", "-f"]
    _assert_docker_run_flags_preserved(calls[0]["cmd"])
    _assert_sanitized_env(calls)


def test_acceptance_runner_timeout_cleanup_env_sanitized(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", DUMMY_KEY)
    calls = []

    def fake_run(cmd, capture_output=None, text=None, timeout=None, env=None):
        calls.append({"cmd": cmd, "env": env})
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, timeout)
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(test_runner.subprocess, "run", fake_run)

    workspace = tmp_path / "ws"
    acceptance = tmp_path / "acc"
    workspace.mkdir()
    acceptance.mkdir()
    with pytest.raises(test_runner.DockerInfrastructureError):
        DockerAcceptanceRunner(image="img", timeout=5).run(workspace, acceptance)

    assert len(calls) == 2
    assert calls[1]["cmd"][:3] == ["docker", "rm", "-f"]
    _assert_docker_run_flags_preserved(calls[0]["cmd"])
    _assert_sanitized_env(calls)
