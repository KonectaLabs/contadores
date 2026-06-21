"""Focused tests for Workstation endpoint helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.endpoints.workstation as workstation_endpoints
from backend.endpoints.workstation import (
    build_conversation_text,
    copy_previous_landing_page_version,
    fallback_workstation_agent_decision,
    public_workstation_router,
    parse_workstation_agent_decision,
    resolve_public_page_file,
    workstation_router,
)


def test_build_conversation_text_preserves_media_context_without_text() -> None:
    """Media-only messages should not become blank lines in copy-all exports."""
    lead = SimpleNamespace(
        full_name="Ana Perez",
        phone="+5491111111111",
        normalized_phone="5491111111111",
        email="ana@example.com",
        funnel_id="contadores",
    )
    message = SimpleNamespace(
        from_me=False,
        created_at=datetime(2026, 5, 3, 15, 30, tzinfo=UTC),
        media_type="image",
        media_caption="Balance firmado",
        media_filename="balance.png",
        media_path="data/workstation/clients/ana/media/balance.png",
        text="",
    )

    transcript = build_conversation_text(lead, [message])

    assert "Cliente [image]: Balance firmado | balance.png | data/workstation/clients/ana/media/balance.png" in transcript


def test_build_conversation_text_marks_empty_media_messages() -> None:
    """A media message with no metadata should still be visible to operators."""
    lead = SimpleNamespace(
        full_name=None,
        phone="+5491111111111",
        normalized_phone="5491111111111",
        email=None,
        funnel_id="contadores",
    )
    message = SimpleNamespace(
        from_me=False,
        created_at=datetime(2026, 5, 3, 15, 30, tzinfo=UTC),
        media_type="audio",
        media_caption=None,
        media_filename=None,
        media_path=None,
        text=None,
    )

    transcript = build_conversation_text(lead, [message])

    assert "Cliente [audio]: (media sin texto)" in transcript


def test_parse_workstation_agent_decision_allows_text_reply() -> None:
    """The agent can choose a text answer instead of forcing another preview."""
    decision = parse_workstation_agent_decision(
        '{"action":"send_text","message":"Mandeme lo que quiere sumar y lo agrego.","reason":"asked how to add content"}'
    )

    assert decision.action == "send_text"
    assert "lo agrego" in decision.message


def test_fallback_workstation_agent_decision_answers_content_question() -> None:
    """A client question about content should not become a page revision."""
    decision = fallback_workstation_agent_decision("Y como hago para meterle todas las cosas que hice?")

    assert decision.action == "send_text"
    assert "Conteme" in decision.message


def test_fallback_workstation_agent_decision_asks_before_vague_trajectory_revision() -> None:
    """Vague factual copy requests should collect facts before revising."""
    decision = fallback_workstation_agent_decision("Tema de la trayectoria que coloquemos algo mas amplio")

    assert decision.action == "ask_for_details"
    assert "5 cosas" in decision.message
    assert "Desde que ano" in decision.message


def test_fallback_workstation_agent_decision_allows_concrete_revision() -> None:
    """Specific page changes can still become revisions."""
    decision = fallback_workstation_agent_decision("Agregale derecho migratorio, familia y contratos.")

    assert decision.action == "generate_or_revise_page"


def test_copy_previous_landing_page_version_preserves_design_files(tmp_path) -> None:
    """Revision folders should start from the prior HTML/CSS/JS instead of a blank redesign."""
    previous = tmp_path / "v001"
    next_version = tmp_path / "v002"
    (previous / "assets").mkdir(parents=True)
    next_version.mkdir()
    (previous / "index.html").write_text("<main>Original</main>", encoding="utf-8")
    (previous / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (previous / "script.js").write_text("console.log('same project');", encoding="utf-8")
    (previous / "assets" / "logo.txt").write_text("logo", encoding="utf-8")

    copy_previous_landing_page_version(previous_version=previous, version_dir=next_version)

    assert (next_version / "index.html").read_text(encoding="utf-8") == "<main>Original</main>"
    assert (next_version / "styles.css").read_text(encoding="utf-8") == "body { color: black; }"
    assert (next_version / "script.js").read_text(encoding="utf-8") == "console.log('same project');"
    assert (next_version / "assets" / "logo.txt").read_text(encoding="utf-8") == "logo"


def test_public_workstation_page_serves_only_approved_assets(tmp_path, monkeypatch) -> None:
    """Public trial URLs should expose page files, not mixed internal artifacts."""
    version_dir = tmp_path / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("body{}", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")
    (version_dir / "assets" / "logo.png").write_bytes(b"png")
    for filename in ["metadata.json", "preview-message.txt", "outbound-messages.json", "preview.mp4"]:
        (version_dir / filename).write_text("private", encoding="utf-8")

    monkeypatch.setattr(
        workstation_endpoints,
        "get_public_page_or_404",
        lambda public_token: SimpleNamespace(public_token=public_token),
    )
    monkeypatch.setattr(workstation_endpoints, "resolve_public_page_version_dir", lambda public_page: version_dir)

    app = FastAPI()
    app.include_router(public_workstation_router)
    client = TestClient(app)

    page = client.get("/p/token/")
    stylesheet = client.get("/p/token/styles.css")
    assert page.status_code == 200
    assert "connect-src 'none'" in page.headers["content-security-policy"]
    assert "frame-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "geolocation=()" in page.headers["permissions-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    assert page.headers["cache-control"] == "no-store"
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-security-policy"] == page.headers["content-security-policy"]
    assert stylesheet.headers["x-content-type-options"] == "nosniff"
    assert stylesheet.headers["cache-control"] == "no-store"
    redirect = client.get("/p/token", follow_redirects=False)
    assert redirect.status_code == 307
    assert redirect.headers["cache-control"] == "no-store"
    assert client.get("/p/token/script.js").status_code == 200
    assert client.get("/p/token/assets/logo.png").status_code == 200
    assert client.get("/p/token/metadata.json").status_code == 404
    assert client.get("/p/token/preview-message.txt").status_code == 404
    assert client.get("/p/token/outbound-messages.json").status_code == 404
    assert client.get("/p/token/preview.mp4").status_code == 404


def test_resolve_public_page_file_rejects_traversal_and_hidden_assets(tmp_path, monkeypatch) -> None:
    """Traversal and hidden files stay unavailable even when they exist."""
    version_dir = tmp_path / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (version_dir / "assets" / ".secret").write_text("secret", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    public_page = SimpleNamespace(public_token="token")
    monkeypatch.setattr(workstation_endpoints, "resolve_public_page_version_dir", lambda public_page: version_dir)

    assert resolve_public_page_file(public_page, "index.html") == (version_dir / "index.html").resolve()
    for asset_path in ["../secret.txt", "assets/.secret", "assets//logo.png", "/etc/passwd", r"assets\\logo.png"]:
        try:
            resolve_public_page_file(public_page, asset_path)
        except workstation_endpoints.HTTPException as error:
            assert error.status_code == 404
        else:
            raise AssertionError(f"Expected 404 for {asset_path}")


def test_workstation_media_file_serving_downgrades_unsafe_types(tmp_path, monkeypatch) -> None:
    """Uploaded SVG/HTML-like files should not preview inline on the CRM origin."""
    svg_path = tmp_path / "danger.svg"
    png_path = tmp_path / "photo.png"
    svg_path.write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
    png_path.write_bytes(b"png")
    paths = {
        "data/workstation/clients/ana/media/danger.svg": svg_path,
        "data/workstation/clients/ana/media/photo.png": png_path,
    }
    assets = {
        "svg": SimpleNamespace(
            id="svg",
            stored_path="data/workstation/clients/ana/media/danger.svg",
            original_filename="danger.svg",
            content_type="image/svg+xml",
        ),
        "png": SimpleNamespace(
            id="png",
            stored_path="data/workstation/clients/ana/media/photo.png",
            original_filename="photo.png",
            content_type="image/png",
        ),
    }
    monkeypatch.setattr(workstation_endpoints.WorkstationMediaAsset, "get_by_id", lambda asset_id: assets.get(asset_id))
    monkeypatch.setattr(workstation_endpoints, "resolve_media_path", lambda stored_path: paths.get(stored_path))

    app = FastAPI()
    app.include_router(workstation_router)
    client = TestClient(app)

    unsafe = client.get("/api/workstation/media/svg/file")
    safe = client.get("/api/workstation/media/png/file")

    assert unsafe.status_code == 200
    assert unsafe.headers["content-type"] == "application/octet-stream"
    assert unsafe.headers["content-disposition"].startswith("attachment")
    assert unsafe.headers["x-content-type-options"] == "nosniff"
    assert safe.status_code == 200
    assert safe.headers["content-type"] == "image/png"
    assert safe.headers["content-disposition"].startswith("inline")
    assert safe.headers["x-content-type-options"] == "nosniff"


def test_professional_photo_payload_rejects_too_many_images(tmp_path) -> None:
    """Codex vision payloads should cap reference count before invocation."""
    paths = []
    for index in range(workstation_endpoints.WORKSTATION_PRO_PHOTO_CREATE_MAX_IMAGES + 1):
        path = tmp_path / f"image-{index}.jpg"
        path.write_bytes(b"jpg")
        paths.append(path)

    with pytest.raises(workstation_endpoints.HTTPException) as raised:
        workstation_endpoints.validate_professional_photo_vision_payload(
            image_paths=paths,
            max_images=workstation_endpoints.WORKSTATION_PRO_PHOTO_CREATE_MAX_IMAGES,
        )

    assert raised.value.status_code == 400
    assert "Too many" in raised.value.detail


def test_professional_photo_payload_rejects_oversized_image(tmp_path, monkeypatch) -> None:
    """Individual image bytes are capped before Codex sees local_images."""
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PRO_PHOTO_MAX_IMAGE_BYTES", 3)
    path = tmp_path / "large.jpg"
    path.write_bytes(b"1234")

    with pytest.raises(workstation_endpoints.HTTPException) as raised:
        workstation_endpoints.validate_professional_photo_vision_payload(image_paths=[path], max_images=1)

    assert raised.value.status_code == 400
    assert "too large" in raised.value.detail


def test_professional_photo_payload_rejects_oversized_total(tmp_path, monkeypatch) -> None:
    """Total image bytes include every image sent to Codex."""
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PRO_PHOTO_MAX_IMAGE_BYTES", 100)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PRO_PHOTO_MAX_TOTAL_IMAGE_BYTES", 5)
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"123")
    second.write_bytes(b"456")

    with pytest.raises(workstation_endpoints.HTTPException) as raised:
        workstation_endpoints.validate_professional_photo_vision_payload(image_paths=[first, second], max_images=2)

    assert raised.value.status_code == 400
    assert "together" in raised.value.detail


def test_professional_photo_text_caps_are_model_validated() -> None:
    """Create context and edit prompt are bounded at request parsing."""
    with pytest.raises(ValueError):
        workstation_endpoints.CreateProfessionalPhotoCommand(
            media_asset_ids=["asset-1"],
            context="x" * (workstation_endpoints.WORKSTATION_PRO_PHOTO_MAX_CONTEXT_CHARS + 1),
        )
    with pytest.raises(ValueError):
        workstation_endpoints.EditProfessionalPhotoCommand(
            base_version="v001",
            prompt="x" * (workstation_endpoints.WORKSTATION_PRO_PHOTO_MAX_PROMPT_CHARS + 1),
        )
