"""Smoke test for container isolation.

This is a smoke test, not a proof of complete isolation.
If it fails, the CI job aborts before any API key is loaded.
"""

import os
import socket

import pytest


def test_sentinel_secret_not_leaked():
    """Host env vars must not leak into the container."""
    assert os.environ.get("SENTINEL_SECRET") is None


def test_workspace_mounted():
    """The copied starter workspace must be visible at /workspace."""
    assert os.path.isfile("/workspace/email_service.py")


def test_network_isolated():
    """--network none must block outbound connections."""
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 53), timeout=2)


def test_host_checkout_not_mounted():
    """The repository checkout must not be mounted inside."""
    assert not os.path.exists("/host-checkout")
