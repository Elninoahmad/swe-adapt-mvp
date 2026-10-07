"""Docker acceptance integration tests using the real Task 01 starter."""

import shutil
import subprocess
from pathlib import Path

import pytest

from harness.test_runner import DockerAcceptanceRunner


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


def test_docker_acceptance_on_scripted_final_workspace(
    tester_image_built, actual_starter: Path
):
    """Apply the complete mock-run refactor and change event, then run acceptance in Docker."""
    # Step 1: initial refactor (no types)
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

    # Step 2: change event response (typed + plus-address)
    (actual_starter / "validators.py").write_text(
        "import re\n\n"
        "def validate_email(address: str) -> bool:\n"
        "    return bool(re.match(r'^[\\w.+-]+@[\\w.-]+\\.\\w+$', address))\n"
    )

    acceptance_dir = (
        Path(__file__).parent.parent
        / "tasks"
        / "task_01_extract_and_type"
        / "tests_acceptance"
    )

    runner = DockerAcceptanceRunner(
        image="swe-adapt-tester",
        timeout=120,
    )
    ok, reason = runner.run(actual_starter, acceptance_dir)
    assert ok, reason
