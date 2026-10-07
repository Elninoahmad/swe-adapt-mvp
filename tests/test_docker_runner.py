"""Mocked command-construction tests for DockerTestRunner."""

from pathlib import Path
from subprocess import TimeoutExpired
from unittest.mock import MagicMock, patch

import pytest

from harness.test_runner import (
    DockerInfrastructureError,
    DockerTestRunner,
    LocalTestRunner,
)


def test_docker_command_construction():
    runner = DockerTestRunner(
        image="swe-adapt-tester",
        timeout=60,
        cpus="1.0",
        memory="512m",
        pids_limit=64,
    )
    repo = Path("/tmp/fake-repo")
    cmd, name = runner._build_cmd(repo)

    assert cmd[0] == "docker"
    assert "--network" in cmd
    assert cmd[cmd.index("--network") + 1] == "none"
    assert "--rm" in cmd
    assert "-v" in cmd
    assert "/tmp/fake-repo:/workspace" in cmd
    assert "-w" in cmd
    assert "/workspace" in cmd
    assert "--cpus" in cmd
    assert "1.0" in cmd
    assert "--memory" in cmd
    assert "512m" in cmd
    assert "--pids-limit" in cmd
    assert "64" in cmd
    assert "--cap-drop" in cmd
    assert "ALL" in cmd
    assert "--security-opt" in cmd
    assert "no-new-privileges:true" in cmd
    assert "swe-adapt-tester" in cmd
    assert "python" in cmd
    assert "-m" in cmd
    assert "pytest" in cmd
    assert "tests/" in cmd
    assert name.startswith("swe-adapt-pytest-")


def test_docker_timeout_removes_container():
    runner = DockerTestRunner(image="swe-adapt-tester", timeout=1)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            TimeoutExpired("docker", 1),
            MagicMock(returncode=0, stderr="", stdout=""),
        ]

        with pytest.raises(DockerInfrastructureError, match="timed out"):
            runner.run(Path("/tmp/fake-repo"))

        assert mock_run.call_count == 2
        rm_call = mock_run.call_args_list[1]
        assert rm_call[0][0][:3] == ["docker", "rm", "-f"]


def test_docker_timeout_cleanup_failure():
    runner = DockerTestRunner(image="swe-adapt-tester", timeout=1)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            TimeoutExpired("docker", 1),
            TimeoutExpired("docker", 1),
        ]

        with pytest.raises(DockerInfrastructureError, match="cleanup also failed"):
            runner.run(Path("/tmp/fake-repo"))


def test_docker_run_fails_hard_on_missing_docker():
    runner = DockerTestRunner(image="swe-adapt-tester")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError("docker not found")

        with pytest.raises(DockerInfrastructureError, match="not found"):
            runner.run(Path("/tmp/fake-repo"))


def test_docker_run_fails_hard_on_daemon_error():
    runner = DockerTestRunner(image="swe-adapt-tester")

    with patch("subprocess.run") as mock_run:
        class FakeResult:
            returncode = 125
            stderr = "docker: Error response from daemon: pull access denied"
        mock_run.return_value = FakeResult()

        with pytest.raises(DockerInfrastructureError, match="Docker daemon error"):
            runner.run(Path("/tmp/fake-repo"))


def test_docker_pytest_failure_is_not_infrastructure_error():
    runner = DockerTestRunner(image="swe-adapt-tester")

    with patch("subprocess.run") as mock_run:
        class FakeResult:
            returncode = 1
            stderr = "FAILED tests/test_foo.py::test_bar"
        mock_run.return_value = FakeResult()

        ok, reason = runner.run(Path("/tmp/fake-repo"))
        assert not ok
        assert "pytest failed" in reason


def test_docker_no_host_secrets_in_command():
    runner = DockerTestRunner(image="swe-adapt-tester")
    repo = Path("/tmp/fake-repo")
    cmd, _ = runner._build_cmd(repo)

    for flag in cmd:
        assert "ANTHROPIC" not in flag
        assert "GITHUB" not in flag
        assert "SECRET" not in flag
        assert "=" not in flag or flag in ("-e", "PYTHONUNBUFFERED=1", "--pull=never")


def test_local_runner_still_works(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_dummy.py").write_text("def test_ok(): pass\n")
    (repo / "requirements.txt").write_text("pytest==8.3.3")

    runner = LocalTestRunner()
    ok, reason = runner.run(repo)
    assert ok, reason
