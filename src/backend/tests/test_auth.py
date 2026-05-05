"""Tests for primitive cookie auth behavior."""

from __future__ import annotations

from backend.auth import PrimitiveAuthManager
from backend.main import is_internal_bot_api_path


def write_auth_file(path) -> None:
    """Create a minimal auth file for an enabled auth manager."""
    path.write_text("[users]\nAdmin = \"secret\"\n", encoding="utf-8")


def test_revoke_session_blocks_only_that_token(monkeypatch, tmp_path) -> None:
    """Logout should invalidate the current signed token server-side."""
    auth_path = tmp_path / "auth.toml"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_SESSION_HOURS", "1")

    manager = PrimitiveAuthManager()
    manager.reload_from_env()

    first_token = manager.create_session("admin")
    assert manager.resolve_session(first_token) == "admin"

    manager.revoke_session(first_token)
    assert manager.resolve_session(first_token) is None

    second_token = manager.create_session("admin")
    assert manager.resolve_session(second_token) == "admin"


def test_revoke_session_ignores_invalid_tokens(monkeypatch, tmp_path) -> None:
    """Malformed logout cookies should not break later valid sessions."""
    auth_path = tmp_path / "auth.toml"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))

    manager = PrimitiveAuthManager()
    manager.reload_from_env()

    manager.revoke_session("not-a-valid-token")

    session_token = manager.create_session("admin")
    assert manager.resolve_session(session_token) == "admin"


def test_internal_token_paths_include_runtime_verification() -> None:
    """Deployment checks should be able to verify runtime readiness with the internal token."""
    assert is_internal_bot_api_path("/api/runtime") is True
    assert is_internal_bot_api_path("/api/funnels") is True
    assert is_internal_bot_api_path("/api/workstation/automation/tick") is True
