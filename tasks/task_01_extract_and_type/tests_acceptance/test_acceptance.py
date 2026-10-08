import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(
    os.environ.get("SWE_ADAPT_REPO", Path(__file__).parent.parent / "repo")
)

MYPY_TIMEOUT = 30


@pytest.mark.parametrize("address", ["alice@example.com", "bob.smith@mail.example.org"])
def test_plain_email_still_accepted_by_email_service(address):
    from email_service import send_email
    assert send_email(address) == f"Sent to {address}"


@pytest.mark.parametrize("address", ["alice@example.com", "bob.smith@mail.example.org"])
def test_plain_email_still_accepted_by_user_service(address):
    from user_service import create_user
    assert create_user(address) == {"email": address, "created": True}


def test_plus_addressed_email_in_email_service():
    from email_service import send_email
    assert send_email("alice+work@example.com") == "Sent to alice+work@example.com"


def test_plus_addressed_email_in_user_service():
    from user_service import create_user
    assert create_user("bob+tag@example.com") == {"email": "bob+tag@example.com", "created": True}


@pytest.mark.parametrize("address", [
    "not-an-email",
    "@example.com",       # empty local part
    "a@b",                # no TLD
    "user name@example.com",  # illegal character in local part
])
def test_invalid_email_still_rejected_by_email_service(address):
    from email_service import send_email
    with pytest.raises(ValueError):
        send_email(address)


@pytest.mark.parametrize("address", [
    "bad-email",
    "@example.com",       # empty local part
    "a@b",                # no TLD
    "user name@example.com",  # illegal character in local part
])
def test_invalid_email_still_rejected_by_user_service(address):
    from user_service import create_user
    with pytest.raises(ValueError):
        create_user(address)


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


@pytest.mark.parametrize("service_module,function_name", [
    ("email_service", "send_email"),
    ("user_service", "create_user"),
])
def test_service_calls_imported_validate_email(service_module, function_name, monkeypatch):
    import importlib

    # Clean failure on the starter (no validators.py), not an import error.
    assert (REPO / "validators.py").is_file(), "validators.py is missing"

    import validators
    service = importlib.import_module(service_module)

    # `from validators import validate_email` binds the name in the service
    # module at import time, so the spy must patch the service's own
    # binding — patching validators.validate_email alone would miss it.
    assert hasattr(service, "validate_email"), (
        f"{service_module} does not import validate_email"
    )

    calls = []
    real_validate = validators.validate_email

    def spy(address, *args, **kwargs):
        calls.append(address)
        return real_validate(address, *args, **kwargs)

    monkeypatch.setattr(service, "validate_email", spy)

    getattr(service, function_name)("carol@example.com")

    assert calls == ["carol@example.com"], (
        f"{service_module} never called its imported validate_email "
        f"(imported but unused?)"
    )
