"""Tests for platform creative asset upload and serving safety."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

import backend.database as database_module
import backend.endpoints.platform as platform
from backend.database import AgentRun, ContadoresLead, ContadoresRuntimeAlert, PlatformEvent
from backend.main import app
from backend.tests.support import configure_contadores_db


def test_classify_creative_asset_type_rejects_svg_and_misleading_extensions() -> None:
    """SVG/HTML/JS/XML uploads should not be treated as safe inline media."""
    unsafe_cases = [
        ("image/svg+xml", "logo.svg"),
        ("image/png", "fake.svg"),
        ("image/png", "fake.html"),
        ("text/html", "photo.png"),
        ("application/javascript", "photo.jpg"),
    ]

    for content_type, filename in unsafe_cases:
        with pytest.raises(HTTPException) as error:
            platform.classify_creative_asset_type(content_type, filename)
        assert error.value.status_code == 400


def test_classify_creative_asset_type_allows_safe_images_and_videos() -> None:
    """Normal image/video uploads should keep preview behavior."""
    assert platform.classify_creative_asset_type("image/png", "photo.png") == "image"
    assert platform.classify_creative_asset_type("video/mp4", "clip.mp4") == "video"


@pytest.mark.anyio
async def test_get_creative_asset_file_serves_safe_media_inline_with_nosniff(monkeypatch, tmp_path) -> None:
    """Safe image/video files should still preview inline."""
    media_path = tmp_path / "photo.png"
    media_path.write_bytes(b"png")

    monkeypatch.setattr(
        platform.PlatformCreativeAsset,
        "get_by_id",
        lambda asset_id: SimpleNamespace(id=asset_id, file_path="data/platform/creative-assets/photo.png"),
    )
    monkeypatch.setattr(platform, "resolve_creative_asset_file", lambda file_path: media_path)

    response = await platform.get_creative_asset_file("asset-1")

    assert response.media_type == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith('inline; filename="photo.png"')


@pytest.mark.anyio
async def test_get_creative_asset_file_serves_svg_as_attachment_octet_stream(monkeypatch, tmp_path) -> None:
    """Stored dangerous files should download instead of rendering inline."""
    media_path = tmp_path / "logo.svg"
    media_path.write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")

    monkeypatch.setattr(
        platform.PlatformCreativeAsset,
        "get_by_id",
        lambda asset_id: SimpleNamespace(id=asset_id, file_path="data/platform/creative-assets/logo.svg"),
    )
    monkeypatch.setattr(platform, "resolve_creative_asset_file", lambda file_path: media_path)

    response = await platform.get_creative_asset_file("asset-1")

    assert response.media_type == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith('attachment; filename="logo.svg"')


def test_platform_event_filters_compose(monkeypatch, tmp_path) -> None:
    """Operators should be able to narrow events by diagnostic fields."""
    configure_contadores_db(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    PlatformEvent.add(
        event_type="runtime.error",
        severity="error",
        source="bot",
        target_type="worker",
        target_id="bot",
        funnel_id="contadores",
        correlation_id="req-filter-1",
        created_at=now - timedelta(minutes=5),
    )
    PlatformEvent.add(
        event_type="runtime.info",
        severity="info",
        source="backend",
        target_type="worker",
        target_id="backend",
        funnel_id="abogados",
        correlation_id="req-filter-2",
        created_at=now - timedelta(hours=2),
    )

    response = TestClient(app).get(
        "/api/platform/events",
        params={
            "event_type": "runtime.error",
            "severity": "error",
            "source": "bot",
            "correlation_id": "req-filter-1",
            "created_after": (now - timedelta(minutes=10)).isoformat(),
            "created_before": now.isoformat(),
        },
    )

    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["event_type"] for event in events] == ["runtime.error"]
    assert events[0]["correlation_id"] == "req-filter-1"


def test_platform_overview_surfaces_runtime_alerts_and_stale_runs(monkeypatch, tmp_path) -> None:
    """Overview should show open runtime alerts and stale running Codex runs."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("CODEX_AGENT_RUN_STALE_AFTER_SECONDS", "60")
    lead = ContadoresLead.upsert(
        external_lead_id="runtime-alert-lead",
        phone="+5491111111111",
        full_name="Runtime Alert",
    )
    open_alert = ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="codex_fallback",
        error="Codex crashed with a long provider error " * 20,
        fallback_action="operator_review",
        latest_inbound_text="Necesito ayuda " * 40,
    )
    resolved_alert = ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="resolved",
        error="Already resolved",
        fallback_action="none",
        latest_inbound_text="ok",
    )
    ContadoresRuntimeAlert.mark_resolved(
        alert_id=int(resolved_alert.id or 0),
        operator_reply_text="resolved",
    )
    stale = AgentRun.start(
        run_id="run-stale",
        agent_kind="codex",
        target_type="lead",
        target_id=lead.id,
    )
    AgentRun.start(
        run_id="run-fresh",
        agent_kind="codex",
        target_type="lead",
        target_id=lead.id,
    )
    with Session(database_module.engine) as session:
        row = session.get(AgentRun, stale.id)
        row.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        session.add(row)
        session.commit()

    response = TestClient(app).get("/api/platform/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["unresolved_runtime_alerts"] == 1
    assert payload["counts"]["unnotified_runtime_alerts"] == 1
    assert payload["counts"]["stale_agent_runs"] == 1
    assert payload["runtime_alerts"][0]["id"] == open_alert.id
    assert payload["runtime_alerts"][0]["resolved_at"] is None
    assert payload["stale_agent_runs"][0]["id"] == "run-stale"
    assert payload["stale_agent_runs"][0]["stale"] is True
    assert payload["counts"]["active_blockers"] >= 2


def test_request_id_header_is_preserved_and_used_for_platform_events(monkeypatch, tmp_path) -> None:
    """Request IDs should appear on responses and endpoint-originated events."""
    configure_contadores_db(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/platform/meetings",
        headers={"X-Request-ID": "req-platform-1"},
        json={"lead_id": "lead-correlation", "funnel_id": "contadores"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-platform-1"
    events = client.get(
        "/api/platform/events",
        params={
            "event_type": "meeting.record_created",
            "correlation_id": "req-platform-1",
        },
    ).json()["events"]
    assert len(events) == 1
    assert events[0]["target_id"] == response.json()["id"]


def test_invalid_request_id_is_replaced(monkeypatch, tmp_path) -> None:
    """Oversized or unsafe request ids should not be reflected."""
    configure_contadores_db(monkeypatch, tmp_path)

    response = TestClient(app).get("/health", headers={"X-Request-ID": "bad request id!"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad request id!"
    assert len(response.headers["X-Request-ID"]) == 16
