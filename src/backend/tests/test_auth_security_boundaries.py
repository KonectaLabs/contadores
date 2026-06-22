"""Focused auth boundary tests for internal tokens, CSRF, and capabilities."""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.endpoints.campaigns as campaigns_endpoints
from backend.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, PrimitiveAuthManager, auth_manager
from backend.main import (
    app,
    internal_token_can_access,
    is_internal_only_machine_route,
    is_public_route,
)


def enable_auth(monkeypatch, tmp_path, auth_toml: str) -> None:
    """Enable primitive auth for one middleware test."""
    auth_path = tmp_path / "auth.toml"
    auth_path.write_text(auth_toml, encoding="utf-8")
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    auth_manager.reload_from_env()


def login_with_csrf(client: TestClient, user: str = "admin") -> dict[str, str]:
    """Login and return headers for one same-origin unsafe browser request."""
    login = client.post("/api/auth/login", json={"user": user, "password": "secret"})
    assert login.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token
    return {"Origin": "http://testserver", CSRF_HEADER_NAME: csrf_token}


def test_internal_token_is_scoped_to_machine_allowlist(monkeypatch, tmp_path) -> None:
    """The worker token should not authenticate operator/admin writes."""
    enable_auth(monkeypatch, tmp_path, "[users]\nadmin = \"secret\"\n")
    client = TestClient(app)
    internal_headers = {"X-Internal-Token": "test-internal-token"}

    assert client.get("/api/runtime", headers=internal_headers).status_code == 200
    assert internal_token_can_access("GET", "/api/runtime") is True

    denied = [
        ("POST", "/api/campaigns"),
        ("DELETE", "/api/campaigns/campaign-1"),
        ("POST", "/api/platform/meta-publish-attempts/attempt-1/approve"),
        ("POST", "/api/funnels"),
    ]
    for method, path in denied:
        response = client.request(method, path, headers=internal_headers, json={})
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication required."
        assert internal_token_can_access(method, path) is False


def test_machine_callback_routes_are_internal_only(monkeypatch, tmp_path) -> None:
    """Browser sessions should not call worker-only callback routes."""
    enable_auth(monkeypatch, tmp_path, "[users]\nadmin = \"secret\"\n")
    client = TestClient(app)

    login_with_csrf(client)
    browser_response = client.post("/api/contadores/whatsapp/inbound", json={})
    assert browser_response.status_code == 401
    assert browser_response.json()["detail"] == "Internal authentication required."
    assert is_internal_only_machine_route("POST", "/api/contadores/whatsapp/inbound") is True

    internal_response = client.post(
        "/api/contadores/whatsapp/inbound",
        headers={"X-Internal-Token": "test-internal-token"},
        json={},
    )
    assert internal_response.status_code == 422


def test_browser_session_unsafe_methods_require_origin_and_csrf(monkeypatch, tmp_path) -> None:
    """Cookie-authenticated mutations need same-origin evidence and a CSRF header."""
    enable_auth(monkeypatch, tmp_path, "[users]\nadmin = \"secret\"\n")
    client = TestClient(app)
    headers = login_with_csrf(client)

    missing_origin = client.post("/api/funnels", json={})
    assert missing_origin.status_code == 403
    assert missing_origin.json()["detail"] == "Same-origin browser request required."

    missing_token = client.post("/api/funnels", headers={"Origin": "http://testserver"}, json={})
    assert missing_token.status_code == 403
    assert missing_token.json()["detail"] == "Valid CSRF token required."

    cross_origin = client.post(
        "/api/funnels",
        headers={**headers, "Origin": "https://evil.example"},
        json={},
    )
    assert cross_origin.status_code == 403
    assert cross_origin.json()["detail"] == "Same-origin browser request required."

    valid_csrf = client.post("/api/funnels", headers=headers, json={})
    assert valid_csrf.status_code == 422


def test_public_routes_are_method_and_shape_allowlisted(monkeypatch, tmp_path) -> None:
    """Public-looking prefixes should not bypass auth unless the route shape is allowed."""
    enable_auth(monkeypatch, tmp_path, "[users]\nadmin = \"secret\"\n")
    monkeypatch.setattr(
        campaigns_endpoints.LeadCaptureCampaign,
        "get_by_slug",
        classmethod(lambda cls, public_slug: None),
    )
    client = TestClient(app)

    public_campaign = client.get("/c/missing/")
    public_campaign_api = client.get("/api/public/campaigns/missing")
    public_submission = client.post("/api/public/campaigns/missing/submissions", json={})
    reserved_campaign = client.get("/c/admin", follow_redirects=False)
    reserved_workstation = client.get("/p/admin/", follow_redirects=False)
    unexpected_public_api = client.get("/api/public/campaigns/missing/submissions")

    assert public_campaign.status_code == 404
    assert public_campaign_api.status_code == 404
    assert public_submission.status_code not in {401, 403}
    assert reserved_campaign.status_code == 303
    assert reserved_workstation.status_code == 303
    assert unexpected_public_api.status_code == 401
    assert is_public_route("GET", "/c/missing/") is True
    assert is_public_route("GET", "/c/admin") is False
    assert is_public_route("GET", "/p/admin/") is False
    assert is_public_route("POST", "/c/missing/") is False


def test_rich_auth_accounts_resolve_capabilities(monkeypatch, tmp_path) -> None:
    """Rich TOML users can be lower-privilege without changing simple users."""
    auth_path = tmp_path / "auth.toml"
    auth_path.write_text(
        """
[users.admin]
password = "secret"
role = "admin"

[users.viewer]
password = "secret"
role = "viewer"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_path))

    manager = PrimitiveAuthManager()
    manager.reload_from_env()

    assert manager.authenticate("admin", "secret") == "admin"
    assert manager.user_has_capability("admin", "campaigns:write") is True
    assert manager.authenticate("viewer", "secret") == "viewer"
    assert manager.user_has_capability("viewer", "campaigns:write") is False


def test_viewer_session_cannot_use_admin_mutations(monkeypatch, tmp_path) -> None:
    """Route-level capabilities should fail closed after CSRF passes."""
    enable_auth(
        monkeypatch,
        tmp_path,
        """
[users.admin]
password = "secret"
role = "admin"

[users.viewer]
password = "secret"
role = "viewer"
""".strip(),
    )

    viewer = TestClient(app)
    viewer_headers = login_with_csrf(viewer, user="viewer")
    viewer_response = viewer.post("/api/funnels", headers=viewer_headers, json={})
    assert viewer_response.status_code == 403
    assert viewer_response.json()["detail"] == "Missing capability: config:write."

    admin = TestClient(app)
    admin_headers = login_with_csrf(admin, user="admin")
    admin_response = admin.post("/api/funnels", headers=admin_headers, json={})
    assert admin_response.status_code == 422
