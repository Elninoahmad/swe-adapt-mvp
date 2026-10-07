import pytest

from harness.test_runner import DockerAcceptanceRunner, DockerTestRunner


@pytest.mark.parametrize(
    "runner",
    [
        DockerTestRunner(image="swe-adapt-tester"),
        DockerAcceptanceRunner(image="swe-adapt-tester"),
    ],
)
def test_docker_run_never_pulls(tmp_path, runner):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    if isinstance(runner, DockerAcceptanceRunner):
        cmd, _ = runner._build_cmd(workspace, tmp_path / "acceptance")
    else:
        cmd, _ = runner._build_cmd(workspace)

    assert cmd.count("--pull=never") == 1
    assert cmd.index("--pull=never") < cmd.index("swe-adapt-tester")
