from email_service import send_email
import pytest


def test_send_email_success():
    assert send_email("alice@example.com") == "Sent to alice@example.com"


def test_send_email_invalid():
    with pytest.raises(ValueError):
        send_email("not-an-email")
