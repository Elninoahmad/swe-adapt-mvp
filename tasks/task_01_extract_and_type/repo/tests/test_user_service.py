from user_service import create_user
import pytest


def test_create_user_success():
    assert create_user("bob@example.com") == {"email": "bob@example.com", "created": True}


def test_create_user_invalid():
    with pytest.raises(ValueError):
        create_user("bad-email")
