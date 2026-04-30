"""Tests for the public Codex image-generation endpoint."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.database as database_module
import backend.endpoints.public_image_generation as public_image_generation
from backend.main import app


def test_public_image_generation_returns_codex_output(monkeypatch, tmp_path) -> None:
    """The public endpoint should save inputs, run Codex, and return the generated image."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    calls: list[dict[str, object]] = []

    def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output path:\n"
        output_path = Path(prompt.split(output_marker, 1)[1].splitlines()[0].strip())
        output_path.write_bytes(b"generated-png")
        calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            final_response=f"created {output_path}",
            items_count=1,
            model="fake-model",
            effort="medium",
        )

    monkeypatch.setattr(public_image_generation, "run_codex_with_context", fake_run_codex_with_context)

    with TestClient(app) as client:
        response = client.post(
            "/api/public/image-generation",
            data={"prompt": "Hacer una imagen editorial con estas referencias"},
            files=[
                ("images", ("referencia.jpg", b"source-jpg", "image/jpeg")),
                ("images", ("logo.png", b"source-png", "image/png")),
            ],
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content == b"generated-png"
    assert len(calls) == 1
    assert len(calls[0]["local_images"]) == 2
    assert "Hacer una imagen editorial" in calls[0]["prompt"]
    assert (data_dir / "public-image-generations").is_dir()


def test_public_image_generation_is_not_blocked_by_cookie_auth(monkeypatch, tmp_path) -> None:
    """This endpoint is intentionally public even when the rest of the app requires login."""
    data_dir = tmp_path / "data"
    auth_file = tmp_path / "auth.toml"
    auth_file.write_text("[users]\nadmin = \"secret\"\n", encoding="utf-8")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_file))

    def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output path:\n"
        output_path = Path(prompt.split(output_marker, 1)[1].splitlines()[0].strip())
        output_path.write_bytes(b"public-output")
        return SimpleNamespace(
            final_response=f"created {output_path}",
            items_count=1,
            model="fake-model",
            effort="medium",
        )

    monkeypatch.setattr(public_image_generation, "run_codex_with_context", fake_run_codex_with_context)

    with TestClient(app) as client:
        public_response = client.post(
            "/api/public/image-generation",
            data={"prompt": "Generar una imagen sin login"},
        )
        protected_response = client.get("/api/runtime")

    assert public_response.status_code == 200
    assert public_response.content == b"public-output"
    assert protected_response.status_code == 401
