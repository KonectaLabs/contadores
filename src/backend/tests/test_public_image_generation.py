"""Tests for the public Codex image-generation endpoint."""

from __future__ import annotations

import base64
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


def test_public_image_generation_falls_back_to_openai_generation(monkeypatch, tmp_path) -> None:
    """If Codex fails without input images, use the Images API generation endpoint."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[dict[str, object]] = []

    def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        raise RuntimeError("codex login failed")

    def fake_call_openai_image_generation(*, api_key: str, prompt: str) -> dict[str, object]:
        calls.append({"api_key": api_key, "prompt": prompt, "type": "generation"})
        return {"data": [{"b64_json": base64.b64encode(b"fallback-png").decode("ascii")}]}

    monkeypatch.setattr(public_image_generation, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(public_image_generation, "call_openai_image_generation", fake_call_openai_image_generation)

    with TestClient(app) as client:
        response = client.post(
            "/api/public/image-generation",
            data={"prompt": "Generar una imagen fallback"},
        )

    assert response.status_code == 200
    assert response.content == b"fallback-png"
    assert calls == [{"api_key": "sk-test", "prompt": "Generar una imagen fallback", "type": "generation"}]


def test_public_image_generation_falls_back_to_openai_edit_with_images(monkeypatch, tmp_path) -> None:
    """If Codex fails with input images, pass those images to the Images API edit endpoint."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    calls: list[dict[str, object]] = []

    def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        raise RuntimeError("codex did not create output")

    def fake_call_openai_image_edit(
        *,
        api_key: str,
        prompt: str,
        input_paths: list[Path],
    ) -> dict[str, object]:
        calls.append(
            {
                "api_key": api_key,
                "prompt": prompt,
                "input_count": len(input_paths),
                "input_names": [path.name for path in input_paths],
            }
        )
        return {"data": [{"b64_json": base64.b64encode(b"fallback-edit-png").decode("ascii")}]}

    monkeypatch.setattr(public_image_generation, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(public_image_generation, "call_openai_image_edit", fake_call_openai_image_edit)

    with TestClient(app) as client:
        response = client.post(
            "/api/public/image-generation",
            data={"prompt": "Editar con referencias"},
            files=[
                ("images", ("referencia.jpg", b"source-jpg", "image/jpeg")),
                ("images", ("logo.png", b"source-png", "image/png")),
            ],
        )

    assert response.status_code == 200
    assert response.content == b"fallback-edit-png"
    assert calls[0]["api_key"] == "sk-test"
    assert calls[0]["prompt"] == "Editar con referencias"
    assert calls[0]["input_count"] == 2
    assert calls[0]["input_names"] == ["01-referencia.jpg", "02-logo.png"]


def test_public_image_generation_limits_openai_fallback_calls(monkeypatch, tmp_path) -> None:
    """Codex can be retried freely, but Images API fallback is capped in process."""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(public_image_generation, "openai_image_fallback_count", 0)
    api_call_count = 0

    def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        raise RuntimeError("codex failed")

    def fake_call_openai_image_generation(*, api_key: str, prompt: str) -> dict[str, object]:
        nonlocal api_call_count
        api_call_count += 1
        return {"data": [{"b64_json": base64.b64encode(b"fallback-png").decode("ascii")}]}

    monkeypatch.setattr(public_image_generation, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(public_image_generation, "call_openai_image_generation", fake_call_openai_image_generation)

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/public/image-generation",
                data={"prompt": f"Fallback {index}"},
            )
            for index in range(public_image_generation.OPENAI_IMAGE_FALLBACK_LIMIT + 1)
        ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429
    assert "fallback limit reached" in responses[10].json()["detail"].lower()
    assert api_call_count == public_image_generation.OPENAI_IMAGE_FALLBACK_LIMIT
