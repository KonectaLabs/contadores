"""Regression tests for the dedicated Contadores flow."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from io import BytesIO, StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import backend.calendar_events as calendar_events_module
import backend.database as database_module
import backend.ai.codex_agent_runtime as codex_agent_runtime
import backend.endpoints.contadores as contadores_endpoints
import backend.endpoints.workstation as workstation_endpoints
import backend.meta_ads_publish as meta_ads_publish_module
import backend.meta_lead_forms as meta_lead_forms_module
import backend.platform_profile_extraction as profile_extraction_module
from backend.audio_transcription import AudioTranscriptionError
from backend.codex_utils import CodexSkill, CodexTurnResult
from backend.meta_ads_inventory import sync_meta_inventory
from backend.ai.contadores_conversation_bot import ContadoresConversationBotResult, REJECTION_SURVEY_REPLY
from backend.contadores_strategies import get_contadores_strategy
from backend.database import (
    AgentRun,
    AgentToolCall,
    ClientLeadSource,
    CONTADORES_LEAD_MANUAL_CONVERTED_REASON,
    ContadoresAlertDelivery,
    ContadoresConfig,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresRuntimeAlert,
    ContadoresSheetSyncState,
    ContadoresStrategyAssignment,
    MessageDeliveryStatus,
    PlatformAdCampaign,
    PlatformClientProfile,
    PlatformClientUpdate,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformHumanQuestion,
    PlatformMetaInventorySnapshot,
    PlatformMeeting,
    PlatformMetaPublishAttempt,
    ScheduledAgentTask,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
    WorkstationMediaAsset,
    WorkstationPublicPage,
    build_contadores_external_lead_id,
)
from backend.funnel_config import get_funnel
from backend.ai.codex_agent_tools import call_tool
from backend.main import app
from backend.tests.support import (
    add_recent_inbound,
    build_abogados_test_funnel,
    build_contadores_test_funnel,
    configure_contadores_db,
    fake_profile_extraction,
    now_utc,
    write_funnels_config,
)



def test_drop_legacy_contadores_events_table(monkeypatch, tmp_path) -> None:
    """Existing event timeline tables should be removed during database setup."""
    configure_contadores_db(monkeypatch, tmp_path)
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE contadores_events (id INTEGER PRIMARY KEY, summary TEXT)")

    with database_module.engine.connect() as connection:
        assert "contadores_events" in database_module.inspect(connection).get_table_names()

    database_module.drop_legacy_contadores_events_table()

    with database_module.engine.connect() as connection:
        assert "contadores_events" not in database_module.inspect(connection).get_table_names()


def test_schema_migration_ledger_runs_legacy_drop_once(monkeypatch, tmp_path) -> None:
    """The destructive legacy event-table drop should be a named one-time migration."""
    configure_contadores_db(monkeypatch, tmp_path)
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE contadores_events (id INTEGER PRIMARY KEY, summary TEXT)")

    applied = database_module.run_schema_migrations()

    assert applied == ["20260621_drop_legacy_contadores_events_table"]
    assert [row.name for row in database_module.list_applied_schema_migrations()] == [
        "20260621_drop_legacy_contadores_events_table"
    ]
    with database_module.engine.connect() as connection:
        assert "contadores_events" not in database_module.inspect(connection).get_table_names()

    with database_module.engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE contadores_events (id INTEGER PRIMARY KEY, summary TEXT)")

    assert database_module.run_schema_migrations() == []
    with database_module.engine.connect() as connection:
        assert "contadores_events" in database_module.inspect(connection).get_table_names()


def test_schema_verify_passes_after_identity_indexes(monkeypatch, tmp_path) -> None:
    """Schema verification should report the identity indexes created by startup."""
    configure_contadores_db(monkeypatch, tmp_path)

    database_module.ensure_client_lead_delivery_external_id_index()
    database_module.ensure_client_lead_source_meta_form_id_index()
    database_module.ensure_contadores_message_external_id_index()
    database_module.ensure_scheduled_agent_task_idempotency_index()
    database_module.ensure_platform_logical_identity_indexes()

    assert database_module.verify_schema() == []


def test_file_backed_funnel_config_is_source_of_truth(monkeypatch, tmp_path) -> None:
    """A non-default funnel should not inherit legacy Contadores runtime fields."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("FUNNELS_SEED_CONFIG_PATH", str(tmp_path / "missing-seed.json"))
    ContadoresConfig.update(
        enabled=True,
        sheet_url="https://docs.google.com/spreadsheets/d/contadores",
        sheet_gid="0",
        loom_url="https://loom.example/contadores",
        calendly_base_url="https://calendly.com/contadores",
        alert_emails=["contadores@example.com"],
        initial_reply_quiet_seconds=99,
        post_loom_min_seconds=999,
        post_loom_quiet_seconds=88,
        strategy_weights={"loom": {"legacy": 100}},
    )
    abogados = build_abogados_test_funnel(initial_reply_quiet_seconds=7)
    abogados.update(
        {
            "sheet_url": "https://docs.google.com/spreadsheets/d/abogados",
            "sheet_gid": "123",
            "loom_url": "https://loom.example/abogados",
            "calendly_base_url": "https://calendly.com/abogados",
            "alert_emails": ["abogados@example.com"],
            "post_loom_min_seconds": 600,
            "post_loom_quiet_seconds": 9,
        }
    )
    write_funnels_config(tmp_path, abogados)

    config = contadores_endpoints.get_effective_funnel_config("abogados")
    fallback = contadores_endpoints.get_effective_funnel_config("contadores")

    assert config.sheet_url == "https://docs.google.com/spreadsheets/d/abogados"
    assert config.sheet_gid == "123"
    assert config.loom_url == "https://loom.example/abogados"
    assert config.calendly_base_url == "https://calendly.com/abogados"
    assert config.alert_emails == ["abogados@example.com"]
    assert config.initial_reply_quiet_seconds == 7
    assert config.post_loom_min_seconds == 600
    assert config.post_loom_quiet_seconds == 9
    assert config.strategy_weights == {"loom": {"loom_mp4": 100}}
    assert fallback.sheet_url == "https://docs.google.com/spreadsheets/d/contadores"
    assert fallback.loom_url == "https://loom.example/contadores"


def test_contadores_sheet_sync_state_is_per_funnel(monkeypatch, tmp_path) -> None:
    """Scheduled sheet sync state should survive outside the bot process."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_abogados_test_funnel())

    with TestClient(app) as client:
        running = client.post(
            "/api/contadores/sheet-sync-state",
            json={"funnel_id": "abogados", "status": "running", "note": "scheduled sync started"},
        )
        imported = client.post(
            "/api/contadores/leads/import",
            json={
                "funnel_id": "abogados",
                "rows": [
                    {
                        "id": "shared-row",
                        "phone_number": "+5491111111199",
                        "full_name": "Abogada Sync",
                    }
                ],
            },
        )
        config = client.get("/api/contadores/config", params={"funnel_id": "abogados"})

    sync_state = ContadoresSheetSyncState.get("abogados")
    assert running.status_code == 200
    assert running.json()["last_sheet_sync_status"] == "running"
    assert imported.status_code == 200
    assert sync_state is not None
    assert sync_state.last_sync_status == "ok"
    assert sync_state.last_success_at is not None
    assert ContadoresSheetSyncState.get("contadores") is None
    assert config.json()["last_sheet_sync_status"] == "ok"
    assert config.json()["last_sheet_sync_success_at"] is not None


def test_runtime_endpoint_reports_sheet_readiness(monkeypatch, tmp_path) -> None:
    """Runtime status should expose non-secret sheet readiness."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_contadores_test_funnel())

    with TestClient(app) as client:
        response = client.get("/api/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sheet_configured"] is True
    assert payload["sheet_gid_configured"] is True
    assert payload["sheet_gid_label"] == "0"
    assert payload["ready"] is True
    assert payload["ready_campaign_funnels"] == ["contadores"]
    assert payload["funnel_config_path_label"] == "funnels.json"


def test_runtime_endpoint_requires_sheet_gid(monkeypatch, tmp_path) -> None:
    """Runtime readiness should fail when the sheet gid is missing."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("FUNNELS_SEED_CONFIG_PATH", str(tmp_path / "missing-seed.json"))
    funnel = build_abogados_test_funnel()
    funnel["id"] = "contadores"
    funnel["label"] = "Contadores"
    funnel["sheet_url"] = "https://docs.google.com/spreadsheets/d/example"
    funnel["sheet_gid"] = None
    (tmp_path / "funnels.json").write_text(
        json.dumps({"version": 1, "funnels": [funnel]}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        runtime_response = client.get("/api/runtime")
        health_response = client.get("/health")

    assert runtime_response.status_code == 200
    payload = runtime_response.json()
    assert payload["sheet_configured"] is False
    assert payload["ready"] is False
    assert payload["readiness_issues"] == [
        "No enabled campaign funnel has both sheet_url and sheet_gid.",
        "contadores: sheet_gid is empty.",
    ]
    assert health_response.status_code == 200
    assert health_response.json()["ready"] is False


def test_runtime_endpoint_accepts_file_backed_campaign_readiness(monkeypatch, tmp_path) -> None:
    """A fresh install can become ready from any enabled configured campaign funnel."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("FUNNELS_SEED_CONFIG_PATH", str(tmp_path / "missing-seed.json"))
    monkeypatch.delenv("CONTADORES_SHEET_URL", raising=False)
    monkeypatch.delenv("CONTADORES_SHEET_GID", raising=False)
    funnel = build_abogados_test_funnel()
    funnel["sheet_url"] = "https://docs.google.com/spreadsheets/d/new-client"
    funnel["sheet_gid"] = "987654321"
    (tmp_path / "funnels.json").write_text(
        json.dumps({"version": 1, "funnels": [funnel]}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        runtime_response = client.get("/api/runtime")
        health_response = client.get("/health")

    assert runtime_response.status_code == 200
    payload = runtime_response.json()
    assert payload["ready"] is True
    assert payload["sheet_configured"] is True
    assert payload["ready_campaign_funnels"] == ["abogados"]
    assert payload["enabled_campaign_funnels"] == ["abogados"]
    assert health_response.status_code == 200
    assert health_response.json()["ready"] is True


def test_contadores_import_skips_invalid_phone_rows(monkeypatch, tmp_path) -> None:
    """One malformed sheet phone should not fail the whole import batch."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/leads/import",
            json={
                "rows": [
                    {
                        "id": "sheet-invalid-phone",
                        "phone_number": "sin telefono",
                        "full_name": "Invalid Phone",
                    },
                    {
                        "id": "sheet-valid-phone",
                        "phone_number": "+5491111111111",
                        "full_name": "Valid Phone",
                    },
                ]
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imported"] == 1
    assert payload["updated"] == 0
    assert payload["skipped"] == 1
    assert len(payload["lead_ids"]) == 1
    assert ContadoresLead.get_by_external_lead_id("sheet-invalid-phone") is None
    assert ContadoresLead.get_by_external_lead_id("sheet-valid-phone") is not None


def test_contadores_import_scopes_external_ids_by_funnel(monkeypatch, tmp_path) -> None:
    """The same sheet row id can be imported by two funnels without moving ownership."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        contadores_response = client.post(
            "/api/contadores/leads/import",
            json={
                "funnel_id": "contadores",
                "rows": [{"id": "shared-row", "phone_number": "+5491111111200", "full_name": "Contador"}],
            },
        )
        abogados_response = client.post(
            "/api/contadores/leads/import",
            json={
                "funnel_id": "abogados",
                "rows": [{"id": "shared-row", "phone_number": "+5491111111201", "full_name": "Abogada"}],
            },
        )

    contadores_lead = ContadoresLead.get_by_external_lead_id("shared-row", funnel_id="contadores")
    abogados_external_id = build_contadores_external_lead_id(funnel_id="abogados", source_row_id="shared-row")
    abogados_lead = ContadoresLead.get_by_external_lead_id(abogados_external_id, funnel_id="abogados")
    assert contadores_response.status_code == 200
    assert abogados_response.status_code == 200
    assert contadores_lead is not None
    assert abogados_lead is not None
    assert contadores_lead.id != abogados_lead.id
    assert contadores_lead.funnel_id == "contadores"
    assert abogados_lead.funnel_id == "abogados"
    with pytest.raises(ValueError, match="another funnel"):
        ContadoresLead.upsert(
            funnel_id="abogados",
            external_lead_id="shared-row",
            phone="+5491111111202",
        )
    assert ContadoresLead.get_by_external_lead_id("shared-row").funnel_id == "contadores"


def test_contadores_sparse_sheet_import_preserves_existing_lead_fields(monkeypatch, tmp_path) -> None:
    """A later sparse sheet row should not erase useful CRM fields."""
    configure_contadores_db(monkeypatch, tmp_path)
    first_created = datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc)
    updated_created = datetime(2026, 6, 2, 9, 15, tzinfo=timezone.utc)

    with TestClient(app) as client:
        first = client.post(
            "/api/contadores/leads/import",
            json={
                "rows": [
                    {
                        "id": "sheet-sparse-preserve",
                        "phone_number": "+5491111111122",
                        "full_name": "Rich Lead",
                        "email": "rich@example.com",
                        "platform": "fb",
                        "lead_status": "new",
                        "created_time": first_created.isoformat(),
                    }
                ]
            },
        )
        sparse = client.post(
            "/api/contadores/leads/import",
            json={"rows": [{"id": "sheet-sparse-preserve", "phone_number": "+5491111111133"}]},
        )
        lead_after_sparse = ContadoresLead.get_by_external_lead_id("sheet-sparse-preserve")
        richer_update = client.post(
            "/api/contadores/leads/import",
            json={
                "rows": [
                    {
                        "id": "sheet-sparse-preserve",
                        "phone_number": "+5491111111133",
                        "full_name": "Updated Lead",
                        "email": "updated@example.com",
                        "platform": "ig",
                        "lead_status": "qualified",
                        "created_time": updated_created.isoformat(),
                    }
                ]
            },
        )

    lead = ContadoresLead.get_by_external_lead_id("sheet-sparse-preserve")
    assert first.status_code == 200
    assert first.json()["imported"] == 1
    assert sparse.status_code == 200
    assert sparse.json()["updated"] == 1
    assert lead_after_sparse is not None
    assert lead_after_sparse.phone == "+5491111111133"
    assert lead_after_sparse.full_name == "Rich Lead"
    assert lead_after_sparse.email == "rich@example.com"
    assert lead_after_sparse.platform == "fb"
    assert lead_after_sparse.lead_status == "new"
    assert lead_after_sparse.sheet_created_time is not None
    assert lead_after_sparse.sheet_created_time.replace(tzinfo=timezone.utc) == first_created
    assert richer_update.status_code == 200
    assert richer_update.json()["updated"] == 1
    assert lead is not None
    assert lead.phone == "+5491111111133"
    assert lead.full_name == "Updated Lead"
    assert lead.email == "updated@example.com"
    assert lead.platform == "ig"
    assert lead.lead_status == "qualified"
    assert lead.sheet_created_time is not None
    assert lead.sheet_created_time.replace(tzinfo=timezone.utc) == updated_created


def test_contadores_lead_search_matches_message_text(monkeypatch, tmp_path) -> None:
    """The CRM search box should find leads by text from the chat timeline."""
    configure_contadores_db(monkeypatch, tmp_path)
    matching = ContadoresLead.upsert(
        external_lead_id="sheet-row-message-search",
        phone="+5491111111180",
        full_name="Message Search Lead",
    )
    other = ContadoresLead.upsert(
        external_lead_id="sheet-row-message-other",
        phone="+5491111111181",
        full_name="Other Lead",
    )
    ContadoresMessage.add(
        lead_id=matching.id,
        from_me=False,
        text="Me pasas el presupuesto especial para mayo?",
    )
    ContadoresMessage.add(
        lead_id=other.id,
        from_me=False,
        text="Quiero coordinar una llamada.",
    )

    with TestClient(app) as client:
        response = client.get("/api/contadores/leads?query=presupuesto especial&funnel_id=contadores")

    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["total"] == 1
    assert [item["id"] for item in payload["leads"]] == [matching.id]


def test_contadores_pending_delivery_keeps_full_mp4_sequence(monkeypatch, tmp_path) -> None:
    """Loom intro and WhatsApp MP4 must both remain visible to the bot outbox."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_contadores_test_funnel())
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-1",
        phone="+5491111111111",
        full_name="Ana Perez",
    )
    add_recent_inbound(lead.id)

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_mp4")

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert [item["sequence_step"] for item in payload["messages"]] == ["loom_intro", "loom_video"]
    assert [item["strategy_id"] for item in payload["messages"]] == ["loom_mp4", "loom_mp4"]


def test_contadores_pending_delivery_exposes_loom_mp4_media(monkeypatch, tmp_path) -> None:
    """The MP4 strategy must expose explicit media metadata for bot dispatch."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_contadores_test_funnel())
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-mp4",
        phone="+5491111111112",
        full_name="Media Lead",
    )
    add_recent_inbound(lead.id)

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_mp4")

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert [item["sequence_step"] for item in payload["messages"]] == ["loom_intro", "loom_video"]
    assert payload["messages"][1]["media_type"] == "video"
    assert payload["messages"][1]["media_path"] == "data/contadores/videos/loom_60_seconds_captions.mp4"
    assert [item["strategy_id"] for item in payload["messages"]] == ["loom_mp4", "loom_mp4"]


def test_contadores_pending_delivery_claim_reserves_rows(monkeypatch, tmp_path) -> None:
    """Claiming pending rows should reserve them before bot dispatch."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-claim",
        phone="+5491111111199",
        full_name="Claim Lead",
    )
    first = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Primero",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="opener",
        dispatch_after=now_utc() - timedelta(seconds=5),
    )
    second = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Segundo",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="loom_url",
        dispatch_after=now_utc() - timedelta(seconds=5),
    )

    with TestClient(app) as client:
        read_only = client.get("/api/contadores/messages/pending-delivery?limit=2")
        claimed = client.post(
            "/api/contadores/messages/pending-delivery/claim",
            json={"limit": 1, "lease_seconds": 300},
        )
        after_claim = client.get("/api/contadores/messages/pending-delivery?limit=2")
        second_claim = client.post(
            "/api/contadores/messages/pending-delivery/claim",
            json={"limit": 2, "lease_seconds": 300},
        )

    assert read_only.status_code == 200
    assert [item["message_id"] for item in read_only.json()["messages"]] == [first.id, second.id]
    assert claimed.status_code == 200
    assert [item["message_id"] for item in claimed.json()["messages"]] == [first.id]
    assert after_claim.status_code == 200
    assert [item["message_id"] for item in after_claim.json()["messages"]] == [second.id]
    assert second_claim.status_code == 200
    assert [item["message_id"] for item in second_claim.json()["messages"]] == [second.id]
    assert ContadoresMessage.get_by_id(first.id).dispatch_after.replace(tzinfo=timezone.utc) > now_utc()
    assert ContadoresMessage.get_by_id(second.id).dispatch_after.replace(tzinfo=timezone.utc) > now_utc()


def test_contadores_text_offer_strategy_queues_one_message(monkeypatch, tmp_path) -> None:
    """Mission offer funnels should not need a Loom video when configured as text."""
    configure_contadores_db(monkeypatch, tmp_path)
    text_offer = "Son 599 USD mensuales. A cambio recibis oportunidades directo a tu WhatsApp."
    write_funnels_config(
        tmp_path,
        build_contadores_test_funnel(
            loom_intro_text="",
            strategies=[
                {
                    "step": "loom",
                    "id": "text_offer_599",
                    "label": "Text offer 599",
                    "weight": 100,
                    "delivery": "text",
                    "sequence_step": "text_offer",
                    "message_text": text_offer,
                    "media_type": None,
                    "media_path": None,
                    "media_caption": None,
                }
            ],
        ),
    )
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-text-offer",
        phone="+5491111111199",
        full_name="Texto Oferta",
    )
    add_recent_inbound(lead.id)

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="text_offer_599")

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")
        events_response = client.get(f"/api/platform/events?target_type=lead&target_id={lead.id}")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [item["sequence_step"] for item in messages] == ["text_offer"]
    assert messages[0]["text"] == text_offer
    assert messages[0]["media_type"] is None
    assert messages[0]["strategy_id"] == "text_offer_599"
    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert events[0]["event_type"] == "whatsapp.outbound_queued"
    assert events[0]["lifecycle_stage"] == "text_offer"
    assert events[0]["target_type"] == "lead"
    assert events[0]["target_id"] == lead.id
    assert events[0]["funnel_id"] == "contadores"
    assert events[0]["payload"]["message_id"] == messages[0]["message_id"]


def test_contadores_delivery_failure_retries_then_surfaces_error(monkeypatch, tmp_path) -> None:
    """Delivery failures should retry twice and then become visible on the lead/message."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-retry",
        phone="+5491111111113",
        full_name="Retry Lead",
    )
    message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="opener",
    )

    with TestClient(app) as client:
        first = client.post(
            f"/api/contadores/messages/{message.id}/delivery-failure",
            json={"error": "invalid recipient phone", "max_attempts": 3, "retry_delay_seconds": 0},
        )
        second = client.post(
            f"/api/contadores/messages/{message.id}/delivery-failure",
            json={"error": "invalid recipient phone", "max_attempts": 3, "retry_delay_seconds": 0},
        )
        third = client.post(
            f"/api/contadores/messages/{message.id}/delivery-failure",
            json={"error": "invalid recipient phone", "max_attempts": 3, "retry_delay_seconds": 0},
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert first.status_code == 200
    assert first.json()["delivery_status"] == "undelivered"
    assert first.json()["delivery_attempts"] == 1
    assert second.status_code == 200
    assert second.json()["delivery_status"] == "undelivered"
    assert second.json()["delivery_attempts"] == 2
    assert third.status_code == 200
    assert third.json()["delivery_status"] == "failed"
    assert third.json()["delivery_attempts"] == 3
    assert "Recipient phone looks invalid" in third.json()["last_delivery_error"]
    assert detail.status_code == 200
    assert detail.json()["lead"]["outbound_error_count"] == 1
    assert "Recipient phone looks invalid" in detail.json()["lead"]["latest_outbound_error"]
    assert "Recipient phone looks invalid" in detail.json()["messages"][0]["last_delivery_error"]


def test_contadores_delivery_status_transitions_are_monotonic(monkeypatch, tmp_path) -> None:
    """Late provider callbacks should not regress accepted or delivered messages."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-monotonic",
        phone="+5491111111117",
        full_name="Monotonic Lead",
    )
    sent_message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="opener",
    )
    delivered_message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Video",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        external_id="wa-delivered",
        sequence_step="loom_url",
    )

    with TestClient(app) as client:
        sent = client.put(
            f"/api/contadores/messages/{sent_message.id}/delivery",
            json={"status": "sent", "external_id": "wa-sent"},
        )
        late_failure = client.post(
            f"/api/contadores/messages/{sent_message.id}/delivery-failure",
            json={"error": "late provider failure", "max_attempts": 1, "retry_delay_seconds": 0},
        )
        late_sent = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={"external_id": "wa-delivered", "status": "sent"},
        )
        late_delivered_failure = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={"external_id": "wa-delivered", "status": "failed", "error": "late provider failure"},
        )
        delivered = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={"external_id": "wa-sent", "status": "delivered"},
        )

    assert sent.status_code == 200
    assert sent.json()["delivery_status"] == "sent"
    assert late_failure.status_code == 200
    assert late_failure.json()["delivery_status"] == "sent"
    assert late_failure.json()["delivery_attempts"] == 0
    assert late_failure.json()["last_delivery_error"] is None
    assert late_sent.status_code == 200
    assert late_sent.json()["delivery_status"] == "delivered"
    assert late_delivered_failure.status_code == 200
    assert late_delivered_failure.json()["delivery_status"] == "delivered"
    assert late_delivered_failure.json()["delivery_attempts"] == 0
    assert delivered.status_code == 200
    assert delivered.json()["delivery_status"] == "delivered"


def test_contadores_delivery_failure_acknowledgement_clears_lead_alert(monkeypatch, tmp_path) -> None:
    """Acknowledged delivery failures should stay on the message without tinting the chat row."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-retry-ack",
        phone="+5491111111116",
        full_name="Retry Ack Lead",
    )
    message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="opener",
    )

    with TestClient(app) as client:
        failed = client.post(
            f"/api/contadores/messages/{message.id}/delivery-failure",
            json={"error": "invalid recipient phone", "max_attempts": 1, "retry_delay_seconds": 0},
        )
        acknowledged = client.post(
            f"/api/contadores/messages/{message.id}/delivery-error/acknowledge",
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert failed.status_code == 200
    assert failed.json()["delivery_status"] == "failed"
    assert failed.json()["delivery_error_acknowledged_at"] is None
    assert acknowledged.status_code == 200
    assert acknowledged.json()["delivery_status"] == "failed"
    assert "Recipient phone looks invalid" in acknowledged.json()["last_delivery_error"]
    assert acknowledged.json()["delivery_error_acknowledged_at"] is not None
    assert detail.status_code == 200
    assert detail.json()["lead"]["outbound_error_count"] == 0
    assert detail.json()["lead"]["latest_outbound_error"] is None
    assert detail.json()["messages"][0]["delivery_error_acknowledged_at"] is not None


def test_contadores_followup_snapshot_is_read_only_and_segments_leads(monkeypatch, tmp_path) -> None:
    """Follow-up snapshot should expose state without queuing new messages."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    ContadoresConfig.update(enabled=True)
    warm = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-warm",
        phone="+5491111111120",
        full_name="Warm Lead",
        email="warm@example.com",
    )
    ContadoresLead.update_flow_state(
        warm.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
    )
    ContadoresMessage.add(
        lead_id=warm.id,
        from_me=False,
        text="Que presupuesto tienen?",
        created_at=now_utc() - timedelta(minutes=3),
    )

    booking = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-booking",
        phone="+5491111111121",
        full_name="Booking Lead",
        email="booking@example.com",
    )
    ContadoresLead.update_flow_state(
        booking.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
    )
    ContadoresMessage.add(
        lead_id=booking.id,
        from_me=False,
        text="Manana a las 15 hs puedo. Mi mail es booking@example.com",
        created_at=now_utc() - timedelta(minutes=2),
    )
    converted = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-converted",
        phone="+5491111111122",
        full_name="Converted Lead",
        email="converted@example.com",
    )
    ContadoresLead.mark_converted(converted.id, converted_at=now_utc() - timedelta(minutes=1))

    venezuelan = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-ve",
        phone="0412-7174588",
        full_name="Venezuela Lead",
    )
    ContadoresMessage.add(
        lead_id=venezuelan.id,
        from_me=True,
        text="Hola",
        delivery_status=MessageDeliveryStatus.FAILED,
        sequence_step="opener",
    )
    formula = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-formula",
        phone="+5491111111199",
        full_name="=Formula Lead",
        email="=formula@example.com",
    )
    ContadoresMessage.add(
        lead_id=formula.id,
        from_me=False,
        text="+SUM(1,1)",
        created_at=now_utc() - timedelta(minutes=3),
    )

    with TestClient(app) as client:
        unauthorized = client.get("/api/contadores/followup/snapshot")
        response = client.get(
            "/api/contadores/followup/snapshot",
            headers={"X-Internal-Token": "test-internal-token"},
        )
        csv_response = client.get(
            "/api/contadores/followup/snapshot.csv",
            headers={"X-Internal-Token": "test-internal-token"},
        )
        full_csv_response = client.get(
            "/api/contadores/followup/snapshot.csv?profile=full",
            headers={"X-Internal-Token": "test-internal-token"},
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert csv_response.status_code == 200
    assert full_csv_response.status_code == 200
    assert "lead_id,funnel_id,full_name,email" in csv_response.text
    assert "converted_at,booked_at" in csv_response.text
    assert warm.id in csv_response.text
    assert "Warm Lead" not in csv_response.text
    assert "warm@example.com" not in csv_response.text
    assert "Que presupuesto tienen?" not in csv_response.text
    assert "recent_transcript" not in csv_response.text
    assert "Warm Lead" in full_csv_response.text
    assert "warm@example.com" in full_csv_response.text
    assert "Que presupuesto tienen?" in full_csv_response.text
    assert "recent_transcript" in full_csv_response.text
    full_rows = list(csv.DictReader(StringIO(full_csv_response.text)))
    formula_row = next(row for row in full_rows if row["lead_id"] == formula.id)
    assert formula_row["full_name"] == "'=Formula Lead"
    assert formula_row["email"] == "'=formula@example.com"
    assert formula_row["phone"] == "'+5491111111199"
    assert formula_row["latest_inbound_text"] == "'+SUM(1,1)"
    payload = response.json()
    assert payload["counts_by_bucket"]["booking_time_provided"] == 1
    assert payload["counts_by_bucket"]["needs_answer_now"] == 2
    assert payload["counts_by_bucket"]["close_call"] == 2
    assert payload["counts_by_exclusion_reason"]["venezuela"] == 1
    by_id = {item["id"]: item for item in payload["leads"]}
    assert by_id[warm.id]["email"] == "warm@example.com"
    assert by_id[warm.id]["suggested_buckets"] == ["needs_answer_now", "close_call"]
    assert by_id[warm.id]["latest_inbound"]["text"] == "Que presupuesto tienen?"
    assert by_id[booking.id]["suggested_buckets"] == ["booking_time_provided", "needs_answer_now", "close_call"]
    assert by_id[converted.id]["stage"] == "converted"
    assert by_id[converted.id]["raw_stage"] == "awaiting_initial_reply"
    assert by_id[converted.id]["converted_at"] is not None
    assert by_id[converted.id]["converted_at"] == by_id[converted.id]["booked_at"]
    assert by_id[converted.id]["exclusion_reasons"] == ["closed_converted_or_archived"]
    assert f"{converted.id},contadores,Converted Lead,converted@example.com" in full_csv_response.text
    assert ",converted,awaiting_initial_reply," in csv_response.text
    assert by_id[venezuelan.id]["excluded"] is True
    assert by_id[venezuelan.id]["suggested_buckets"] == []

    assert len(ContadoresMessage.list_by_lead(warm.id)) == 1
    assert len(ContadoresMessage.list_by_lead(booking.id)) == 1
    assert len(ContadoresMessage.list_by_lead(venezuelan.id)) == 1


def test_contadores_followup_snapshot_only_marks_due_opener_followups(monkeypatch, tmp_path) -> None:
    """Snapshot opener_followup bucket should match the sender due guard."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    now = now_utc()

    early = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-early",
        phone="+5491111111201",
        full_name="Early Opener",
    )
    ContadoresLead.update_flow_state(
        early.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=now - timedelta(hours=1),
    )

    due = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-due",
        phone="+5491111111202",
        full_name="Due Opener",
    )
    ContadoresLead.update_flow_state(
        due.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=now - timedelta(hours=25),
    )

    replied = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-replied",
        phone="+5491111111203",
        full_name="Replied Opener",
    )
    ContadoresLead.update_flow_state(
        replied.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=now - timedelta(hours=25),
        first_reply_received_at=now - timedelta(hours=23),
    )

    already_sent = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-sent",
        phone="+5491111111204",
        full_name="Sent Opener",
    )
    opener_sent_at = now - timedelta(hours=25)
    ContadoresLead.update_flow_state(
        already_sent.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=opener_sent_at,
    )
    ContadoresMessage.add(
        lead_id=already_sent.id,
        from_me=True,
        text="followup",
        sequence_step=contadores_endpoints.OPENER_FOLLOWUP_SEQUENCE_STEP,
        created_at=opener_sent_at + timedelta(hours=24),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/contadores/followup/snapshot",
            headers={"X-Internal-Token": "test-internal-token"},
        )

    assert response.status_code == 200
    by_id = {item["id"]: item for item in response.json()["leads"]}
    assert "opener_followup" not in by_id[early.id]["suggested_buckets"]
    assert by_id[due.id]["suggested_buckets"] == ["opener_followup"]
    assert "opener_followup" not in by_id[replied.id]["suggested_buckets"]
    assert "opener_followup" not in by_id[already_sent.id]["suggested_buckets"]


def test_contadores_followup_snapshot_batches_recent_messages_and_workstation(monkeypatch, tmp_path) -> None:
    """Snapshot hydration should not fall back to per-lead full-history lookups."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-batch",
        phone="+5491111111301",
        full_name="Snapshot Batch",
    )
    base_time = now_utc() - timedelta(hours=1)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="inbound outside recent cap",
        created_at=base_time,
    )
    for index in range(8):
        ContadoresMessage.add(
            lead_id=lead.id,
            from_me=True,
            text=f"outbound {index}",
            created_at=base_time + timedelta(minutes=index + 1),
        )
    WorkstationClient.create_for_lead(lead, work_type=WorkstationClientWorkType.SOLO_PAGINA)

    already_followed = ContadoresLead.upsert(
        external_lead_id="sheet-row-snapshot-old-followup",
        phone="+5491111111302",
        full_name="Old Followup",
    )
    opener_sent_at = now_utc() - timedelta(days=2)
    ContadoresLead.update_flow_state(
        already_followed.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=opener_sent_at,
    )
    ContadoresMessage.add(
        lead_id=already_followed.id,
        from_me=True,
        text="old opener followup",
        sequence_step=contadores_endpoints.OPENER_FOLLOWUP_SEQUENCE_STEP,
        created_at=opener_sent_at + timedelta(days=1),
    )
    for index in range(5):
        ContadoresMessage.add(
            lead_id=already_followed.id,
            from_me=True,
            text=f"newer outbound {index}",
            created_at=opener_sent_at + timedelta(days=1, minutes=index + 1),
        )

    def fail_list_by_lead(_lead_id: str):
        raise AssertionError("snapshot should batch message hydration")

    def fail_get_by_lead_id(_lead_id: str):
        raise AssertionError("snapshot should batch workstation hydration")

    def fail_has_outbound_sequence_step(*args, **kwargs):
        raise AssertionError("snapshot should batch sequence-step hydration")

    monkeypatch.setattr(ContadoresMessage, "list_by_lead", fail_list_by_lead)
    monkeypatch.setattr(ContadoresMessage, "has_outbound_sequence_step", fail_has_outbound_sequence_step)
    monkeypatch.setattr(ContadoresLead, "open_workstation_client", classmethod(lambda cls, lead: None))
    monkeypatch.setattr(WorkstationClient, "get_by_lead_id", fail_get_by_lead_id)

    with TestClient(app) as client:
        response = client.get(
            "/api/contadores/followup/snapshot?messages_per_lead=3",
            headers={"X-Internal-Token": "test-internal-token"},
        )

    assert response.status_code == 200
    item = next(row for row in response.json()["leads"] if row["id"] == lead.id)
    assert [message["text"] for message in item["recent_messages"]] == ["outbound 5", "outbound 6", "outbound 7"]
    assert item["latest_inbound"]["text"] == "inbound outside recent cap"
    assert item["latest_outbound"]["text"] == "outbound 7"
    assert item["workstation_client_id"] is not None
    followed = next(row for row in response.json()["leads"] if row["id"] == already_followed.id)
    assert [message["text"] for message in followed["recent_messages"]] == [
        "newer outbound 2",
        "newer outbound 3",
        "newer outbound 4",
    ]
    assert "opener_followup" not in followed["suggested_buckets"]


def test_contadores_leads_pipeline_filter_reaches_past_recent_window(monkeypatch, tmp_path) -> None:
    """Persisted CRM filters should run in SQL before the list limit."""
    configure_contadores_db(monkeypatch, tmp_path)
    old_time = now_utc() - timedelta(days=5)
    matching = ContadoresLead.upsert(
        external_lead_id="sheet-row-old-meeting-sent",
        phone="+5491111111401",
        full_name="Old Meeting Sent",
    )
    ContadoresLead.update_flow_state(
        matching.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=old_time,
    )
    with Session(database_module.engine) as session:
        row = session.get(ContadoresLead, matching.id)
        row.updated_at = old_time
        session.add(row)
        session.commit()

    for index in range(1005):
        ContadoresLead.upsert(
            external_lead_id=f"sheet-row-new-unmatched-{index}",
            phone=f"+54911112{index:06d}",
            full_name=f"New Unmatched {index}",
        )

    with TestClient(app) as client:
        response = client.get("/api/contadores/leads?pipeline_stage=meeting_sent")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["leads"]] == [matching.id]


def test_contadores_followup_runner_status_reads_local_artifacts(monkeypatch, tmp_path) -> None:
    """Runner status should expose local launchd artifacts without mutation."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    lock_dir = data_dir / "locks" / "contadores-crm-hourly-followup.lock"
    reports_dir.mkdir(parents=True)
    lock_dir.mkdir(parents=True)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)

    (lock_dir / "pid").write_text("999999999", encoding="utf-8")
    (lock_dir / "started_at").write_text("2026-05-03T01:00:00Z", encoding="utf-8")
    (reports_dir / "contadores-crm-followup-latest.md").write_text("Messages sent: none", encoding="utf-8")
    (reports_dir / "contadores-crm-followup-delta-latest.json").write_text(
        '{"metrics":{"new_replies":1,"needs_action":1},"events":[]}',
        encoding="utf-8",
    )
    (reports_dir / "contadores-crm-followup-20260503T010000Z.log").write_text(
        "line 1\nline 2\nline 3\n",
        encoding="utf-8",
    )
    (reports_dir / "launchd-contadores-crm-followup.err.log").write_text("stderr tail\n", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/contadores/followup/runner/status?log_tail_lines=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["state"] == "degraded"
    assert payload["lock_state"] == "stale"
    assert payload["artifact_errors"]["launchd_out"] == "missing"
    assert payload["started_at"] == "2026-05-03T01:00:00Z"
    assert payload["latest_summary"] == "Messages sent: none"
    assert payload["delta"]["metrics"]["new_replies"] == 1
    assert payload["history_markdown"] == ""
    assert payload["history_updated_at"] is None
    assert payload["latest_log_tail"] == "line 2\nline 3"
    assert payload["launchd_err_tail"] == "stderr tail"
    assert payload["logs"][0]["name"] == "contadores-crm-followup-20260503T010000Z.log"

    with TestClient(app) as client:
        unauthorized = client.post(
            "/api/contadores/followup/runner/status",
            json={"status": "completed", "latest_summary": "should not write"},
        )
        synced = client.post(
            "/api/contadores/followup/runner/status",
            headers={"X-Internal-Token": "test-internal-token"},
            json={
                "status": "completed",
                "generated_at": "2026-05-03T01:10:00Z",
                "latest_summary": "Synced summary",
                "runner_delta": {"metrics": {"new_replies": 2, "needs_action": 1}, "events": []},
                "latest_log_tail": "synced tail token=abc123 warm@example.com +5491111112222 /Users/fgoiriz/private/token.txt",
                "launchd_out_tail": "synced stdout",
                "launchd_err_tail": "synced stderr",
            },
        )
        synced_again = client.post(
            "/api/contadores/followup/runner/status",
            headers={"X-Internal-Token": "test-internal-token"},
            json={
                "status": "completed",
                "generated_at": "2026-05-03T01:10:00Z",
                "latest_summary": "Synced summary",
                "latest_log_tail": "synced tail",
            },
        )

    assert unauthorized.status_code == 401
    assert synced.status_code == 200
    assert synced_again.status_code == 200
    synced_payload = synced.json()
    assert synced_payload["latest_summary"] == "Synced summary"
    assert synced_payload["delta"]["metrics"]["new_replies"] == 2
    assert synced_payload["history_updated_at"] is not None
    assert synced_payload["history_markdown"].count("Synced summary") == 1
    assert "synced tail" in synced_payload["latest_log_tail"]
    assert "abc123" not in synced_payload["latest_log_tail"]
    assert "warm@example.com" not in synced_payload["latest_log_tail"]
    assert "+5491111112222" not in synced_payload["latest_log_tail"]
    assert "/Users/fgoiriz" not in synced_payload["latest_log_tail"]
    assert synced_payload["launchd_out_tail"] == "synced stdout"

    history_text = (reports_dir / "contadores-crm-followup-history.md").read_text(encoding="utf-8")
    assert history_text.count("Synced summary") == 1


def test_contadores_followup_runner_status_classifies_degraded_artifacts(monkeypatch, tmp_path) -> None:
    """Runner diagnostics should make missing/corrupt artifacts explicit."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    lock_dir = data_dir / "locks" / "contadores-crm-hourly-followup.lock"
    reports_dir.mkdir(parents=True)
    lock_dir.mkdir(parents=True)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)

    (reports_dir / "contadores-crm-followup-delta-latest.json").write_text("{bad json", encoding="utf-8")

    with TestClient(app) as client:
        missing_pid = client.get("/api/contadores/followup/runner/status")

    assert missing_pid.status_code == 200
    missing_payload = missing_pid.json()
    assert missing_payload["state"] == "degraded"
    assert missing_payload["lock_state"] == "missing_pid"
    assert missing_payload["artifact_errors"]["delta"] == "invalid_json"

    (lock_dir / "pid").write_text(str(os.getpid()), encoding="utf-8")
    with TestClient(app) as client:
        healthy_lock = client.get("/api/contadores/followup/runner/status")

    assert healthy_lock.status_code == 200
    assert healthy_lock.json()["lock_state"] == "healthy"
    assert healthy_lock.json()["running"] is True


def test_contadores_followup_internal_apis_send_and_update_leads(monkeypatch, tmp_path) -> None:
    """Automation endpoints should require token and reuse CRM send/state guards."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-followup-api",
        phone="+5491111111130",
        full_name="API Lead",
    )
    add_recent_inbound(lead.id, text="Me interesa, que precio tiene?")

    with TestClient(app) as client:
        unauthorized = client.post(
            f"/api/contadores/followup/leads/{lead.id}/messages",
            json={"text": "La inversion es de 599 USD."},
        )
        sent = client.post(
            f"/api/contadores/followup/leads/{lead.id}/messages",
            headers={"X-Internal-Token": "test-internal-token"},
            json={"text": "La inversion es de 599 USD."},
        )
        duplicate = client.post(
            f"/api/contadores/followup/leads/{lead.id}/messages",
            headers={"X-Internal-Token": "test-internal-token"},
            json={"text": "La inversion es de 599 USD."},
        )
        updated = client.patch(
            f"/api/contadores/followup/leads/{lead.id}",
            headers={"X-Internal-Token": "test-internal-token"},
            json={
                "stage": "needs_human",
                "classification_label": "needs_human",
                "classification_reason": "Automation marked for human close.",
                "manual_reply_status": "answered",
                "tags": ["automation-reviewed"],
            },
        )
        action = client.post(
            f"/api/contadores/followup/leads/{lead.id}/actions",
            headers={"X-Internal-Token": "test-internal-token"},
            json={"action": "mark-answered"},
        )

    assert unauthorized.status_code == 401
    assert sent.status_code == 200
    assert sent.json()["queued_message_ids"]
    assert duplicate.status_code == 409
    assert updated.status_code == 200
    assert updated.json()["stage"] == "needs_human"
    refreshed = ContadoresLead.get_by_id(lead.id)
    assert refreshed is not None
    assert refreshed.last_classification_label == "needs_human"
    assert refreshed.last_classification_reason == "Automation marked for human close."
    assert refreshed.manual_reply_handled_at is not None
    assert refreshed.tags == ["automation-reviewed"]
    assert action.status_code == 200


def test_contadores_followup_booked_stage_marks_converted_without_raw_booked(monkeypatch, tmp_path) -> None:
    """Internal follow-up callers can use the old stage name without writing raw booked state."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-followup-converted",
        phone="+5491111111131",
        full_name="Converted Followup",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
    )

    with TestClient(app) as client:
        response = client.patch(
            f"/api/contadores/followup/leads/{lead.id}",
            headers={"X-Internal-Token": "test-internal-token"},
            json={
                "stage": "booked",
                "classification_label": "converted",
                "classification_reason": "Automation confirmed the client converted.",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "converted"
    assert payload["raw_stage"] == "awaiting_initial_reply"
    assert payload["pipeline_stage"] == "converted"
    assert payload["converted_at"] is not None
    assert payload["converted_at"] == payload["booked_at"]


def test_contadores_provider_failed_status_requeues_before_final_failure(monkeypatch, tmp_path) -> None:
    """Meta failed webhooks should use the same retry budget as send exceptions."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-provider-failed",
        phone="+5491111111114",
        full_name="Provider Failed Lead",
    )
    message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        external_id="wamid.failed.1",
        delivery_status=MessageDeliveryStatus.SENT,
        sequence_step="opener",
    )

    with TestClient(app) as client:
        first = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={
                "external_id": message.external_id,
                "status": "failed",
                "error_code": 131026,
                "error_message": "Message undeliverable",
                "error_details": "The recipient is not a WhatsApp user.",
            },
        )
        second = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={
                "external_id": message.external_id,
                "status": "failed",
                "error_code": 131026,
                "error_message": "Message undeliverable",
                "error_details": "The recipient is not a WhatsApp user.",
            },
        )
        third = client.put(
            "/api/contadores/messages/delivery/by-external-id",
            json={
                "external_id": message.external_id,
                "status": "failed",
                "error_code": 131026,
                "error_message": "Message undeliverable",
                "error_details": "The recipient is not a WhatsApp user.",
            },
        )

    assert first.status_code == 200
    assert first.json()["delivery_status"] == "undelivered"
    assert first.json()["delivery_attempts"] == 1
    assert second.status_code == 200
    assert second.json()["delivery_status"] == "undelivered"
    assert second.json()["delivery_attempts"] == 2
    assert third.status_code == 200
    assert third.json()["delivery_status"] == "failed"
    assert third.json()["delivery_attempts"] == 3
    assert "not registered on WhatsApp" in third.json()["last_delivery_error"]
    assert "Meta code: 131026" in third.json()["last_delivery_error"]


def test_contadores_delivery_failure_normalizes_experiment_group_error(monkeypatch, tmp_path) -> None:
    """Meta experiment-group failures should be readable in the CRM."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-experiment-group",
        phone="+5491111111117",
        full_name="Experiment Lead",
    )
    message = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="opener",
    )
    raw_error = (
        "UserIsInExperimentGroup(code=130472, message=\"User's number is part of an experiment\", "
        "details=\"Failed to send message because this user's phone number is part of an experiment\")"
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/messages/{message.id}/delivery-failure",
            json={"error": raw_error, "max_attempts": 1, "retry_delay_seconds": 0},
        )

    assert response.status_code == 200
    assert response.json()["delivery_status"] == "failed"
    assert "Meta says the recipient is in an experiment group" in response.json()["last_delivery_error"]
    assert "not a copy or template issue" in response.json()["last_delivery_error"]
    assert "Meta code: 130472" in response.json()["last_delivery_error"]


def test_contadores_custom_manual_message_requires_open_whatsapp_window(monkeypatch, tmp_path) -> None:
    """Custom/manual WhatsApp should be blocked when the 24-hour window is closed."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-closed-window",
        phone="+5491111111115",
        full_name="Closed Window Lead",
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual",
            json={"text": "Hola, te escribo manualmente"},
        )

    assert response.status_code == 400
    assert "24-hour" in response.json()["detail"]
    assert ContadoresMessage.list_by_lead(lead.id) == []


def test_contadores_custom_manual_message_works_inside_whatsapp_window(monkeypatch, tmp_path) -> None:
    """Custom/manual WhatsApp should be allowed after a recent lead reply."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-open-window",
        phone="+5491111111116",
        full_name="Open Window Lead",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si, me interesa",
        created_at=now_utc() - timedelta(hours=2),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual",
            json={"text": "Genial, te paso mas informacion"},
        )

    assert response.status_code == 200
    assert response.json()["queued_message_ids"] == [2]


def test_contadores_manual_ping_template_bypasses_closed_whatsapp_window(monkeypatch, tmp_path) -> None:
    """Approved templates should remain available outside the 24-hour window."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-template-window",
        phone="+5491111111117",
        full_name="Template Window Lead",
    )

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")

    assert response.status_code == 200
    assert response.json()["queued_message_ids"] == [1]


def test_contadores_closed_lead_blocks_manual_outbound_until_reopened(monkeypatch, tmp_path) -> None:
    """Closed leads should not receive custom messages or approved templates."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-closed-send",
        phone="+5491111111118",
        full_name="Closed Send Lead",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        custom_response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual",
            json={"text": "Esto no deberia salir"},
        )
        template_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/reopen")
        after_reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")

    assert close_response.status_code == 200
    assert custom_response.status_code == 400
    assert template_response.status_code == 400
    assert "closed" in custom_response.json()["detail"]
    assert "closed" in template_response.json()["detail"]
    assert reopen_response.status_code == 200
    assert after_reopen_response.status_code == 200
    assert after_reopen_response.json()["queued_message_ids"] == [2]
    assert [item.sequence_step for item in ContadoresMessage.list_by_lead(lead.id) if item.from_me] == [
        "manual_ping_template"
    ]


def test_contadores_zero_weight_strategy_is_not_auto_assigned(monkeypatch, tmp_path) -> None:
    """A configured zero-weight strategy should stay available without receiving automatic traffic."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))

    chosen_ids = {
        contadores_endpoints.choose_contadores_strategy(step="loom", lead_id=f"lead-{index}").id
        for index in range(50)
    }

    assert chosen_ids == {"text_offer_599"}


def test_contadores_strategy_weights_are_configurable(monkeypatch, tmp_path) -> None:
    """Config weights should drive automatic strategy assignment and stats display."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(
        enabled=True,
        strategy_weights={"loom": {"text_offer_599": 100}},
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-config-weight",
        phone="+5491111111199",
        full_name="Weight Lead",
    )
    add_recent_inbound(lead.id)

    contadores_endpoints.send_loom_sequence(lead=lead, config=config)

    with TestClient(app) as client:
        config_response = client.get("/api/contadores/config")
        stats_response = client.get("/api/contadores/strategy-stats")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert config_response.status_code == 200
    assert config_response.json()["strategy_weights"] == {
        "loom": {"text_offer_599": 100}
    }

    assert stats_response.status_code == 200
    items = {item["strategy_id"]: item for item in stats_response.json()["items"]}
    assert items["text_offer_599"]["weight"] == 100

    assert pending_response.status_code == 200
    assert [item["strategy_id"] for item in pending_response.json()["messages"]] == [
        "text_offer_599",
    ]


def test_contadores_strategy_stats_count_calendly_and_booked(monkeypatch, tmp_path) -> None:
    """Strategy stats should aggregate assigned leads and downstream milestones."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stats",
        phone="+5491111111113",
        full_name="Stats Lead",
    )
    add_recent_inbound(lead.id)

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="text_offer_599")
    for message in ContadoresMessage.list_by_lead(lead.id):
        ContadoresMessage.update_delivery_status(
            message_id=message.id or 0,
            delivery_status=MessageDeliveryStatus.DELIVERED,
            external_id=f"wa-{message.id}",
        )
    ContadoresLead.update_flow_state(
        lead.id,
        calendly_sent_at=now_utc(),
        booked_at=now_utc(),
    )

    with TestClient(app) as client:
        response = client.get("/api/contadores/strategy-stats")

    assert response.status_code == 200
    items = {item["strategy_id"]: item for item in response.json()["items"]}
    assert items["text_offer_599"]["assigned"] == 1
    assert items["text_offer_599"]["sent"] == 1
    assert items["text_offer_599"]["delivered"] == 1
    assert items["text_offer_599"]["reached_calendly"] == 1
    assert items["text_offer_599"]["reached_meeting"] == 1
    assert items["text_offer_599"]["booked"] == 1
    assert items["text_offer_599"]["converted"] == 1
    assert items["text_offer_599"]["calendly_rate"] == 1
    assert items["text_offer_599"]["meeting_rate"] == 1
    assert items["text_offer_599"]["conversion_rate"] == 1


def test_contadores_pending_delivery_exposes_name_country_opener_params(monkeypatch, tmp_path) -> None:
    """The opener should render lead-specific copy and template params."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener",
        phone="+5491999999999",
        full_name="Eva Ruiz",
    )

    contadores_endpoints.send_opener_sequence(lead=lead)

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"] == [
        {
            "message_id": 1,
            "lead_id": lead.id,
            "external_lead_id": "sheet-row-opener",
            "phone": "+5491999999999",
            "normalized_phone": "5491999999999",
            "full_name": "Eva Ruiz",
            "text": (
                "Hola Eva, llenaste el formulario para contadores de Argentina sobre como conseguir "
                "clientes a tu whatsapp. es correcto?"
            ),
            "dispatch_after": payload["messages"][0]["dispatch_after"],
            "created_at": payload["messages"][0]["created_at"],
            "sequence_step": "opener",
            "strategy_assignment_id": None,
            "strategy_step": None,
            "strategy_id": None,
            "strategy_label": None,
            "media_type": None,
            "media_path": None,
            "media_caption": None,
            "media_mime_type": None,
            "media_filename": None,
            "contact_has_inbound": False,
            "whatsapp_template_name": "contadores_intro_nombre_pais_es_v1",
            "whatsapp_template_language": "es",
            "whatsapp_template_body_params": ["Eva", "Argentina"],
        }
    ]


def test_abogados_pending_delivery_upgrades_legacy_opener_to_name_country_params(monkeypatch, tmp_path) -> None:
    """Old Abogados funnel config should still send the new name/country template."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-lawyer-opener",
        phone="+584245449498",
        full_name="Dra Marielis Gomez",
        funnel_id="abogados",
    )
    legacy_abogados_funnel = build_abogados_test_funnel()
    legacy_abogados_funnel["opener_text"] = "Hola, completaste el formulario para abogados. Es correcto?"
    legacy_abogados_funnel["opener_template_name"] = "abogados_intro_es_v1"

    with TestClient(app) as client:
        create_funnel = client.post("/api/funnels", json=legacy_abogados_funnel)
        contadores_endpoints.send_opener_sequence(lead=lead)
        response = client.get("/api/contadores/messages/pending-delivery")

    assert create_funnel.status_code == 200
    assert response.status_code == 200
    message = response.json()["messages"][0]
    assert message["text"] == (
        "Hola Marielis, llenaste el formulario para abogados de Venezuela sobre como conseguir "
        "casos redituables a tu whatsapp. es correcto?"
    )
    assert message["whatsapp_template_name"] == "abogados_intro_nombre_pais_es_v1"
    assert message["whatsapp_template_body_params"] == ["Marielis", "Venezuela"]


def test_manual_ping_action_queues_template_and_pauses_automation(monkeypatch, tmp_path) -> None:
    """The operator-only ping should be template-backed without joining automation ticks."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-ping",
        phone="+5491888888888",
        full_name="Ping Lead",
    )

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["text"] == (
        "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion"
    )
    assert messages[0]["sequence_step"] == "manual_ping_template"
    assert messages[0]["whatsapp_template_name"] == "contadores_manual_ping_es_v1"
    assert messages[0]["whatsapp_template_language"] == "es"

    assert detail_response.status_code == 200
    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "needs_human"
    assert lead_payload["automation_paused"] is True


def test_manual_handoff_action_pauses_ai_reply_without_queueing_message(monkeypatch, tmp_path) -> None:
    """Operators can stop AI replies for one lead and take the chat manually."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-handoff",
        phone="+5491888888899",
        full_name="Manual Lead",
    )
    inbound = add_recent_inbound(lead.id, text="Me interesa, cuanto sale?")
    assert inbound.id is not None
    assert ContadoresLead.claim_conversation_processing(
        lead_id=lead.id,
        latest_inbound_id=inbound.id,
        latest_inbound_at=inbound.created_at,
        claimed_at=now_utc(),
        stale_after_seconds=1200,
    )

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/manual-handoff")
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    refreshed = ContadoresLead.get_by_id(lead.id)
    assert refreshed is not None
    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    assert pending_response.json()["messages"] == []

    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "needs_human"
    assert lead_payload["manual_reply_status"] == "needs_reply"
    assert lead_payload["automation_paused"] is True
    assert lead_payload["automation_paused_reason"] == "manual_handoff"
    assert refreshed.conversation_processing_started_at is None
    assert refreshed.conversation_processing_latest_inbound_id is None


def test_accountant_page_example_video_action_queues_reusable_video(monkeypatch, tmp_path) -> None:
    """Operators should be able to send the reused accountant page example video."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-page-example",
        phone="+5491888888898",
        full_name="Example Lead",
    )
    add_recent_inbound(lead.id, text="me podes mandar un ejemplo?")

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-accountant-page-example-video")
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["text"] == "Esta es una pagina de un cliente contador nuestro, asi podria verse tu pagina"
    assert messages[0]["sequence_step"] == "manual_accountant_page_example_video"
    assert messages[0]["media_type"] == "video"
    assert messages[0]["media_path"] == "data/contadores/videos/cliente-pagina.mp4"
    assert messages[0]["media_filename"] == "cliente-pagina.mp4"

    assert detail_response.status_code == 200
    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "needs_human"
    assert lead_payload["automation_paused"] is True
    assert lead_payload["automation_paused_reason"] == "manual_send-accountant-page-example-video"


def test_lawyer_page_example_video_action_queues_reusable_video(monkeypatch, tmp_path) -> None:
    """Operators should be able to send the reused lawyer page example video."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-lawyer-page-example",
        phone="+5491888888897",
        full_name="Lawyer Example Lead",
        funnel_id="abogados",
    )
    add_recent_inbound(lead.id, text="me podes mandar un ejemplo?")

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-lawyer-page-example-video")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["text"] == "Esta es una pagina de un cliente abogado nuestro, asi podria verse tu pagina"
    assert messages[0]["sequence_step"] == "manual_lawyer_page_example_video"
    assert messages[0]["media_type"] == "video"
    assert messages[0]["media_path"] == "data/contadores/videos/pagina-abogado.mp4"
    assert messages[0]["media_filename"] == "pagina-abogado.mp4"


def test_pending_delivery_uses_message_template_params(monkeypatch, tmp_path) -> None:
    """One-off campaign rows should carry their own WhatsApp template variables."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-promo-template",
        phone="+5491888888899",
        full_name="Promo Lead",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text=(
            "Hola Karen, promo para contadores de Ecuador:\n\n"
            "te construimos una pagina web moderna y profesional para mostrar tus servicios.\n\n"
            "Solo 29 USD.\n"
            "La pagas solo cuando este terminada y te guste.\n\n"
            "Si te interesa esta oferta, respondeme y te mostramos un ejemplo."
        ),
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="promo_web_profesional_20260505",
        whatsapp_template_name="konecta_promo_web_profesional_es_v1",
        whatsapp_template_language="es",
        whatsapp_template_body_params=["Karen", "contadores", "Ecuador", "29"],
    )

    with TestClient(app) as client:
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["whatsapp_template_name"] == "konecta_promo_web_profesional_es_v1"
    assert messages[0]["whatsapp_template_language"] == "es"
    assert messages[0]["whatsapp_template_body_params"] == ["Karen", "contadores", "Ecuador", "29"]

    assert detail_response.status_code == 200
    detail_messages = detail_response.json()["messages"]
    assert detail_messages[0]["whatsapp_template_name"] == "konecta_promo_web_profesional_es_v1"
    assert detail_messages[0]["whatsapp_template_body_params"] == ["Karen", "contadores", "Ecuador", "29"]


def test_active_offer_positive_reply_sends_page_example_video(monkeypatch, tmp_path) -> None:
    """The solo-page promo should send an example video before asking for scheduling."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer-page-example",
        phone="+593991111113",
        full_name="Carla Perez",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola Carla, si te interesa esta oferta respondeme y te mostramos un ejemplo.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Me interesa",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FailIfCalledConversationBot:
        async def aforward(self, **kwargs):
            raise AssertionError(f"conversation bot should not run for first solo-page interest: {kwargs}")

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FailIfCalledConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert tick.status_code == 200
    assert tick.json()["page_examples_sent"] == 1
    assert tick.json()["scheduling_detail_requests_sent"] == 0
    messages = pending.json()["messages"]
    assert [item["sequence_step"] for item in messages] == ["auto_accountant_page_example_video"]
    assert messages[0]["media_type"] == "video"
    assert messages[0]["media_path"] == "data/contadores/videos/cliente-pagina.mp4"
    assert WorkstationClient.get_by_lead_id(lead.id) is None
    assert detail.json()["lead"]["last_classification_label"] == "page_example_sent"


def test_active_offer_positive_reply_after_example_creates_solo_page_workstation(monkeypatch, tmp_path) -> None:
    """Positive replies after the page example should create the pending-payment Workstation job."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer-workstation",
        phone="+593991111114",
        full_name="Daniel Molina",
    )
    offer_at = now_utc() - timedelta(minutes=4)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola Daniel, si te interesa esta oferta respondeme y te mostramos un ejemplo.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        whatsapp_template_body_params=["Daniel", "contadores", "Ecuador", "29"],
        created_at=offer_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Esta es una pagina de un cliente contador nuestro, asi podria verse tu pagina",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="auto_accountant_page_example_video",
        media_type="video",
        media_path="data/contadores/videos/cliente-pagina.mp4",
        media_filename="cliente-pagina.mp4",
        created_at=offer_at + timedelta(minutes=1),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Dale hagamos la pagina",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FailIfCalledConversationBot:
        async def aforward(self, **kwargs):
            raise AssertionError(f"conversation bot should not run after accepted page example: {kwargs}")

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FailIfCalledConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        workstation_detail = client.get(f"/api/workstation/clients/{WorkstationClient.get_by_lead_id(lead.id).id}")

    assert tick.status_code == 200
    assert tick.json()["workstation_solo_page_started"] == 1
    workstation = WorkstationClient.get_by_lead_id(lead.id)
    assert workstation is not None
    assert workstation.work_type == WorkstationClientWorkType.SOLO_PAGINA
    assert workstation.status == WorkstationClientStatus.PENDING_PAYMENT
    assert workstation.automation_status == WorkstationAutomationStatus.INTAKE
    assert workstation.offer_price_usd == 29
    assert workstation.offer_currency == "USD"
    assert detail.json()["lead"]["stage"] == "converted"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "workstation_solo_page_started"
    assert workstation_detail.status_code == 200
    assert workstation_detail.json()["client"]["work_type"] == "solo_pagina"
    assert workstation_detail.json()["client"]["status"] == "pending_payment"
    assert workstation_detail.json()["client"]["automation_status"] == "intake"
    assert workstation_detail.json()["client"]["offer_price_usd"] == 29
    assert workstation_detail.json()["client"]["offer_currency"] == "USD"
