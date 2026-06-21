"""Tests for primitive cookie auth behavior."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import Response
from fastapi.testclient import TestClient

from backend.auth import PrimitiveAuthManager, auth_manager
from backend.endpoints.auth import apply_session_cookie, clear_session_cookie, login_throttle
from backend.main import app, is_internal_bot_api_path


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


def test_revoke_session_survives_manager_reload_without_raw_token(monkeypatch, tmp_path) -> None:
    """Logged-out tokens should remain revoked after backend restart."""
    auth_path = tmp_path / "auth.toml"
    revocations_path = tmp_path / "revocations.json"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_REVOCATIONS_PATH", str(revocations_path))

    manager = PrimitiveAuthManager()
    manager.reload_from_env()
    session_token = manager.create_session("admin")
    manager.revoke_session(session_token)

    persisted = revocations_path.read_text(encoding="utf-8")
    assert session_token not in persisted
    assert json.loads(persisted)

    restarted = PrimitiveAuthManager()
    restarted.reload_from_env()
    assert restarted.resolve_session(session_token) is None


def test_expired_session_revocations_are_pruned(monkeypatch, tmp_path) -> None:
    """Expired revocation entries should not grow forever."""
    auth_path = tmp_path / "auth.toml"
    revocations_path = tmp_path / "revocations.json"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_SESSION_HOURS", "1")
    monkeypatch.setenv("AUTH_REVOCATIONS_PATH", str(revocations_path))

    manager = PrimitiveAuthManager()
    manager.reload_from_env()
    session_token = manager.create_session("admin")
    manager.revoke_session(session_token)

    future = datetime.now(UTC) + timedelta(hours=2)
    monkeypatch.setattr(manager, "_utc_now", lambda: future)

    assert manager.resolve_session(session_token) is None
    assert json.loads(revocations_path.read_text(encoding="utf-8")) == {}


def test_auth_disable_fails_closed_in_production(monkeypatch) -> None:
    """AUTH_DISABLE is not a production bypass."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DISABLE", "true")
    monkeypatch.delenv("AUTH_DISABLE_LOCAL_ONLY", raising=False)

    manager = PrimitiveAuthManager()
    try:
        manager.reload_from_env()
    except RuntimeError as exc:
        assert "AUTH_DISABLE=true is not allowed" in str(exc)
    else:
        raise AssertionError("Production AUTH_DISABLE was accepted")


def test_auth_disable_local_override_still_disables_auth(monkeypatch) -> None:
    """Tests and isolated local work can still opt into disabled auth explicitly."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_DISABLE", "true")
    monkeypatch.setenv("AUTH_DISABLE_LOCAL_ONLY", "true")

    manager = PrimitiveAuthManager()
    manager.reload_from_env()

    assert manager.enabled is False


def test_login_throttles_repeated_bad_passwords(monkeypatch, tmp_path) -> None:
    """Public login should slow online password guessing without sleeps."""
    auth_path = tmp_path / "auth.toml"
    auth_path.write_text("[users]\nadmin = \"secret\"\nviewer = \"secret\"\n", encoding="utf-8")
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("AUTH_LOGIN_FAILURE_LIMIT", "2")
    monkeypatch.setenv("AUTH_LOGIN_WINDOW_SECONDS", "60")
    auth_manager.reload_from_env()
    clock = {"now": 1000.0}
    login_throttle.reset(now=lambda: clock["now"])

    client = TestClient(app)
    first = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"user": "admin", "password": "wrong"},
    )
    assert first.status_code == 401

    isolated_success = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "198.51.100.11"},
        json={"user": "viewer", "password": "secret"},
    )
    assert isolated_success.status_code == 200

    throttled = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"user": "admin", "password": "wrong"},
    )
    assert throttled.status_code == 429
    assert int(throttled.headers["retry-after"]) > 0

    clock["now"] += 61
    recovered = client.post(
        "/api/auth/login",
        headers={"X-Forwarded-For": "198.51.100.10"},
        json={"user": "admin", "password": "secret"},
    )
    assert recovered.status_code == 200


def test_session_cookie_defaults_to_secure(monkeypatch, tmp_path) -> None:
    """Enabled auth should issue production-safe browser cookies by default."""
    auth_path = tmp_path / "auth.toml"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    auth_manager.reload_from_env()

    response = Response()
    apply_session_cookie(response, "token")

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_session_cookie_allows_insecure_local_override(monkeypatch, tmp_path) -> None:
    """Local HTTP can still opt out with AUTH_COOKIE_SECURE=false."""
    auth_path = tmp_path / "auth.toml"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    auth_manager.reload_from_env()

    response = Response()
    apply_session_cookie(response, "token")

    cookie = response.headers["set-cookie"].lower()
    assert "secure" not in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_clear_session_cookie_defaults_to_secure(monkeypatch, tmp_path) -> None:
    """Logout should clear the cookie with matching secure defaults."""
    auth_path = tmp_path / "auth.toml"
    write_auth_file(auth_path)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.delenv("AUTH_COOKIE_SECURE", raising=False)
    auth_manager.reload_from_env()

    response = Response()
    clear_session_cookie(response)

    cookie = response.headers["set-cookie"].lower()
    assert "secure" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie


def test_internal_token_paths_include_runtime_verification() -> None:
    """Deployment checks should be able to verify runtime readiness with the internal token."""
    assert is_internal_bot_api_path("/api/runtime") is True
    assert is_internal_bot_api_path("/api/funnels") is True
    assert is_internal_bot_api_path("/api/platform/events") is True
    assert is_internal_bot_api_path("/api/platform/human-questions") is True
    assert is_internal_bot_api_path("/api/workstation/automation/tick") is True
