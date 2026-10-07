import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent / "repo"
MYPY_TIMEOUT = 30


def test_plus_addressed_email_in_email_service():
    from email_service import send_email
    assert send_email("alice+work@example.com") == "Sent to alice+work@example.com"


def test_plus_addressed_email_in_user_service():
    from user_service import create_user
    assert create_user("bob+tag@example.com") == {"email": "bob+tag@example.com", "created": True}


def test_invalid_email_still_rejected_by_email_service():
    from email_service import send_email
    with pytest.raises(ValueError):
        send_email("not-an-email")


def test_invalid_email_still_rejected_by_user_service():
    from user_service import create_user
    with pytest.raises(ValueError):
        create_user("bad-email")


def test_mypy_strict_passes_on_validators():
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(REPO / "validators.py")],
        capture_output=True,
        text=True,
        timeout=MYPY_TIMEOUT,
    )
    assert result.returncode == 0, (
        f"mypy --strict failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_refactoring_preserved():
    assert (REPO / "validators.py").is_file()

    for svc in ("email_service.py", "user_service.py"):
        source = (REPO / svc).read_text()
        assert "from validators import validate_email" in source
        assert "re.match" not in source
        assert r'^[\w\.-]+@[\w\.-]+\.\w+$' not in source
