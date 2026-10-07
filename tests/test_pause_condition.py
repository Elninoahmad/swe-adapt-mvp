from pathlib import Path

import pytest

from pause_condition import is_paused


def _write_validators(repo: Path) -> None:
    (repo / "validators.py").write_text(
        'import re\n\n'
        'def validate_email(address):\n'
        '    return bool(re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address))\n'
    )


def _write_tests(repo: Path) -> None:
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_email_service.py").write_text(
        'from email_service import send_email\n'
        'import pytest\n\n'
        'def test_send_email_success():\n'
        '    assert send_email("alice@example.com") == "Sent to alice@example.com"\n\n'
        'def test_send_email_invalid():\n'
        '    with pytest.raises(ValueError):\n'
        '        send_email("not-an-email")\n'
    )
    (tests / "test_user_service.py").write_text(
        'from user_service import create_user\n'
        'import pytest\n\n'
        'def test_create_user_success():\n'
        '    assert create_user("bob@example.com") == {"email": "bob@example.com", "created": True}\n\n'
        'def test_create_user_invalid():\n'
        '    with pytest.raises(ValueError):\n'
        '        create_user("bad-email")\n'
    )


def _write_positive_services(repo: Path) -> None:
    (repo / "email_service.py").write_text(
        'from validators import validate_email\n\n'
        'def send_email(address):\n'
        '    if not validate_email(address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'from validators import validate_email\n\n'
        'def create_user(email):\n'
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )


def test_positive_valid_refactoring(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_validators(repo)
    _write_positive_services(repo)
    _write_tests(repo)

    paused, reason = is_paused(repo)
    assert paused, reason


def test_negative_no_validator_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "email_service.py").write_text(
        'import re\n\n'
        'def send_email(address):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'import re\n\n'
        'def create_user(email):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )
    _write_tests(repo)

    paused, reason = is_paused(repo)
    assert not paused
    assert "validators.py does not exist" in reason


def test_negative_import_no_call(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_validators(repo)
    _write_tests(repo)
    (repo / "email_service.py").write_text(
        'from validators import validate_email\n'
        'import re\n\n'
        'def send_email(address):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'from validators import validate_email\n'
        'import re\n\n'
        'def create_user(email):\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )

    paused, reason = is_paused(repo)
    assert not paused
    assert "does not call validator in its main function" in reason


def test_negative_still_has_regex(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_validators(repo)
    _write_tests(repo)
    (repo / "email_service.py").write_text(
        'from validators import validate_email\n'
        'import re\n\n'
        'def send_email(address):\n'
        '    if not validate_email(address):\n'
        '        raise ValueError("Invalid email")\n'
        '    if not re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address):\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'from validators import validate_email\n\n'
        'def create_user(email):\n'
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )

    paused, reason = is_paused(repo)
    assert not paused
    assert "duplicated regex still present" in reason


def test_negative_tests_fail(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "validators.py").write_text(
        'import re\n\n'
        'def validate_email(address):\n'
        '    # BUG: missing return\n'
        '    re.match(r\'^[\\w\\.-]+@[\\w\\.-]+\\.\\w+$\', address)\n'
    )
    _write_positive_services(repo)
    _write_tests(repo)

    paused, reason = is_paused(repo)
    assert not paused
    assert "pytest failed" in reason


def test_negative_call_in_unrelated_function(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_validators(repo)
    _write_tests(repo)
    # Validator is called in a helper, but send_email uses a different check
    (repo / "email_service.py").write_text(
        'from validators import validate_email\n\n'
        'def _unused_helper():\n'
        '    # Calls validator here, but send_email never uses it\n'
        '    return validate_email("test@example.com")\n\n'
        'def send_email(address):\n'
        '    if "@" not in address:\n'
        '        raise ValueError("Invalid email")\n'
        '    return f"Sent to {address}"\n'
    )
    (repo / "user_service.py").write_text(
        'from validators import validate_email\n\n'
        'def create_user(email):\n'
        '    if not validate_email(email):\n'
        '        raise ValueError("Invalid email")\n'
        '    return {"email": email, "created": True}\n'
    )

    paused, reason = is_paused(repo)
    assert not paused
    assert "does not call validator in its main function" in reason
