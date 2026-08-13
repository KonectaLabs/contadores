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



def test_workstation_conversion_is_idempotent_and_keeps_crm_link(monkeypatch, tmp_path) -> None:
    """Converting a paid lead should create one linked Workstation client."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation",
        phone="+5491777777777",
        full_name="Cliente Pago",
        email="cliente@example.com",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola, te paso la propuesta.",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Perfecto, avance y pague.",
    )

    with TestClient(app) as client:
        first = client.post(f"/api/workstation/clients/from-lead/{lead.id}")
        second = client.post(f"/api/workstation/clients/from-lead/{lead.id}")
        crm_detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert first.status_code == 200
    assert second.status_code == 200
    first_payload = first.json()
    second_payload = second.json()
    assert first_payload["client"]["id"] == second_payload["client"]["id"]
    assert first_payload["client"]["lead_id"] == lead.id
    assert first_payload["client"]["folder_name"].endswith("-cliente-pago")
    assert [message["text"] for message in first_payload["messages"]] == [
        "Hola, te paso la propuesta.",
        "Perfecto, avance y pague.",
    ]
    assert crm_detail.json()["lead"]["workstation_client_id"] == first_payload["client"]["id"]
    assert "workstation_status" not in crm_detail.json()["lead"]
    assert crm_detail.json()["lead"]["stage"] == "converted"
    assert WorkstationClient.get_by_lead_id(lead.id) is not None


def test_solo_page_workstation_conversion_leaves_manual_attention(monkeypatch, tmp_path) -> None:
    """A converted solo-page lead should leave the CRM manual-attention queue."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-manual-exit",
        phone="+5491777777797",
        full_name="Cliente Manual Sale",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="handoff_human",
        clear_needs_human_notified_at=True,
        last_inbound_at=now_utc(),
    )

    with TestClient(app) as client:
        conversion = client.post(
            f"/api/workstation/clients/from-lead/{lead.id}"
            "?work_type=solo_pagina&status=pending_payment&automation_status=intake"
        )
        manual_attention = client.get(
            "/api/contadores/leads"
            "?stage=needs_human&manual_reply_status=needs_reply&needs_human=true"
        )
        pending_alerts = client.get("/api/contadores/alerts/pending?funnel_id=contadores")
        crm_detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert conversion.status_code == 200
    assert crm_detail.json()["lead"]["stage"] == "converted"
    assert crm_detail.json()["lead"]["raw_stage"] == "needs_human"
    assert manual_attention.json()["leads"] == []
    assert pending_alerts.json()["items"] == []


def test_workstation_close_closes_crm_lead_and_stops_automation(monkeypatch, tmp_path) -> None:
    """Closing from Workstation should stop further automated work for that lead."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-close",
        phone="+5491777777788",
        full_name="Cliente Cierre",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PAID,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )

    with TestClient(app) as client:
        response = client.post(f"/api/workstation/clients/{workstation.id}/close")
        crm_detail = client.get(f"/api/contadores/leads/{lead.id}")
        workstation_list = client.get("/api/workstation/clients")
        start_response = client.post(
            f"/api/workstation/clients/{workstation.id}/solo-page/work",
            json={"prompt": "hacer una version nueva"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["client"]["status"] == "closed"
    assert payload["client"]["automation_status"] == "needs_human"
    assert payload["automation_state"]["label"] == "Closed lead"
    assert crm_detail.json()["lead"]["stage"] == "closed"
    assert crm_detail.json()["lead"]["automation_paused"] is True
    assert crm_detail.json()["lead"]["automation_paused_reason"] == "manual_workstation_close"
    assert workstation_list.json()["clients"] == []
    assert start_response.status_code == 409


def test_workstation_migration_normalizes_enum_values(monkeypatch, tmp_path) -> None:
    """Existing rows with raw enum values should remain readable after migration."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-enum-migration",
        phone="+5491777777770",
        full_name="Cliente Enum",
    )
    workstation = WorkstationClient.create_for_lead(lead)
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE workstation_clients "
            "SET status = 'paid', work_type = 'pagina_ads', automation_status = 'needs_human' "
            "WHERE id = ?",
            (workstation.id,),
        )

    database_module.ensure_workstation_client_automation_columns()

    rows = WorkstationClient.list_recent()
    assert len(rows) == 1
    assert rows[0].status == WorkstationClientStatus.PAID
    assert rows[0].work_type == WorkstationClientWorkType.PAGINA_ADS
    assert rows[0].automation_status == WorkstationAutomationStatus.NEEDS_HUMAN


def test_workstation_tick_sends_intake_and_mirrors_whatsapp_media(monkeypatch, tmp_path) -> None:
    """Solo-page Workstation intake should ask for basics and mirror inbound media files."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-intake-media",
        phone="+5491777777771",
        full_name="Cliente Media",
    )
    source_path = data_dir / "contadores" / "inbound_media" / lead.id / "foto.jpg"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"source-photo")
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[image]",
        media_type="image",
        media_path=str(Path("data") / "contadores" / "inbound_media" / lead.id / "foto.jpg"),
        media_mime_type="image/jpeg",
        media_filename="foto.jpg",
        created_at=now_utc() - timedelta(seconds=45),
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["intake_messages_sent"] == 1
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["workstation_intake"]
    media_assets = WorkstationMediaAsset.list_by_client(workstation.id)
    assert len(media_assets) == 1
    assert media_assets[0].stored_path.startswith("data/workstation/clients/")
    mirrored_path = data_dir / Path(media_assets[0].stored_path).relative_to("data")
    assert mirrored_path.read_bytes() == b"source-photo"


def test_workstation_tick_generates_preview_without_blocking_on_missing_photo(monkeypatch, tmp_path) -> None:
    """A solo-page draft should be generated from intake text even if no photo arrived yet."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-draft",
        phone="+5491777777772",
        full_name="Cliente Draft",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    intake_at = now_utc() - timedelta(minutes=30)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Perfecto, entonces arrancamos con la pagina.",
        sequence_step="workstation_intake",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=intake_at,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.INTAKE,
        last_automation_handled_at=intake_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="El estudio se llama Molina Contadores, hacemos impuestos y sociedades en Quito.",
        created_at=now_utc() - timedelta(minutes=21),
    )
    generated_calls: list[dict[str, object]] = []

    async def fake_generate_solo_page_version(**kwargs) -> Path:
        generated_calls.append(kwargs)
        version_dir = workstation_endpoints.next_landing_page_version_dir(kwargs["client"])
        (version_dir / "index.html").write_text("<html><body>Draft</body></html>", encoding="utf-8")
        (version_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (version_dir / "script.js").write_text("", encoding="utf-8")
        (version_dir / "preview-message.txt").write_text(
            "Molina, le dejo el primer recorrido de la pagina. "
            "Digame que ajustamos o si avanzamos asi.",
            encoding="utf-8",
        )
        (version_dir / "preview.mp4").write_bytes(b"mp4")
        return version_dir

    monkeypatch.setattr(workstation_endpoints, "generate_solo_page_version", fake_generate_solo_page_version)
    monkeypatch.setattr(
        workstation_endpoints,
        "decide_workstation_next_action",
        lambda **kwargs: asyncio.sleep(
            0,
            result=workstation_endpoints.WorkstationAgentDecision(
                action="generate_or_revise_page",
                reason="Concrete revision request.",
            ),
        ),
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["drafts_generated"] == 1
    assert tick.json()["revision_videos_sent"] == 1
    assert len(generated_calls) == 1
    assert generated_calls[0]["revision"] is False
    messages = pending.json()["messages"]
    assert [item["sequence_step"] for item in messages] == ["workstation_preview_video"]
    assert messages[0]["text"] == (
        "Molina, le dejo el primer recorrido de la pagina. Digame que ajustamos o si avanzamos asi."
    )
    assert messages[0]["media_type"] == "video"
    assert messages[0]["media_path"].endswith("landing-page/v001/preview.mp4")
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW
    assert updated.last_preview_sent_at is not None


def test_workstation_tick_waits_twenty_minutes_before_generating_preview(monkeypatch, tmp_path) -> None:
    """Solo-page Workstation should wait for a long quiet window before drafting."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-draft-backoff",
        phone="+5491777777788",
        full_name="Cliente Backoff",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    intake_at = now_utc() - timedelta(minutes=30)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.INTAKE,
        last_automation_handled_at=intake_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Perfecto, entonces arrancamos con la pagina.",
        sequence_step="workstation_intake",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=intake_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Estoy juntando fotos y datos del estudio.",
        created_at=now_utc() - timedelta(minutes=19),
    )

    async def fail_generate_solo_page_version(**kwargs) -> Path:
        raise AssertionError("Workstation generated before the quiet window elapsed")

    monkeypatch.setattr(workstation_endpoints, "generate_solo_page_version", fail_generate_solo_page_version)

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")

    assert tick.status_code == 200
    assert tick.json()["drafts_generated"] == 0
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.INTAKE


def test_workstation_detail_shows_backoff_state_and_progress(monkeypatch, tmp_path) -> None:
    """The Workstation detail should explain quiet-window waits and show progress.md."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-status",
        phone="+5491777777789",
        full_name="Cliente Estado",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    preview_at = now_utc() - timedelta(minutes=40)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path="data/workstation/clients/demo/landing-page/v001/preview.mp4",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Ahora le mando mas fotos y cambios.",
        created_at=now_utc() - timedelta(minutes=5),
    )
    workstation_endpoints.append_workstation_progress(workstation, "Operator-visible progress line.")

    with TestClient(app) as client:
        detail = client.get(f"/api/workstation/clients/{workstation.id}")

    assert detail.status_code == 200
    state = detail.json()["automation_state"]
    assert state["status"] == "awaiting_review"
    assert state["label"] == "Waiting backoff"
    assert state["is_waiting_backoff"] is True
    assert state["backoff_until"]
    assert state["latest_inbound_at"]
    assert state["progress_path"].endswith("progress.md")
    assert "Operator-visible progress line." in state["progress_markdown"]


def test_workstation_handoff_reply_shows_backoff_instead_of_idle(monkeypatch, tmp_path) -> None:
    """A late reply after human handoff should be visible as backoff, not generic idle."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-handoff-backoff",
        phone="+5491777777815",
        full_name="Cliente Handoff Backoff",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
    )
    preview_at = now_utc() - timedelta(days=4)
    handoff_at = now_utc() - timedelta(days=1)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_preview_sent_at=preview_at,
        handoff_sent_at=handoff_at,
        last_automation_handled_at=handoff_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Recien pude verlo, cambiemos el color.",
        created_at=now_utc() - timedelta(minutes=4),
    )

    with TestClient(app) as client:
        detail = client.get(f"/api/workstation/clients/{workstation.id}")

    assert detail.status_code == 200
    state = detail.json()["automation_state"]
    assert state["status"] == "needs_human"
    assert state["label"] == "Waiting backoff"
    assert state["is_waiting_backoff"] is True
    assert state["backoff_until"]


def test_workstation_tick_revises_after_handoff_reply(monkeypatch, tmp_path) -> None:
    """Late replies after no-response handoff should resume Codex revision automatically."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-handoff-revision",
        phone="+5491777777816",
        full_name="Cliente Handoff Revision",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
    )
    preview_at = now_utc() - timedelta(days=4)
    handoff_at = now_utc() - timedelta(days=1)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_preview_sent_at=preview_at,
        handoff_sent_at=handoff_at,
        last_automation_handled_at=handoff_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Cambiale el color y agregale mi especialidad.",
        created_at=now_utc() - timedelta(minutes=25),
    )
    generated_calls: list[dict[str, object]] = []

    async def fake_generate_solo_page_version(**kwargs) -> Path:
        generated_calls.append(kwargs)
        version_dir = workstation_endpoints.next_landing_page_version_dir(kwargs["client"])
        (version_dir / "index.html").write_text("<html><body>Revision</body></html>", encoding="utf-8")
        (version_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (version_dir / "script.js").write_text("", encoding="utf-8")
        (version_dir / "preview.mp4").write_bytes(b"mp4")
        return version_dir

    monkeypatch.setattr(workstation_endpoints, "generate_solo_page_version", fake_generate_solo_page_version)
    monkeypatch.setattr(
        workstation_endpoints,
        "decide_workstation_next_action",
        lambda **kwargs: asyncio.sleep(
            0,
            result=workstation_endpoints.WorkstationAgentDecision(
                action="generate_or_revise_page",
                reason="Concrete revision request.",
            ),
        ),
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["revision_videos_sent"] == 1
    assert [item["sequence_step"] for item in pending.json()["messages"]] == [
        "workstation_revision_video",
        "workstation_public_page_link",
    ]
    assert len(generated_calls) == 1
    assert generated_calls[0]["revision"] is True
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW


def test_workstation_tick_fails_stale_working_state(monkeypatch, tmp_path) -> None:
    """A server restart during Codex should not leave Workstation silently working forever."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-stale",
        phone="+5491777777790",
        full_name="Cliente Stale",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    started_at = now_utc() - timedelta(hours=2, minutes=1)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=started_at,
    )

    with TestClient(app) as client:
        detail_before = client.get(f"/api/workstation/clients/{workstation.id}")
        tick = client.post("/api/workstation/automation/tick")
        detail_after = client.get(f"/api/workstation/clients/{workstation.id}")

    assert detail_before.status_code == 200
    assert detail_before.json()["automation_state"]["is_stale"] is True
    assert tick.status_code == 200
    assert tick.json()["failures"] == 1
    after_payload = detail_after.json()
    assert after_payload["client"]["automation_status"] == "failed"
    assert after_payload["runtime_alerts"][0]["alert_type"] == "workstation_codex_failure"
    assert "more than 2 hours" in after_payload["runtime_alerts"][0]["error"]
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Automation failed" in progress


def test_workstation_tick_keeps_recent_working_state_active(monkeypatch, tmp_path) -> None:
    """Drafts should get a long generation window before stale failure handling."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-recent-working",
        phone="+5491777777793",
        full_name="Cliente Working Reciente",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    started_at = now_utc() - timedelta(minutes=31)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=started_at,
    )

    with TestClient(app) as client:
        detail_before = client.get(f"/api/workstation/clients/{workstation.id}")
        tick = client.post("/api/workstation/automation/tick")
        detail_after = client.get(f"/api/workstation/clients/{workstation.id}")

    assert detail_before.status_code == 200
    assert detail_before.json()["automation_state"]["is_stale"] is False
    assert tick.status_code == 200
    assert tick.json()["failures"] == 0
    assert detail_after.json()["client"]["automation_status"] == "drafting"


def test_workstation_tick_returns_busy_while_generation_tick_is_running(monkeypatch, tmp_path) -> None:
    """Bot retries should not mark an in-progress Codex run as stale."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-busy-lock",
        phone="+5491777777791",
        full_name="Cliente Busy",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    started_at = now_utc() - timedelta(hours=2, minutes=1)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=started_at,
    )
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    monkeypatch.setattr(workstation_endpoints, "workstation_automation_tick_lock", lock)

    try:
        with TestClient(app) as client:
            tick = client.post("/api/workstation/automation/tick")
            detail = client.get(f"/api/workstation/clients/{workstation.id}")
    finally:
        lock.release()

    assert tick.status_code == 200
    assert tick.json()["status"] == "busy"
    assert tick.json()["failures"] == 0
    assert detail.json()["client"]["automation_status"] == "drafting"


def test_workstation_tick_skips_durably_claimed_client(monkeypatch, tmp_path) -> None:
    """A client already claimed by another process should not advance twice."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    calls: list[str] = []
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-durable-claim",
        phone="+5491777777792",
        full_name="Cliente Claimed",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PAID,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    assert WorkstationClient.claim_automation(workstation.id, claimed_at=now_utc())

    async def fail_if_advanced(client, *, now):
        del now
        calls.append(client.id)
        return workstation_endpoints.empty_workstation_metrics()

    monkeypatch.setattr(workstation_endpoints, "advance_solo_page_client", fail_if_advanced)

    try:
        with TestClient(app) as client:
            tick = client.post("/api/workstation/automation/tick")
    finally:
        WorkstationClient.release_automation_claim(workstation.id)

    assert tick.status_code == 200
    assert tick.json()["automation_claims_skipped"] == 1
    assert calls == []


def test_manual_solo_page_conversion_uses_existing_chat_context(monkeypatch, tmp_path) -> None:
    """Manual solo-page starts should generate when the old chat already has page details."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        funnel_id="abogados",
        external_lead_id="sheet-row-manual-solo-page-context",
        phone="+584241111115",
        full_name="Cliente Manual Solo",
    )
    offer_at = now_utc() - timedelta(minutes=15)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Promo pagina profesional por 49 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        whatsapp_template_body_params=["Cliente", "abogados", "Venezuela", "49"],
        created_at=offer_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Esta es una pagina de un cliente abogado nuestro, asi podria verse tu pagina",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="auto_lawyer_page_example_video",
        media_type="video",
        media_path="data/contadores/videos/pagina-abogado.mp4",
        created_at=offer_at + timedelta(minutes=1),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Mi despacho se llama Estudio Manual, trabajo derecho civil y familia en Caracas.",
        created_at=now_utc() - timedelta(minutes=21),
    )

    generated_calls: list[dict[str, object]] = []

    async def fake_generate_solo_page_version(**kwargs) -> Path:
        generated_calls.append(kwargs)
        version_dir = workstation_endpoints.next_landing_page_version_dir(kwargs["client"])
        (version_dir / "index.html").write_text("<html><body>Draft</body></html>", encoding="utf-8")
        (version_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (version_dir / "script.js").write_text("", encoding="utf-8")
        (version_dir / "preview.mp4").write_bytes(b"mp4")
        return version_dir

    monkeypatch.setattr(workstation_endpoints, "generate_solo_page_version", fake_generate_solo_page_version)
    monkeypatch.setattr(
        workstation_endpoints,
        "decide_workstation_next_action",
        lambda **kwargs: asyncio.sleep(
            0,
            result=workstation_endpoints.WorkstationAgentDecision(
                action="generate_or_revise_page",
                reason="Existing chat context is enough for a first draft.",
            ),
        ),
    )

    with TestClient(app) as client:
        created = client.post(
            f"/api/workstation/clients/from-lead/{lead.id}",
            params={
                "work_type": "solo_pagina",
                "status": "pending_payment",
                "automation_status": "intake",
            },
        )
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")
        crm_detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert created.status_code == 200
    assert created.json()["client"]["work_type"] == "solo_pagina"
    assert created.json()["client"]["status"] == "pending_payment"
    assert created.json()["client"]["offer_price_usd"] == 49
    assert tick.status_code == 200
    assert tick.json()["intake_messages_sent"] == 0
    assert tick.json()["drafts_generated"] == 1
    assert len(generated_calls) == 1
    assert generated_calls[0]["revision"] is False
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["workstation_preview_video"]
    assert crm_detail.json()["lead"]["automation_paused_reason"] == "manual_workstation_solo_page_conversion"


def test_manual_solo_page_conversion_without_context_sends_intake(monkeypatch, tmp_path) -> None:
    """Manual solo-page starts should still ask intake when the old chat only has interest."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        funnel_id="contadores",
        external_lead_id="sheet-row-manual-solo-page-no-context",
        phone="+5491777777710",
        full_name="Cliente Sin Datos",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Promo pagina profesional por 29 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        whatsapp_template_body_params=["Cliente", "contadores", "Argentina", "29"],
        created_at=now_utc() - timedelta(minutes=5),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Dale",
        created_at=now_utc() - timedelta(seconds=45),
    )

    with TestClient(app) as client:
        created = client.post(
            f"/api/workstation/clients/from-lead/{lead.id}",
            params={
                "work_type": "solo_pagina",
                "status": "pending_payment",
                "automation_status": "intake",
            },
        )
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert created.status_code == 200
    assert created.json()["client"]["offer_price_usd"] == 29
    assert tick.status_code == 200
    assert tick.json()["intake_messages_sent"] == 1
    assert tick.json()["drafts_generated"] == 0
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["workstation_intake"]


def test_workstation_public_page_uses_one_stable_latest_version_url(monkeypatch, tmp_path) -> None:
    """One unguessable URL should keep serving the latest generated page version."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PUBLIC_PAGE_BASE_URL", "https://preview.example.com")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-public-page",
        phone="+5491777777710",
        full_name="Cliente Publico",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    v001 = workstation_endpoints.landing_page_root(workstation) / "v001"
    (v001 / "assets").mkdir(parents=True)
    (v001 / "index.html").write_text(
        "<html><head><link rel='stylesheet' href='./styles.css'></head><body>v001</body></html>",
        encoding="utf-8",
    )
    (v001 / "styles.css").write_text("body { color: red; }", encoding="utf-8")
    (v001 / "script.js").write_text("", encoding="utf-8")

    first_public_page = workstation_endpoints.ensure_workstation_public_page(workstation, v001)
    assert first_public_page is not None
    first_token = first_public_page.public_token

    v002 = workstation_endpoints.landing_page_root(workstation) / "v002"
    (v002 / "assets").mkdir(parents=True)
    (v002 / "index.html").write_text(
        "<html><head><script src='./script.js'></script></head><body>v002</body></html>",
        encoding="utf-8",
    )
    (v002 / "styles.css").write_text("body { color: blue; }", encoding="utf-8")
    (v002 / "script.js").write_text("window.previewVersion = 'v002';", encoding="utf-8")
    second_public_page = workstation_endpoints.ensure_workstation_public_page(workstation, v002)

    assert second_public_page is not None
    assert second_public_page.public_token == first_token
    assert second_public_page.current_version == "v002"
    assert second_public_page.version_path.endswith("landing-page/v002")
    assert workstation_endpoints.workstation_public_page_url(second_public_page) == f"https://preview.example.com/p/{first_token}/"

    with TestClient(app) as client:
        redirect = client.get(f"/p/{first_token}", follow_redirects=False)
        index_response = client.get(f"/p/{first_token}/")
        script_response = client.get(f"/p/{first_token}/script.js")
        invalid_response = client.get("/p/not-a-real-token/")
        traversal_response = client.get(f"/p/{first_token}/../profile.json")

    assert redirect.status_code == 307
    assert redirect.headers["location"] == f"/p/{first_token}/"
    assert index_response.status_code == 200
    assert "v002" in index_response.text
    assert script_response.status_code == 200
    assert "v002" in script_response.text
    assert invalid_response.status_code == 404
    assert traversal_response.status_code == 404


def test_workstation_public_page_backfills_detail_profile_and_agent_context(monkeypatch, tmp_path) -> None:
    """Existing generated pages should get a public row and expose it to UI and Codex."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PUBLIC_PAGE_BASE_URL", "https://preview.example.com")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-public-page-backfill",
        phone="+5491777777711",
        full_name="Cliente Backfill",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html><body>public page</body></html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")

    assert WorkstationPublicPage.get_by_client_id(workstation.id) is None
    assert workstation_endpoints.backfill_workstation_public_pages() == 1

    with TestClient(app) as client:
        detail = client.get(f"/api/workstation/clients/{workstation.id}")

    assert detail.status_code == 200
    public_page = detail.json()["public_page"]
    assert public_page["public_url"].startswith("https://preview.example.com/p/")
    profile = json.loads((workstation_endpoints.client_folder(workstation) / "profile.json").read_text(encoding="utf-8"))
    assert profile["public_page"]["public_url"] == public_page["public_url"]

    context = call_tool(
        run_id="agent-run-workstation-context-public-page",
        tool_name="get_workstation_context",
        arguments={"client_id": workstation.id},
    )
    assert context["ok"] is True
    assert context["result"]["public_page"]["public_url"] == public_page["public_url"]


def test_codex_tool_sends_workstation_public_page_link(monkeypatch, tmp_path) -> None:
    """The Workstation tool should queue the public URL and mark it as sent."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PUBLIC_PAGE_BASE_URL", "https://preview.example.com")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-public-page-tool",
        phone="+5491777777712",
        full_name="Cliente Link",
    )
    add_recent_inbound(lead.id, text="Si, quiero verla publicada")
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html><body>link page</body></html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")
    public_page = workstation_endpoints.ensure_workstation_public_page(workstation, version_dir)
    assert public_page is not None
    assert public_page.last_sent_at is None

    result = call_tool(
        run_id="agent-run-public-page-link",
        tool_name="send_workstation_public_page_link",
        arguments={
            "client_id": workstation.id,
            "text": "Ya esta publicada de prueba: {url}",
            "idempotency_key": "workstation-public-link-1",
        },
    )

    assert result["ok"] is True
    assert result["result"]["queued"] is True
    rows = [message for message in ContadoresMessage.list_by_lead(lead.id) if message.from_me]
    assert [row.sequence_step for row in rows] == ["workstation_public_page_link"]
    assert rows[0].text.startswith("Ya esta publicada de prueba: https://preview.example.com/p/")
    updated_public_page = WorkstationPublicPage.get_by_client_id(workstation.id)
    assert updated_public_page is not None
    assert updated_public_page.last_sent_at is not None


def test_workstation_approval_sends_public_link_before_final_handoff(monkeypatch, tmp_path) -> None:
    """Video approval should send the public trial URL before final approval."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PUBLIC_PAGE_BASE_URL", "https://preview.example.com")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-approval-before-public-link",
        phone="+5491777777713",
        full_name="Cliente Aprueba Video",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html><body>approval gate</body></html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")
    public_page = workstation_endpoints.ensure_workstation_public_page(workstation, version_dir)
    assert public_page is not None
    assert public_page.last_sent_at is None
    preview_at = now_utc() - timedelta(minutes=25)
    ContadoresLead.update_flow_state(
        lead.id,
        booked_at=preview_at - timedelta(minutes=5),
        automation_paused=True,
        automation_paused_reason="workstation_solo_page_started",
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path=workstation_endpoints.relative_data_path(version_dir / "preview.mp4"),
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Me gusta, asi esta bien",
        created_at=now_utc() - timedelta(minutes=21),
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["approvals"] == 0
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["workstation_public_page_link"]
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW
    updated_public_page = WorkstationPublicPage.get_by_client_id(workstation.id)
    assert updated_public_page is not None
    assert updated_public_page.last_sent_at is not None


def test_workstation_periodic_heartbeat_sends_public_link_from_needs_human(monkeypatch, tmp_path) -> None:
    """The 12-hour heartbeat should recover a human-handoff client that asks for the link."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_PUBLIC_PAGE_BASE_URL", "https://preview.example.com")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_ENABLED", True)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS", 12)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-heartbeat-link",
        phone="+5491777777714",
        full_name="Cliente Heartbeat Link",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
    )
    handled_at = now_utc() - timedelta(hours=13)
    preview_at = now_utc() - timedelta(days=1)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=handled_at,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html><body>heartbeat link</body></html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")
    workstation_endpoints.ensure_workstation_public_page(workstation, version_dir)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Subela para verla",
        created_at=now_utc() - timedelta(minutes=25),
    )

    async def fake_decide_workstation_next_action(**kwargs):
        assert kwargs["scheduled_instruction"]
        assert [message.text for message in kwargs["replies"]] == ["Subela para verla"]
        return workstation_endpoints.WorkstationAgentDecision(
            action="send_public_page_link",
            message="Ya esta publicada de prueba: {url}",
            reason="Client asked to see the public page.",
        )

    monkeypatch.setattr(workstation_endpoints, "decide_workstation_next_action", fake_decide_workstation_next_action)

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    payload = tick.json()
    assert payload["scheduled_agent_tasks_created"] == 1
    assert payload["scheduled_agent_tasks_processed"] == 1
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["workstation_public_page_link"]
    public_page = WorkstationPublicPage.get_by_client_id(workstation.id)
    assert public_page is not None
    assert public_page.last_sent_at is not None
    assert ScheduledAgentTask.list_due(now=now_utc()) == []


def test_workstation_periodic_heartbeat_can_choose_no_action(monkeypatch, tmp_path) -> None:
    """A heartbeat no_action should only advance the handled timestamp."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_ENABLED", True)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS", 12)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-heartbeat-no-action",
        phone="+5491777777715",
        full_name="Cliente Heartbeat Quieto",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
    )
    handled_at = now_utc() - timedelta(hours=13)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_automation_handled_at=handled_at,
    )

    async def fake_decide_workstation_next_action(**kwargs):
        assert kwargs["replies"] == []
        return workstation_endpoints.WorkstationAgentDecision(
            action="no_action",
            reason="No useful client-facing action.",
        )

    monkeypatch.setattr(workstation_endpoints, "decide_workstation_next_action", fake_decide_workstation_next_action)

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    payload = tick.json()
    assert payload["scheduled_agent_tasks_created"] == 1
    assert payload["scheduled_agent_tasks_processed"] == 1
    assert pending.json()["messages"] == []
    updated = WorkstationClient.get_by_id(workstation.id)
    assert updated is not None
    assert workstation_endpoints.normalize_utc(updated.last_automation_handled_at) > handled_at


def test_workstation_solo_page_codex_runs_from_repo_root(monkeypatch, tmp_path) -> None:
    """Codex should read repo templates and then validate client-folder outputs."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(workstation_endpoints, "OPENAI_API_KEY", "sk-test")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-codex-cwd",
        phone="+5491777777774",
        full_name="Cliente Cwd",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    calls: list[dict[str, object]] = []

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output folder:\n"
        output_dir = Path(prompt.split(output_marker, 1)[1].splitlines()[0].strip())
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("<html><body>Draft</body></html>", encoding="utf-8")
        (output_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (output_dir / "script.js").write_text("", encoding="utf-8")
        (output_dir / "preview-message.txt").write_text(
            "Cliente Cwd, le comparto el primer boceto para revisar ajustes.",
            encoding="utf-8",
        )
        calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(final_response="created", items=[])

    def fake_render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
        assert index_path.name == "index.html"
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(workstation_endpoints, "render_landing_page_video_sync", fake_render_landing_page_video_sync)

    version_dir = asyncio.run(
        workstation_endpoints.generate_solo_page_version(
            client=workstation,
            lead=lead,
            replies=[],
            revision=False,
        )
    )

    assert (version_dir / "preview.mp4").read_bytes() == b"mp4"
    metadata = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["preview_message"] == "Cliente Cwd, le comparto el primer boceto para revisar ajustes."
    media_assets = WorkstationMediaAsset.list_by_client(workstation.id)
    preview_assets = [asset for asset in media_assets if asset.content_type == "video/mp4"]
    assert len(preview_assets) == 1
    assert preview_assets[0].stored_filename == "generated-page-preview-v001.mp4"
    assert (data_dir / Path(preview_assets[0].stored_path).relative_to("data")).read_bytes() == b"mp4"
    assert len(calls) == 1
    assert Path(calls[0]["cwd"]).resolve() == workstation_endpoints.REPO_ROOT.resolve()
    assert "sandbox_writable_roots" not in calls[0]
    assert "Progress file:" in str(calls[0]["prompt"])
    assert "progress.md" in str(calls[0]["prompt"])
    assert "preview-message.txt" in str(calls[0]["prompt"])
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Starting draft generation" in progress
    assert "Codex finished. Validating generated files." in progress
    assert "Preview media registered in Workstation." in progress


def test_workstation_solo_page_can_queue_multiple_codex_deliverables(monkeypatch, tmp_path) -> None:
    """Codex can ask Workstation to send more than the preview video."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(workstation_endpoints, "OPENAI_API_KEY", "sk-test")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-multi-delivery",
        phone="+5491777777724",
        full_name="Cliente Multi",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Mandame la nueva version y la foto profesional sola.",
        created_at=now_utc() - timedelta(minutes=1),
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    photo_dir = workstation_endpoints.professional_photo_root(workstation) / "v001"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "professional-photo.jpg").write_bytes(b"jpg")

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output folder:\n"
        output_dir = Path(prompt.split(output_marker, 1)[1].splitlines()[0].strip())
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("<html><body>Revision</body></html>", encoding="utf-8")
        (output_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (output_dir / "script.js").write_text("", encoding="utf-8")
        (output_dir / "preview-message.txt").write_text("Le mando la nueva version.", encoding="utf-8")
        (output_dir / "outbound-messages.json").write_text(
            json.dumps(
                {
                    "messages": [
                        {
                            "text": "Le mando la nueva version de la pagina.",
                            "media_type": "video",
                            "media_path": "preview.mp4",
                            "media_filename": "pagina-revision.mp4",
                        },
                        {
                            "text": "Y aca va la foto profesional sola.",
                            "media_type": "image",
                            "media_path": "professional-photo/v001/professional-photo.jpg",
                            "media_filename": "foto-profesional.jpg",
                        },
                    ]
                },
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(final_response="created", items=[])

    def fake_render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(workstation_endpoints, "render_landing_page_video_sync", fake_render_landing_page_video_sync)

    version_dir = asyncio.run(
        workstation_endpoints.generate_solo_page_version(
            client=workstation,
            lead=lead,
            replies=ContadoresMessage.list_by_lead(lead.id),
            revision=True,
        )
    )
    rows = workstation_endpoints.queue_workstation_preview(
        client=workstation,
        lead=lead,
        version_dir=version_dir,
        sequence_step=workstation_endpoints.WORKSTATION_REVISION_SEQUENCE_STEP,
    )

    assert [row.media_type for row in rows] == ["video", "image"]
    assert [row.media_filename for row in rows] == ["pagina-revision.mp4", "foto-profesional.jpg"]
    assert rows[1].media_path.endswith("professional-photo/v001/professional-photo.jpg")


def test_workstation_solo_page_fallback_sends_professional_photo_before_preview(monkeypatch, tmp_path) -> None:
    """Default preview delivery should include the generated photo before the video."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-default-photo-delivery",
        phone="+5491777777734",
        full_name="Cliente Foto Default",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[image] foto.jpg",
        created_at=now_utc() - timedelta(minutes=1),
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    photo_dir = workstation_endpoints.professional_photo_root(workstation) / "v001"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "professional-photo.jpg").write_bytes(b"jpg")
    version_dir = workstation_endpoints.next_landing_page_version_dir(workstation)
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "preview.mp4").write_bytes(b"mp4")
    (version_dir / "preview-message.txt").write_text("Le mando el boceto de la pagina.", encoding="utf-8")

    rows = workstation_endpoints.queue_workstation_preview(
        client=workstation,
        lead=lead,
        version_dir=version_dir,
        sequence_step=workstation_endpoints.WORKSTATION_PREVIEW_SEQUENCE_STEP,
    )

    assert [row.media_type for row in rows] == ["image", "video"]
    assert rows[0].media_path.endswith("professional-photo/v001/professional-photo.jpg")
    assert rows[0].media_filename.endswith("-v001-foto-profesional.jpg")
    assert "foto profesional" in rows[0].text.lower()
    assert rows[1].media_path.endswith("landing-page/v001/preview.mp4")
    assert rows[1].text == "Le mando el boceto de la pagina."


def test_workstation_solo_page_does_not_resend_professional_photo(monkeypatch, tmp_path) -> None:
    """Professional photo delivery should happen only once per client chat."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-single-photo-delivery",
        phone="+5491777777735",
        full_name="Cliente Foto Unica",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[image] foto.jpg",
        created_at=now_utc() - timedelta(minutes=1),
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    photo_dir = workstation_endpoints.professional_photo_root(workstation) / "v001"
    photo_dir.mkdir(parents=True, exist_ok=True)
    (photo_dir / "professional-photo.jpg").write_bytes(b"jpg")
    first_version_dir = workstation_endpoints.next_landing_page_version_dir(workstation)
    first_version_dir.mkdir(parents=True, exist_ok=True)
    (first_version_dir / "preview.mp4").write_bytes(b"mp4")
    (first_version_dir / "preview-message.txt").write_text("Primer boceto.", encoding="utf-8")

    first_rows = workstation_endpoints.queue_workstation_preview(
        client=workstation,
        lead=lead,
        version_dir=first_version_dir,
        sequence_step=workstation_endpoints.WORKSTATION_PREVIEW_SEQUENCE_STEP,
    )

    second_version_dir = workstation_endpoints.next_landing_page_version_dir(workstation)
    second_version_dir.mkdir(parents=True, exist_ok=True)
    (second_version_dir / "preview.mp4").write_bytes(b"mp4")
    (second_version_dir / "preview-message.txt").write_text("Revision.", encoding="utf-8")
    second_rows = workstation_endpoints.queue_workstation_preview(
        client=workstation,
        lead=lead,
        version_dir=second_version_dir,
        sequence_step=workstation_endpoints.WORKSTATION_PREVIEW_SEQUENCE_STEP,
    )

    assert [row.media_type for row in first_rows] == ["image", "video"]
    assert [row.media_type for row in second_rows] == ["video"]
    assert all("professional-photo/" not in (row.media_path or "") for row in second_rows)


def test_workstation_solo_page_codex_falls_back_to_api_key(monkeypatch, tmp_path) -> None:
    """Solo-page generation should retry with OPENAI_API_KEY when ChatGPT Codex fails."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(workstation_endpoints, "CODEX_PREFER_CHATGPT_LOGIN", True)
    monkeypatch.setattr(workstation_endpoints, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(workstation_endpoints, "CONVERSATION_BOT_CODEX_CHATGPT_HOME", "/chatgpt-home")
    monkeypatch.setattr(workstation_endpoints, "CONVERSATION_BOT_CODEX_API_KEY_HOME", "/api-key-home")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-codex-fallback",
        phone="+5491777777718",
        full_name="Cliente Fallback",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    calls: list[dict[str, object]] = []

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        calls.append({"prompt": prompt, **kwargs})
        if kwargs["prefer_chatgpt_login"]:
            raise RuntimeError("chatgpt codex tokens unavailable")
        output_marker = "Required output folder:\n"
        output_dir = Path(prompt.split(output_marker, 1)[1].splitlines()[0].strip())
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "index.html").write_text("<html><body>Draft</body></html>", encoding="utf-8")
        (output_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (output_dir / "script.js").write_text("", encoding="utf-8")
        return SimpleNamespace(final_response="created with api key", items=[])

    def fake_render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
        assert index_path.name == "index.html"
        output_path.write_bytes(b"mp4")

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(workstation_endpoints, "render_landing_page_video_sync", fake_render_landing_page_video_sync)

    version_dir = asyncio.run(
        workstation_endpoints.generate_solo_page_version(
            client=workstation,
            lead=lead,
            replies=[],
            revision=False,
        )
    )

    assert (version_dir / "metadata.json").exists()
    assert [call["prefer_chatgpt_login"] for call in calls] == [True, False]
    assert [call["codex_home"] for call in calls] == ["/chatgpt-home", "/api-key-home"]


def test_workstation_solo_page_codex_reports_both_auth_errors(monkeypatch, tmp_path) -> None:
    """Operator alerts should show the real Codex auth failures, not a generic timeout."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "CODEX_PREFER_CHATGPT_LOGIN", True)
    monkeypatch.setattr(workstation_endpoints, "OPENAI_API_KEY", "sk-test")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-codex-auth-errors",
        phone="+5491777777719",
        full_name="Cliente Auth Error",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        del prompt
        if kwargs["prefer_chatgpt_login"]:
            raise RuntimeError("ChatGPT tokens exhausted")
        raise RuntimeError("OPENAI_API_KEY quota exceeded")

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)

    try:
        asyncio.run(
            workstation_endpoints.generate_solo_page_version(
                client=workstation,
                lead=lead,
                replies=[],
                revision=False,
            )
        )
    except RuntimeError as error:
        message = str(error)
    else:
        raise AssertionError("Expected Codex auth failures to be reported.")

    assert "Codex ChatGPT failed: RuntimeError: ChatGPT tokens exhausted" in message
    assert "Codex API key failed: RuntimeError: OPENAI_API_KEY quota exceeded" in message
    assert "https://auth.openai.com/codex/device" in message


def test_manual_workstation_solo_page_work_uses_operator_prompt(monkeypatch, tmp_path) -> None:
    """Operator-triggered page work should pass the typed prompt into Codex."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-workstation-codex",
        phone="+5491777777711",
        full_name="Marielis Torres",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Soy abogada de familia en Lima y quiero algo serio.",
        created_at=now_utc() - timedelta(minutes=5),
    )
    generated_calls: list[dict[str, object]] = []

    async def fake_generate_solo_page_version(**kwargs) -> Path:
        generated_calls.append(kwargs)
        version_dir = workstation_endpoints.next_landing_page_version_dir(kwargs["client"])
        (version_dir / "index.html").write_text("<html><body>Draft</body></html>", encoding="utf-8")
        (version_dir / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")
        (version_dir / "script.js").write_text("", encoding="utf-8")
        (version_dir / "preview-message.txt").write_text(
            "Marielis, le envio una version mas premium para que me diga si refleja el tono que queria.",
            encoding="utf-8",
        )
        (version_dir / "preview.mp4").write_bytes(b"mp4")
        return version_dir

    monkeypatch.setattr(workstation_endpoints, "generate_solo_page_version", fake_generate_solo_page_version)

    asyncio.run(
        workstation_endpoints.run_manual_solo_page_work(
            workstation.id,
            "Ponete a trabajar y hacele la pagina con tono premium.",
        )
    )

    assert len(generated_calls) == 1
    assert generated_calls[0]["revision"] is False
    assert generated_calls[0]["operator_prompt"] == "Ponete a trabajar y hacele la pagina con tono premium."
    assert [message.text for message in generated_calls[0]["replies"]] == [
        "Soy abogada de familia en Lima y quiero algo serio.",
    ]
    pending = ContadoresMessage.list_pending_delivery(limit=10)
    assert [message.sequence_step for message in pending] == ["workstation_preview_video"]
    assert pending[0].text == (
        "Marielis, le envio una version mas premium para que me diga si refleja el tono que queria."
    )
    updated = WorkstationClient.get_by_id(workstation.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW


def test_manual_workstation_solo_page_endpoint_queues_background_work(monkeypatch, tmp_path) -> None:
    """The Workstation action should return immediately with the client marked as working."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-workstation-endpoint",
        phone="+5491777777712",
        full_name="Cliente Manual",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    queued_coroutines: list[object] = []

    def fake_create_task(coroutine):
        queued_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(workstation_endpoints.asyncio, "create_task", fake_create_task)

    with TestClient(app) as client:
        response = client.post(
            f"/api/workstation/clients/{workstation.id}/solo-page/work",
            json={"prompt": "Hacer pagina ahora con el contexto existente."},
        )

    assert response.status_code == 202
    assert response.json()["client"]["automation_status"] == "drafting"
    assert len(queued_coroutines) == 1
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Manual Codex run queued from Workstation Actions." in progress
    workstation_endpoints.manual_solo_page_work_client_ids.clear()


def test_manual_workstation_solo_page_endpoint_allows_parallel_clients(monkeypatch, tmp_path) -> None:
    """Manual Codex work should only block another run for the same Workstation client."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    first_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-parallel-workstation-1",
        phone="+5491777777713",
        full_name="Cliente Uno",
    )
    second_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-parallel-workstation-2",
        phone="+5491777777714",
        full_name="Cliente Dos",
    )
    first_workstation = WorkstationClient.create_for_lead(
        first_lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    second_workstation = WorkstationClient.create_for_lead(
        second_lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    queued_coroutines: list[object] = []

    def fake_create_task(coroutine):
        queued_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(workstation_endpoints.asyncio, "create_task", fake_create_task)

    with TestClient(app) as client:
        first_response = client.post(
            f"/api/workstation/clients/{first_workstation.id}/solo-page/work",
            json={"prompt": "Hacer la pagina del primero."},
        )
        second_response = client.post(
            f"/api/workstation/clients/{second_workstation.id}/solo-page/work",
            json={"prompt": "Hacer la pagina del segundo."},
        )
        duplicate_response = client.post(
            f"/api/workstation/clients/{first_workstation.id}/solo-page/work",
            json={"prompt": "No arrancar dos veces el mismo cliente."},
        )

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == "Workstation Codex is already working for this client."
    assert len(queued_coroutines) == 2
    workstation_endpoints.manual_solo_page_work_client_ids.clear()


def test_manual_workstation_solo_page_endpoint_restarts_missing_live_process(monkeypatch, tmp_path) -> None:
    """A stale persisted working state should not block a real operator restart."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    workstation_endpoints.active_solo_page_codex_tasks.clear()
    workstation_endpoints.active_solo_page_codex_turns.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-restart-missing-live-workstation",
        phone="+5491777777722",
        full_name="Cliente Restart",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.REVISION_REQUESTED,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.REVISION_REQUESTED,
        last_automation_handled_at=now_utc(),
    )
    workstation_endpoints.manual_solo_page_work_client_ids.add(workstation.id)
    queued_coroutines: list[object] = []

    def fake_create_task(coroutine):
        queued_coroutines.append(coroutine)
        coroutine.close()
        return SimpleNamespace(done=lambda: False)

    monkeypatch.setattr(workstation_endpoints.asyncio, "create_task", fake_create_task)

    with TestClient(app) as client:
        response = client.post(
            f"/api/workstation/clients/{workstation.id}/solo-page/work",
            json={"prompt": "Rehacer con fotos profesionales."},
        )

    assert response.status_code == 202
    assert response.json()["automation_state"]["is_live_working"] is True
    assert len(queued_coroutines) == 1
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Operator restarted Codex because no live backend task or Codex turn was registered." in progress
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    workstation_endpoints.clear_solo_page_live_work(workstation.id)


def test_workstation_solo_page_stop_interrupts_active_codex(monkeypatch, tmp_path) -> None:
    """Operators should be able to stop a running Codex turn for one client."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.active_solo_page_codex_turns.clear()
    workstation_endpoints.solo_page_stop_requested_client_ids.clear()
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stop-workstation-codex",
        phone="+5491777777715",
        full_name="Cliente Stop",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=now_utc(),
    )
    calls = {"interrupts": 0}

    class FakeTurn:
        def interrupt(self) -> None:
            calls["interrupts"] += 1

    workstation_endpoints.active_solo_page_codex_turns[workstation.id] = FakeTurn()

    with TestClient(app) as client:
        response = client.post(f"/api/workstation/clients/{workstation.id}/solo-page/stop")

    assert response.status_code == 200
    assert calls["interrupts"] == 1
    assert response.json()["client"]["automation_status"] == "needs_human"
    assert workstation.id in workstation_endpoints.solo_page_stop_requested_client_ids
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Codex stopped by operator." in progress
    workstation_endpoints.active_solo_page_codex_turns.clear()
    workstation_endpoints.solo_page_stop_requested_client_ids.clear()


def test_workstation_automation_state_reports_missing_live_codex_process(monkeypatch, tmp_path) -> None:
    """A persisted drafting state should not pretend Codex is live after a restart."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.active_solo_page_codex_tasks.clear()
    workstation_endpoints.active_solo_page_codex_turns.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-missing-live-codex",
        phone="+5491777777720",
        full_name="Cliente Sin Proceso",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=now_utc(),
    )
    workstation = WorkstationClient.get_by_id(workstation.id) or workstation

    state = workstation_endpoints.build_workstation_automation_state(workstation, [])

    assert state.label == "No live Codex process"
    assert state.is_working is False
    assert state.is_live_working is False
    assert state.live_status == "not_running"


def test_workstation_automation_state_reports_live_codex_task(monkeypatch, tmp_path) -> None:
    """The UI should be able to distinguish a real running backend task."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.active_solo_page_codex_tasks.clear()
    workstation_endpoints.active_solo_page_codex_turns.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-live-codex",
        phone="+5491777777721",
        full_name="Cliente Live",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=now_utc(),
    )
    workstation = WorkstationClient.get_by_id(workstation.id) or workstation

    fake_task = SimpleNamespace(done=lambda: False)
    workstation_endpoints.register_solo_page_task(workstation.id, fake_task)
    state = workstation_endpoints.build_workstation_automation_state(workstation, [])

    assert state.label == "Codex working"
    assert state.is_working is True
    assert state.is_live_working is True
    assert state.live_status == "background_task_active"
    assert state.has_active_background_task is True
    assert state.live_started_at is not None
    workstation_endpoints.clear_solo_page_live_work(workstation.id)


def test_workstation_progress_logging_uses_module_logger(monkeypatch, tmp_path) -> None:
    """Progress logging fallbacks should not crash with an undefined logger."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-progress-logger",
        phone="+5491777777717",
        full_name="Cliente Logger",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )

    def fail_write_text(*args, **kwargs) -> None:
        raise OSError("disk unavailable")

    progress_path = workstation_endpoints.workstation_progress_path(workstation)
    monkeypatch.setattr(type(progress_path), "write_text", fail_write_text)

    workstation_endpoints.append_workstation_progress(workstation, "This should be logged, not raised.")


def test_workstation_solo_page_steer_sends_message_to_active_codex(monkeypatch, tmp_path) -> None:
    """Operators should be able to steer a running Codex turn for one client."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.active_solo_page_codex_turns.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-steer-workstation-codex",
        phone="+5491777777716",
        full_name="Cliente Steer",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.DRAFTING,
        last_automation_handled_at=now_utc(),
    )
    steered_messages: list[str] = []

    class FakeTurn:
        def steer(self, message: str) -> None:
            steered_messages.append(message)

    workstation_endpoints.active_solo_page_codex_turns[workstation.id] = FakeTurn()

    with TestClient(app) as client:
        response = client.post(
            f"/api/workstation/clients/{workstation.id}/solo-page/steer",
            json={"message": "Hacelo mas sobrio y prioriza la foto profesional."},
        )

    assert response.status_code == 200
    assert [getattr(message, "text", message) for message in steered_messages] == [
        "Hacelo mas sobrio y prioriza la foto profesional."
    ]
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Operator steered Codex: Hacelo mas sobrio" in progress
    workstation_endpoints.active_solo_page_codex_turns.clear()


def test_workstation_tick_approval_marks_needs_human(monkeypatch, tmp_path) -> None:
    """Client approval should stop automation and hand the job to a human operator."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-approved",
        phone="+5491777777773",
        full_name="Cliente Aprobado",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    preview_at = now_utc() - timedelta(minutes=25)
    ContadoresLead.update_flow_state(
        lead.id,
        booked_at=preview_at - timedelta(minutes=5),
        automation_paused=True,
        automation_paused_reason="workstation_solo_page_started",
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    (version_dir / "assets").mkdir(parents=True)
    (version_dir / "index.html").write_text("<html><body>approved public page</body></html>", encoding="utf-8")
    (version_dir / "styles.css").write_text("", encoding="utf-8")
    (version_dir / "script.js").write_text("", encoding="utf-8")
    workstation_endpoints.ensure_workstation_public_page(workstation, version_dir)
    WorkstationPublicPage.mark_sent(workstation.id, sent_at=preview_at)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path="data/workstation/clients/demo/landing-page/v001/preview.mp4",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Me gusta, asi esta bien",
        created_at=now_utc() - timedelta(minutes=21),
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending_alerts = client.get("/api/contadores/alerts/pending?funnel_id=contadores")

    assert tick.status_code == 200
    assert tick.json()["approvals"] == 1
    assert tick.json()["human_handoffs"] == 1
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.NEEDS_HUMAN
    assert updated.approved_at is not None
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused_reason"] == "workstation_solo_page_approved"
    assert pending_alerts.json()["items"][0]["lead_id"] == lead.id
    assert pending_alerts.json()["items"][0]["automation_paused_reason"] == "workstation_solo_page_approved"


def test_workstation_pings_tolerate_naive_preview_timestamp(monkeypatch, tmp_path) -> None:
    """SQLite can return naive datetimes; pings should normalize before subtracting."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-naive-preview",
        phone="+5491777777792",
        full_name="Cliente Preview Naive",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    preview_at = (now_utc() - timedelta(hours=25)).replace(tzinfo=None)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path="data/workstation/clients/demo/landing-page/v001/preview.mp4",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")

    assert tick.status_code == 200
    assert tick.json()["pings_sent"] == 1
    assert tick.json()["failures"] == 0
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW
    assert updated.ping_1_sent_at is not None


def test_workstation_ping_error_does_not_fail_delivered_preview(monkeypatch, tmp_path) -> None:
    """After a preview exists, ping-loop bugs should not alert as Codex delivery failures."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-ping-bug",
        phone="+5491777777794",
        full_name="Cliente Preview Entregado",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    preview_at = now_utc() - timedelta(minutes=10)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path="data/workstation/clients/demo/landing-page/v001/preview.mp4",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )

    def fake_process_workstation_pings(**kwargs) -> int:
        raise TypeError("can't subtract offset-naive and offset-aware datetimes")

    monkeypatch.setattr(workstation_endpoints, "process_workstation_pings", fake_process_workstation_pings)

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")
        detail = client.get(f"/api/workstation/clients/{workstation.id}")

    assert tick.status_code == 200
    assert tick.json()["failures"] == 0
    assert detail.json()["client"]["automation_status"] == "awaiting_review"
    assert detail.json()["runtime_alerts"] == []
    progress = workstation_endpoints.workstation_progress_path(workstation).read_text(encoding="utf-8")
    assert "Nonblocking automation issue: TypeError" in progress
    assert "Automation failed" not in progress


def test_workstation_tick_stops_when_linked_lead_is_closed(monkeypatch, tmp_path) -> None:
    """A CRM-closed lead should not keep Workstation pings retrying every tick."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-closed-lead",
        phone="+5491777777795",
        full_name="Cliente Cerrado",
    )
    closed_at = now_utc() - timedelta(hours=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CLOSED,
        closed_at=closed_at,
        automation_paused=True,
        automation_paused_reason="manual_pause",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    preview_at = closed_at - timedelta(hours=25)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Le mando un video con el boceto de su pagina.",
        sequence_step="workstation_preview_video",
        media_type="video",
        media_path="data/workstation/clients/demo/landing-page/v001/preview.mp4",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        created_at=preview_at,
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")

    assert tick.status_code == 200
    assert tick.json()["pings_sent"] == 0
    assert tick.json()["failures"] == 0
    assert len(ContadoresMessage.list_by_lead(lead.id)) == 1
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.status == WorkstationClientStatus.CLOSED
    assert updated.automation_status == WorkstationAutomationStatus.NEEDS_HUMAN
    progress = workstation_endpoints.workstation_progress_path(updated).read_text(encoding="utf-8")
    assert "Linked CRM lead is closed. Workstation automation stopped." in progress


def test_workstation_heartbeat_skips_closed_linked_lead(monkeypatch, tmp_path) -> None:
    """Periodic Workstation heartbeats should not wake Codex for closed CRM leads."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_ENABLED", True)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS", 12)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-closed-heartbeat",
        phone="+5491777777796",
        full_name="Cliente Cerrado Heartbeat",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CLOSED,
        closed_at=now_utc() - timedelta(hours=1),
        automation_paused=True,
        automation_paused_reason="manual_pause",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
    )
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_automation_handled_at=now_utc() - timedelta(hours=13),
    )

    with TestClient(app) as client:
        tick = client.post("/api/workstation/automation/tick")

    assert tick.status_code == 200
    assert tick.json()["scheduled_agent_tasks_created"] == 0
    assert ScheduledAgentTask.get_open_for_target(
        target_type="workstation_client",
        target_id=workstation.id,
        reason_prefix=workstation_endpoints.WORKSTATION_CODEX_HEARTBEAT_REASON,
    ) is None
    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.status == WorkstationClientStatus.CLOSED


def test_failed_solo_page_reopens_when_lead_replies_after_preview(monkeypatch, tmp_path) -> None:
    """A failed solo-page preview should not stay stuck after the lead replies."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-failed-reopen",
        phone="+5491777777799",
        full_name="Cliente Reabre",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.FAILED,
    )
    preview_at = now_utc() - timedelta(minutes=5)
    WorkstationClient.update_automation_state(
        workstation.id,
        automation_status=WorkstationAutomationStatus.FAILED,
        last_preview_sent_at=preview_at,
        last_automation_handled_at=preview_at + timedelta(seconds=5),
    )

    contadores_endpoints.record_whatsapp_inbound_for_lead(
        lead=lead,
        command=contadores_endpoints.ContadoresWhatsAppInboundCommand(
            phone=lead.phone,
            text="Me gusta, asi esta bien",
            external_id="wamid.reopen-solo-page",
        ),
    )

    updated = WorkstationClient.get_by_lead_id(lead.id)
    assert updated.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW
    assert updated.last_preview_sent_at is not None


def test_workstation_failure_is_visible_and_pending_email_alert(monkeypatch, tmp_path) -> None:
    """Workstation failures must be visible in UI data and queued for operator email."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-visible-failure",
        phone="+5491777777800",
        full_name="Cliente Falla Visible",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.DRAFTING,
    )

    workstation_endpoints.mark_workstation_failed(
        client=workstation,
        lead=lead,
        error="RuntimeError: codex render failed",
        latest_inbound_text="Adjunto fotos nuevas",
    )

    with TestClient(app) as client:
        detail = client.get(f"/api/workstation/clients/{workstation.id}")
        pending = client.get("/api/contadores/alerts/pending?funnel_id=contadores")

    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["client"]["automation_status"] == "failed"
    assert detail_payload["runtime_alerts"][0]["alert_type"] == "workstation_codex_failure"
    assert detail_payload["runtime_alerts"][0]["error"] == "RuntimeError: codex render failed"
    assert detail_payload["runtime_alerts"][0]["notified_at"] is None
    pending_payload = pending.json()
    runtime_items = [item for item in pending_payload["items"] if item["alert_kind"] == "runtime"]
    assert len(runtime_items) == 1
    assert runtime_items[0]["runtime_alert_id"] == detail_payload["runtime_alerts"][0]["id"]
    assert runtime_items[0]["alert_emails"] == ["facu@example.com"]
    assert runtime_items[0]["codex_error"] == "RuntimeError: codex render failed"


def test_workstation_clients_can_be_filtered_by_funnel(monkeypatch, tmp_path) -> None:
    """Workstation lists should stay separated by funnel."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    contadores_lead = ContadoresLead.upsert(
        funnel_id="contadores",
        external_lead_id="sheet-row-workstation-contadores",
        phone="+5491777777777",
        full_name="Cliente Contadores",
    )
    abogados_lead = ContadoresLead.upsert(
        funnel_id="abogados",
        external_lead_id="sheet-row-workstation-abogados",
        phone="+5491888888888",
        full_name="Cliente Abogados",
    )

    with TestClient(app) as client:
        client.post(f"/api/workstation/clients/from-lead/{contadores_lead.id}")
        client.post(f"/api/workstation/clients/from-lead/{abogados_lead.id}")
        contadores_response = client.get("/api/workstation/clients?funnel_id=contadores")
        abogados_response = client.get("/api/workstation/clients?funnel_id=abogados")

    assert contadores_response.status_code == 200
    assert abogados_response.status_code == 200
    assert [item["funnel_id"] for item in contadores_response.json()["clients"]] == ["contadores"]
    assert [item["funnel_id"] for item in abogados_response.json()["clients"]] == ["abogados"]


def test_workstation_notes_media_and_zip_are_persisted(monkeypatch, tmp_path) -> None:
    """Notes, uploaded media, and zip exports should mirror the client folder."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-files",
        phone="+5491888888888",
        full_name="Cliente Files",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Necesito una web seria y tres campañas.",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}").json()
        client_id = created["client"]["id"]
        notes_response = client.put(
            f"/api/workstation/clients/{client_id}/notes",
            json={"notes": "Notas de reunion\nQuiere landing premium."},
        )
        upload_response = client.post(
            f"/api/workstation/clients/{client_id}/media",
            data={"title": "Logo actual"},
            files={"file": ("logo.png", b"image-bytes", "image/png")},
        )
        update_media_response = client.put(
            f"/api/workstation/clients/{client_id}/media/{upload_response.json()['id']}",
            json={"title": "Logo final", "original_filename": "logo-final.png"},
        )
        copy_response = client.get(f"/api/workstation/clients/{client_id}/copy-all")
        zip_response = client.get(f"/api/workstation/clients/{client_id}/zip")

    assert notes_response.status_code == 200
    assert upload_response.status_code == 200
    assert upload_response.json()["title"] == "Logo actual"
    assert upload_response.json()["stored_path"].startswith("data/workstation/clients/")
    assert update_media_response.status_code == 200
    assert update_media_response.json()["title"] == "Logo final"
    assert update_media_response.json()["original_filename"] == "logo-final.png"
    assert "Notas de reunion" in copy_response.json()["text"]
    assert "Necesito una web seria" in copy_response.json()["text"]
    assert "Logo final" in copy_response.json()["text"]

    folder = data_dir / "workstation" / "clients" / created["client"]["folder_name"]
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "Notas de reunion\nQuiere landing premium."
    assert "Necesito una web seria" in (folder / "conversation.txt").read_text(encoding="utf-8")
    assert (folder / "media" / upload_response.json()["stored_filename"]).read_bytes() == b"image-bytes"

    assert zip_response.status_code == 200
    with zipfile.ZipFile(BytesIO(zip_response.content)) as archive:
        names = set(archive.namelist())
        assert "notes.txt" in names
        assert f"media/{upload_response.json()['stored_filename']}" in names
        assert "profile.json" not in names
        assert "conversation.txt" not in names


def test_workstation_upload_rejects_oversized_media(monkeypatch, tmp_path) -> None:
    """Workstation uploads should be capped before writing files."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_MEDIA_MAX_UPLOAD_BYTES", 4)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-oversized-media",
        phone="+5491888888889",
        full_name="Cliente Media Grande",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}").json()
        response = client.post(
            f"/api/workstation/clients/{created['client']['id']}/media",
            files={"file": ("large.png", b"12345", "image/png")},
        )

    assert response.status_code == 413
    media_dir = data_dir / "workstation" / "clients" / created["client"]["folder_name"] / "media"
    assert list(media_dir.glob("*")) == []


def test_workstation_public_page_deactivates_on_manual_close(monkeypatch, tmp_path) -> None:
    """Closing a Workstation client should stop serving its public token."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-public-close",
        phone="+5491888888890",
        full_name="Cliente Cierra Publico",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    version_dir = workstation_endpoints.landing_page_root(workstation) / "v001"
    version_dir.mkdir(parents=True)
    (version_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    public_page = workstation_endpoints.ensure_workstation_public_page(workstation, version_dir)
    assert public_page is not None

    with TestClient(app) as client:
        assert client.get(f"/p/{public_page.public_token}/").status_code == 200
        close_response = client.post(f"/api/workstation/clients/{workstation.id}/close")
        closed_public = client.get(f"/p/{public_page.public_token}/")

    assert close_response.status_code == 200
    assert closed_public.status_code == 404
    assert WorkstationPublicPage.get_by_client_id(workstation.id).status != "active"


def test_workstation_prune_candidates_skip_current_public_version(monkeypatch, tmp_path) -> None:
    """Explicit pruning should never list the active public page version."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(workstation_endpoints, "WORKSTATION_MAX_LANDING_PAGE_VERSIONS", 1)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-prune",
        phone="+5491888888891",
        full_name="Cliente Prune",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    v001 = workstation_endpoints.landing_page_root(workstation) / "v001"
    v002 = workstation_endpoints.landing_page_root(workstation) / "v002"
    for version in (v001, v002):
        version.mkdir(parents=True)
        (version / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    workstation_endpoints.ensure_workstation_public_page(workstation, v001)

    candidates = workstation_endpoints.prune_workstation_artifacts(workstation, confirm=False)

    assert candidates == []
    assert v001.exists()
    assert v002.exists()


def test_workstation_professional_photo_versions_use_codex_context(monkeypatch, tmp_path) -> None:
    """Professional photo endpoints should create deterministic generated versions."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    calls: list[dict[str, object]] = []

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output path:\n"
        output_path = prompt.split(output_marker, 1)[1].splitlines()[0].strip()
        Path(output_path).write_bytes(b"generated-jpg")
        calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(final_response=f"created {output_path}", items=[])

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-photo",
        phone="+5491888888888",
        full_name="Cliente Foto",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}").json()
        client_id = created["client"]["id"]
        media_response = client.post(
            f"/api/workstation/clients/{client_id}/media",
            data={"title": "Foto fuente"},
            files={"file": ("cliente.jpg", b"source-jpg", "image/jpeg")},
        )
        media_id = media_response.json()["id"]
        photo_response = client.post(
            f"/api/workstation/clients/{client_id}/professional-photo",
            json={"media_asset_ids": [media_id], "context": "abogado premium"},
        )
        edit_response = client.post(
            f"/api/workstation/clients/{client_id}/professional-photo/edit",
            json={"base_version": "v001", "prompt": "mas formal", "media_asset_ids": [media_id]},
        )
        detail_response = client.get(f"/api/workstation/clients/{client_id}")
        file_response = client.get(f"/api/workstation/clients/{client_id}/professional-photo/v002/file")

    assert photo_response.status_code == 200
    assert photo_response.json()["version"] == "v001"
    assert photo_response.json()["image_path"].endswith("professional-photo/v001/professional-photo.jpg")
    assert edit_response.status_code == 200
    assert edit_response.json()["version"] == "v002"
    assert [photo["version"] for photo in detail_response.json()["professional_photos"]] == ["v001", "v002"]
    generated_media = [
        asset
        for asset in detail_response.json()["media"]
        if asset["stored_filename"].startswith("generated-professional-photo-")
    ]
    assert {asset["stored_filename"] for asset in generated_media} == {
        "generated-professional-photo-v001.jpg",
        "generated-professional-photo-v002.jpg",
    }
    assert file_response.status_code == 200
    assert file_response.content == b"generated-jpg"
    assert len(calls) == 2
    assert calls[0]["local_images"]
    assert "client-professional-photo" in calls[0]["prompt"]
    assert "client-professional-photo-edit" in calls[1]["prompt"]


def test_workstation_professional_photo_job_can_be_polled(monkeypatch, tmp_path) -> None:
    """Async professional photo jobs should expose status until the result is ready."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output path:\n"
        output_path = prompt.split(output_marker, 1)[1].splitlines()[0].strip()
        Path(output_path).write_bytes(b"generated-job-jpg")
        return SimpleNamespace(final_response=f"created {output_path}", items=[])

    async def run_inline(coro) -> None:
        await coro

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
    monkeypatch.setattr(workstation_endpoints, "schedule_background_task", run_inline)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-photo-job",
        phone="+5491777777777",
        full_name="Cliente Job Foto",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}").json()
        client_id = created["client"]["id"]
        media_response = client.post(
            f"/api/workstation/clients/{client_id}/media",
            data={"title": "Foto fuente"},
            files={"file": ("cliente.jpg", b"source-jpg", "image/jpeg")},
        )
        media_id = media_response.json()["id"]
        start_response = client.post(
            f"/api/workstation/clients/{client_id}/professional-photo/jobs",
            json={"media_asset_ids": [media_id], "context": "contador premium"},
        )
        job_id = start_response.json()["job_id"]

        status_response = client.get(f"/api/workstation/clients/{client_id}/professional-photo/jobs/{job_id}")
        detail_response = client.get(f"/api/workstation/clients/{client_id}")
        workstation_endpoints.reset_professional_photo_jobs()
        recovered_status_response = client.get(f"/api/workstation/clients/{client_id}/professional-photo/jobs/{job_id}")

    assert start_response.status_code == 202
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "completed"
    assert status_payload["result"]["version"] == "v001"
    assert status_payload["result"]["image_path"].endswith("professional-photo/v001/professional-photo.jpg")
    assert recovered_status_response.status_code == 200
    assert recovered_status_response.json()["status"] == "completed"
    assert recovered_status_response.json()["result"]["version"] == "v001"
    assert [photo["version"] for photo in detail_response.json()["professional_photos"]] == ["v001"]


def test_workstation_professional_photo_job_reports_restart_failure(monkeypatch, tmp_path) -> None:
    """A queued in-memory job should not become a 404 after a backend restart."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)

    async def keep_queued(coro) -> None:
        coro.close()

    monkeypatch.setattr(workstation_endpoints, "schedule_background_task", keep_queued)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-photo-job-restart",
        phone="+5491777777778",
        full_name="Cliente Job Restart",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}").json()
        client_id = created["client"]["id"]
        media_response = client.post(
            f"/api/workstation/clients/{client_id}/media",
            data={"title": "Foto fuente"},
            files={"file": ("cliente.jpg", b"source-jpg", "image/jpeg")},
        )
        media_id = media_response.json()["id"]
        start_response = client.post(
            f"/api/workstation/clients/{client_id}/professional-photo/jobs",
            json={"media_asset_ids": [media_id], "context": "contador premium"},
        )
        job_id = start_response.json()["job_id"]
        workstation_endpoints.reset_professional_photo_jobs()
        status_response = client.get(f"/api/workstation/clients/{client_id}/professional-photo/jobs/{job_id}")

    assert start_response.status_code == 202
    assert start_response.json()["status"] == "queued"
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "failed"
    assert "restarted" in status_response.json()["error"]
