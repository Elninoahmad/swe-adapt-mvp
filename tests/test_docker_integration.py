"""Docker integration tests using the real Task 01 starter workspace."""

import shutil
import subprocess
from pathlib import Path

import pytest

from harness.test_runner import DockerTestRunner
from pause_condition import is_paused


@pytest.fixture(scope="module")
def docker_available():
    try:
        subprocess.run(["docker", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("Docker not available")


@pytest.fixture(scope="module")
def tester_image_built(docker_available):
    result = subprocess.run(
        ["docker", "image", "inspect", "swe-adapt-tester"],
        capture_output=True,
    )
    if result.returncode != 0:
        pytest.skip("swe-adapt-tester image not built")


@pytest.fixture
def actual_starter(tmp_path: Path) -> Path:
    """Copy the real Task 01 starter into a temp directory."""
    src = Path(__file__).parent.parent / "tasks" / "task_01_extract_and_type" / "repo"
    dst = tmp_path / "repo"
    shutil.copytree(src, dst)
    return dst


def test_docker_on_actual_starter_not_paused(tester_image_built, actual_starter: Path):
    """Starter repo is not paused because validators.py is missing."""
    runner = DockerTestRunner(image="swe-adapt-tester", timeout=60)
    paused, reason = is_paused(actual_starter, test_runner=runner)
    assert not paused
    assert "validators.py does not exist" in reason


def test_docker_on_complete_refactor_is_paused(tester_image_built, actual_starter: Path):
    """Apply the complete refactor to the real starter; Docker pause must fire."""
    (actual_starter / "validators.py").write_text(
        "import re\n\n"
        "def validate_email(address):\n"
        "    return bool(re.match(r'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$', address))\n"
    )
    (actual_starter / "email_service.py").write_text(
        "from validators import validate_email\n\n"
        "def send_email(address):\n"
        '    if not validate_email(address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (actual_starter / "user_service.py").write_text(
        "from validators import validate_email\n\n"
        "def create_user(email):\n"
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )

    runner = DockerTestRunner(image="swe-adapt-tester", timeout=60)
    paused, reason = is_paused(actual_starter, test_runner=runner)
    assert paused, reason
