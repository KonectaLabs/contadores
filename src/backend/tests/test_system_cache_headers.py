"""System response header tests."""

from fastapi.testclient import TestClient

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


def test_public_image_generation_endpoint_is_removed() -> None:
    """The removed public image endpoint should not be advertised or routed."""
    with TestClient(app) as client:
        response = client.post("/api/public/image-generation", data={"prompt": "test"})
        openapi_response = client.get("/openapi.json")

    assert response.status_code == 404
    assert "/api/public/image-generation" not in openapi_response.json()["paths"]
