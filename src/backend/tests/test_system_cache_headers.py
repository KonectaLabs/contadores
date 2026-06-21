"""System response header tests."""

from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.main import app


def test_api_responses_are_not_cached() -> None:
    """API payloads should not be stored by browser or proxy caches."""
    with TestClient(app) as client:
        response = client.get("/api/runtime")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_health_response_keeps_default_cache_headers() -> None:
    """The no-store policy is scoped to API routes only."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_public_cloudflare_http_requests_redirect_to_https() -> None:
    """Cloudflare HTTP visitors should be upgraded before serving public pages."""
    with TestClient(app) as client:
        response = client.get(
            "/c/facu/",
            headers={"host": "crm.fgoiriz.com", "x-forwarded-proto": "http"},
            follow_redirects=False,
        )

    assert response.status_code == 308
    assert response.headers["location"] == "https://crm.fgoiriz.com/c/facu/"


def test_public_cloudflare_https_requests_do_not_redirect() -> None:
    """Cloudflare HTTPS visitors should not loop when origin traffic is HTTP."""
    with TestClient(app) as client:
        response = client.get(
            "/health",
            headers={"host": "crm.fgoiriz.com", "cf-visitor": '{"scheme":"https"}', "x-forwarded-proto": "http"},
        )

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_configured_public_crm_host_can_reach_public_route(monkeypatch) -> None:
    """Approved public CRM hosts should reach the public route handler."""
    monkeypatch.setattr(backend_main, "CRM_PUBLIC_HOSTS", {"crm.fgoiriz.com"})

    with TestClient(app) as client:
        response = client.get("/c/missing/", headers={"host": "crm.fgoiriz.com"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Campaign form not found."


def test_configured_public_crm_host_blocks_unknown_host(monkeypatch) -> None:
    """Public CRM routes should fail closed on unapproved hosts."""
    monkeypatch.setattr(backend_main, "CRM_PUBLIC_HOSTS", {"crm.fgoiriz.com"})

    with TestClient(app) as client:
        response = client.get(
            "/c/missing/",
            headers={"host": "unknown.fgoiriz.com", "x-forwarded-proto": "http"},
            follow_redirects=False,
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Public CRM host not found."


def test_public_image_generation_endpoint_is_removed() -> None:
    """The removed public image endpoint should not be advertised or routed."""
    with TestClient(app) as client:
        response = client.post("/api/public/image-generation", data={"prompt": "test"})
        openapi_response = client.get("/openapi.json")

    assert response.status_code == 404
    assert "/api/public/image-generation" not in openapi_response.json()["paths"]
