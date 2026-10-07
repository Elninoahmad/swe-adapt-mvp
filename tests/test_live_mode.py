from pathlib import Path

import pytest

from harness.orchestrator import Orchestrator
from harness.test_runner import LocalTestRunner


def test_live_mode_requires_explicit_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    event = tmp_path / "CHANGE_EVENT.md"
    event.write_text("Change event.")

    with pytest.raises(ValueError, match="Live mode requires an explicit test_runner"):
        Orchestrator(repo, event, live_mode=True)


def test_live_mode_rejects_local_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    event = tmp_path / "CHANGE_EVENT.md"
    event.write_text("Change event.")

    with pytest.raises(ValueError, match="Live mode requires a DockerTestRunner"):
        Orchestrator(repo, event, test_runner=LocalTestRunner(), live_mode=True)
