"""Tests for default no-network pytest guard."""

from __future__ import annotations

import socket

import pytest


def test_external_socket_connections_are_blocked_by_default() -> None:
    """Unmarked tests should not be able to touch external services."""
    with pytest.raises(RuntimeError, match="External network is disabled"):
        socket.create_connection(("93.184.216.34", 80), timeout=0.01)
