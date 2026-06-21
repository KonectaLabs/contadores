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



def test_platform_meeting_calendar_gate_builds_and_creates_event(monkeypatch, tmp_path) -> None:
    """Meeting scheduling should build the Calendar payload and gate live writes on credentials."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_DELEGATED_USER", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_OAUTH_CREDENTIALS_FILE", raising=False)
    scheduled_at = datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-platform-meeting",
        phone="+5491333333301",
        full_name="Platform Meeting Lead",
    )
    meeting_result = call_tool(
        run_id="agent-run-calendar",
        tool_name="create_platform_meeting",
        arguments={
            "lead_id": lead.id,
            "client_id": "client-calendar-1",
            "funnel_id": "abogados",
            "lead_email": "Lead.Calendar@Example.com",
            "timezone": "America/Argentina/Buenos_Aires",
            "requested_day": "martes",
            "requested_time": "15:00",
            "context_summary": "Lead quiere confirmar si el plan de 599 incluye pagina.",
            "scheduled_at": scheduled_at,
            "idempotency_key": "meeting-calendar-1",
        },
    )
    assert meeting_result["ok"] is True
    meeting_id = meeting_result["result"]["meeting"]["id"]

    dry_result = call_tool(
        run_id="agent-run-calendar",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "idempotency_key": "schedule-meeting-agent-1",
        },
    )
    assert dry_result["ok"] is True
    assert dry_result["result"]["calendar"]["status"] == "calendar_ready"
    assert dry_result["result"]["calendar"]["live_write_executed"] is False
    assert dry_result["result"]["calendar"]["attendees"] == [
        "lead.calendar@example.com",
        "facundo@example.com",
        "yoel@example.com",
    ]
    assert dry_result["result"]["calendar"]["event_payload"]["start"]["timeZone"] == "America/Argentina/Buenos_Aires"
    assert dry_result["result"]["calendar"]["event_payload"]["start"]["dateTime"] == "2026-07-02T15:00:00-03:00"
    assert PlatformMeeting.get_by_id(meeting_id).status == "calendar_ready"

    blocked_live = call_tool(
        run_id="agent-run-calendar",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "live_writes_requested": True,
            "idempotency_key": "schedule-meeting-blocked-1",
        },
    )
    assert blocked_live["ok"] is True
    assert blocked_live["result"]["calendar"]["status"] == "calendar_blocked"
    assert "GOOGLE_CALENDAR_CREDENTIALS" in blocked_live["result"]["calendar"]["blocked_reasons"]
    assert "GOOGLE_CALENDAR_DELEGATED_USER" not in blocked_live["result"]["calendar"]["blocked_reasons"]

    insert_calls: list[dict] = []

    def fake_insert(calendar_id: str, event_payload: dict, send_updates: str, conference_data_version: int) -> dict:
        assert calendar_id == "team-calendar@example.com"
        assert send_updates == "all"
        assert conference_data_version == 0
        assert "attendees" not in event_payload
        assert "conferenceData" not in event_payload
        insert_calls.append(event_payload)
        return {"id": "calendar-event-1", "htmlLink": "https://calendar.google.com/event?eid=1"}

    monkeypatch.setenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE", str(tmp_path / "service-account.json"))
    monkeypatch.setattr(calendar_events_module, "_insert_google_calendar_event", fake_insert)
    live_result = call_tool(
        run_id="agent-run-calendar",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "create_google_meet": True,
            "live_writes_requested": True,
            "idempotency_key": "schedule-meeting-live-1",
        },
    )
    assert live_result["ok"] is True
    assert live_result["result"]["calendar"]["status"] == "scheduled"
    assert live_result["result"]["calendar"]["calendar_event_id"] == "calendar-event-1"
    warning_text = " ".join(live_result["result"]["calendar"]["warnings"])
    assert "without Google attendees" in warning_text
    assert "without Meet" in warning_text
    scheduled = PlatformMeeting.get_by_id(meeting_id)
    assert scheduled.status == "scheduled"
    assert scheduled.calendar_event_id == "calendar-event-1"
    assert scheduled.calendar_event_link == "https://calendar.google.com/event?eid=1"
    refreshed_lead = ContadoresLead.get_by_id(lead.id)
    assert refreshed_lead.meeting_scheduled_at == scheduled.scheduled_at
    assert refreshed_lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
    assert refreshed_lead.pipeline_stage == "meeting_sent"
    assert refreshed_lead.booked_at is None
    assert refreshed_lead.automation_paused is True
    assert refreshed_lead.automation_paused_reason == "meeting_scheduled"
    assert PlatformEvent.list_recent(target_type="meeting", target_id=meeting_id)[0].event_type == "meeting.calendar_event_checked"
    assert len(insert_calls) == 1

    duplicate_live_result = call_tool(
        run_id="agent-run-calendar",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "live_writes_requested": True,
            "idempotency_key": "schedule-meeting-after-live-1",
        },
    )
    assert duplicate_live_result["ok"] is True
    assert duplicate_live_result["result"]["calendar"]["status"] == "scheduled"
    assert duplicate_live_result["result"]["calendar"]["live_write_executed"] is False
    assert duplicate_live_result["result"]["calendar"]["calendar_event_id"] == "calendar-event-1"
    assert len(insert_calls) == 1

    dry_after_scheduled = call_tool(
        run_id="agent-run-calendar",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "idempotency_key": "schedule-meeting-dry-after-1",
        },
    )
    assert dry_after_scheduled["ok"] is True
    assert dry_after_scheduled["result"]["calendar"]["status"] == "scheduled"
    assert PlatformMeeting.get_by_id(meeting_id).status == "scheduled"


def test_platform_lifecycle_endpoints_support_agent_native_workflow(monkeypatch, tmp_path) -> None:
    """Lifecycle endpoints should expose the full platform without requiring UI configuration."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(profile_extraction_module, "run_client_profile_extraction", fake_profile_extraction)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    client = TestClient(app)

    meeting_response = client.post(
        "/api/platform/meetings",
        json={
            "lead_id": "lead-123",
            "client_id": "client-123",
            "funnel_id": "dentistas",
            "lead_email": "Lead@Example.com",
            "timezone": "America/Argentina/Buenos_Aires",
            "requested_day": "martes",
            "requested_time": "15:00",
            "context_summary": "Lead quiere saber si el plan incluye pagina.",
            "scheduled_at": (now_utc() + timedelta(days=1)).isoformat(),
        },
    )
    assert meeting_response.status_code == 200
    meeting = meeting_response.json()
    assert meeting["lead_email"] == "lead@example.com"

    calendar_response = client.post(
        f"/api/platform/meetings/{meeting['id']}/calendar-event",
        json={
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
        },
    )
    assert calendar_response.status_code == 200
    assert calendar_response.json()["calendar"]["status"] == "calendar_ready"

    transcript_response = client.post(
        f"/api/platform/meetings/{meeting['id']}/transcript",
        json={
            "transcript_text": "El cliente vende implantes y quiere pacientes premium.",
            "extracted_profile": {"offer": "implantes dentales"},
        },
    )
    assert transcript_response.status_code == 200
    assert transcript_response.json()["extracted_profile"]["offer"] == "implantes dentales"

    extraction_response = client.post(
        f"/api/platform/meetings/{meeting['id']}/extract-client-profile",
        json={"status": "draft"},
    )
    assert extraction_response.status_code == 200
    extracted = extraction_response.json()
    assert extracted["profile"]["business_summary"].startswith("Clinica dental")
    assert extracted["profile"]["knowledge"]["meta_planning"]["objective"] == "OUTCOME_LEADS"
    assert extracted["meeting"]["status"] == "profile_extracted"
    assert extracted["meeting"]["extracted_profile"]["profile_id"] == extracted["profile"]["id"]
    assert extracted["extraction"]["source_snippets"][0]["topic"] == "oferta"

    profile_response = client.post(
        "/api/platform/client-profiles",
        json={
            "client_id": "client-123",
            "lead_id": "lead-123",
            "funnel_id": "dentistas",
            "source_meeting_id": meeting["id"],
            "business_summary": "Clinica dental de implantes.",
            "offer_summary": "Evaluacion inicial para pacientes premium.",
            "segments": [{"name": "pacientes premium"}],
            "knowledge": {"city": "Montevideo"},
        },
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["knowledge"]["city"] == "Montevideo"

    campaign_response = client.post(
        "/api/platform/ad-campaigns",
        json={
            "client_id": "client-123",
            "funnel_id": "dentistas",
            "objective": "Generar consultas calificadas por WhatsApp.",
            "budget_daily_usd": 20,
            "target_segments": [{"name": "implantes"}],
            "angles": [{"hook": "Recupera tu sonrisa"}],
        },
    )
    assert campaign_response.status_code == 200
    campaign = campaign_response.json()

    asset_response = client.post(
        "/api/platform/creative-assets",
        json={
            "campaign_id": campaign["id"],
            "client_id": "client-123",
            "asset_type": "image",
            "prompt": "Foto profesional de consultorio dental moderno.",
            "file_path": "media/ads/client-123/creative.png",
        },
    )
    assert asset_response.status_code == 200
    assert asset_response.json()["campaign_id"] == campaign["id"]

    publish_response = client.post(
        "/api/platform/meta-publish-attempts",
        json={
            "campaign_id": campaign["id"],
            "request_payload": {"campaign_name": "Dentistas text offer"},
            "approval_status": "pending",
        },
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["request_payload"]["campaign_name"] == "Dentistas text offer"
    publish_attempt = publish_response.json()

    preflight_response = client.post(f"/api/platform/meta-publish-attempts/{publish_attempt['id']}/preflight", json={})
    assert preflight_response.status_code == 200
    assert preflight_response.json()["preflight"]["status"] == "blocked"
    assert "schema_version" in preflight_response.json()["preflight"]["blocked_reasons"]

    execution_response = client.post(
        f"/api/platform/meta-publish-attempts/{publish_attempt['id']}/execute",
        json={"live_writes_requested": True},
    )
    assert execution_response.status_code == 200
    assert execution_response.json()["execution"]["status"] == "blocked"
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in execution_response.json()["execution"]["blocked_reasons"]

    inventory_response = client.post("/api/platform/meta-inventory/sync", json={})
    assert inventory_response.status_code == 200
    assert inventory_response.json()["snapshot"]["status"] == "missing_credentials"
    assert "META_MARKETING_ACCESS_TOKEN" in inventory_response.json()["result"]["errors"]
    assert client.get("/api/platform/meta-inventory").json()["snapshots"][0]["status"] == "missing_credentials"

    update_response = client.post(
        "/api/platform/client-updates",
        json={
            "client_id": "client-123",
            "campaign_id": campaign["id"],
            "summary_text": "Entraron 3 interesados en las primeras 24 horas.",
            "leads_count": 3,
            "next_action": "Optimizar anuncio con mejor tasa de respuesta.",
        },
    )
    assert update_response.status_code == 200
    assert update_response.json()["leads_count"] == 3

    question_response = client.post(
        "/api/platform/human-questions",
        json={
            "workflow": "meta_publish",
            "target_type": "ad_campaign",
            "target_id": campaign["id"],
            "funnel_id": "dentistas",
            "context_summary": "Meta pide confirmar categoria especial.",
            "trying_to_do": "Publicar campana para el cliente.",
            "question": "Uso categoria especial o publico normal?",
            "options": ["especial", "normal"],
            "default_action": "Si no hay respuesta en 4 minutos, dejar staged.",
        },
    )
    assert question_response.status_code == 200
    question = question_response.json()
    assert question["trying_to_do"] == "Publicar campana para el cliente."

    answer_response = client.post(
        f"/api/platform/human-questions/{question['id']}/answer",
        json={"answer_text": "Dejalo staged hasta revisar la categoria."},
    )
    assert answer_response.status_code == 200
    assert answer_response.json()["status"] == "answered"

    assert client.get("/api/platform/meetings").json()["meetings"][0]["id"] == meeting["id"]
    assert client.get("/api/platform/ad-campaigns").json()["campaigns"][0]["id"] == campaign["id"]
    overview = client.get("/api/platform/overview")
    assert overview.status_code == 200
    overview_payload = overview.json()
    assert overview_payload["counts"]["meetings"] == 1
    assert overview_payload["counts"]["campaigns"] == 1
    assert overview_payload["counts"]["pending_campaigns"] == 1
    assert overview_payload["counts"]["blocked_meta_inventory"] == 1
    assert overview_payload["counts"]["meta_inventory_snapshots"] == 1
    assert overview_payload["counts"]["active_blockers"] == 2
    assert overview_payload["ad_campaigns"][0]["id"] == campaign["id"]
    assert overview_payload["meta_inventory_snapshots"][0]["status"] == "missing_credentials"
    assert overview_payload["human_questions"][0]["status"] == "answered"
    assert overview_payload["events"]
    events = client.get("/api/platform/events", params={"target_type": "human_question", "target_id": question["id"]})
    assert events.status_code == 200
    assert events.json()["events"][0]["event_type"] == "human_question.answered"


def test_platform_creative_asset_upload_persists_media(monkeypatch, tmp_path) -> None:
    """Operators should be able to upload ad images/videos instead of only typing notes."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    client = TestClient(app)

    image_bytes = b"\x89PNG\r\n\x1a\ncreative-image"
    response = client.post(
        "/api/platform/creative-assets/upload",
        data={"client_id": "client-123", "prompt": "Imagen principal del anuncio."},
        files={"file": ("anuncio.png", image_bytes, "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_type"] == "image"
    assert payload["client_id"] == "client-123"
    assert payload["file_path"].startswith("data/platform/creative-assets/")
    assert payload["media_url"].endswith(f"/api/platform/creative-assets/{payload['id']}/file")
    assert PlatformCreativeAsset.get_by_id(payload["id"]).file_path == payload["file_path"]

    file_response = client.get(f"/api/platform/creative-assets/{payload['id']}/file")
    assert file_response.status_code == 200
    assert file_response.content == image_bytes


def test_codex_agent_lifecycle_tools_work_without_ui(monkeypatch, tmp_path) -> None:
    """Agent tools should cover post-conversion, ads, delivery updates, and doubts."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(profile_extraction_module, "run_client_profile_extraction", fake_profile_extraction)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    meeting_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="create_platform_meeting",
        arguments={
            "lead_id": "lead-agent-1",
            "client_id": "client-agent-1",
            "funnel_id": "abogados",
            "lead_email": "lead-agent@example.com",
            "timezone": "America/Argentina/Buenos_Aires",
            "requested_day": "jueves",
            "requested_time": "10:30",
            "context_summary": "Lead quiere avanzar con el plan mensual.",
            "scheduled_at": now_utc() + timedelta(days=2),
            "idempotency_key": "meeting-agent-1",
        },
    )
    assert meeting_result["ok"] is True
    meeting_id = meeting_result["result"]["meeting"]["id"]

    schedule_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="schedule_platform_meeting",
        arguments={
            "meeting_id": meeting_id,
            "calendar_id": "team-calendar@example.com",
            "internal_attendees": ["facundo@example.com", "yoel@example.com"],
            "idempotency_key": "schedule-lifecycle-agent-1",
        },
    )
    assert schedule_result["ok"] is True
    assert schedule_result["result"]["calendar"]["status"] == "calendar_ready"

    transcript_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="attach_meeting_transcript",
        arguments={
            "meeting_id": meeting_id,
            "transcript_text": "El abogado quiere casos laborales.",
            "extracted_profile": {"service": "laboral"},
            "idempotency_key": "attach-transcript-agent-1",
        },
    )
    assert transcript_result["ok"] is True
    assert PlatformMeeting.get_by_id(meeting_id).extracted_profile()["service"] == "laboral"

    extraction_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="extract_client_profile_from_meeting_transcript",
        arguments={
            "meeting_id": meeting_id,
            "client_id": "client-agent-1",
            "idempotency_key": "extract-profile-agent-1",
            "lead_id": "lead-agent-1",
            "funnel_id": "abogados",
        },
    )
    assert extraction_result["ok"] is True
    assert extraction_result["result"]["profile"]["knowledge"]["meta_planning"]["lead_destination"] == "whatsapp"
    assert PlatformMeeting.get_by_id(meeting_id).extracted_profile()["profile_id"] == extraction_result["result"]["profile"]["id"]

    profile_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="upsert_client_profile",
        arguments={
            "client_id": "client-agent-1",
            "lead_id": "lead-agent-1",
            "funnel_id": "abogados",
            "source_meeting_id": meeting_id,
            "business_summary": "Estudio juridico laboral.",
            "offer_summary": "Consulta inicial sin cargo.",
            "segments": [{"name": "empleados despedidos"}],
            "idempotency_key": "profile-agent-1",
        },
    )
    assert profile_result["ok"] is True
    assert PlatformClientProfile.list_recent(client_id="client-agent-1")[0].segments()[0]["name"] == "empleados despedidos"

    campaign_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="stage_ad_campaign",
        arguments={
            "client_id": "client-agent-1",
            "funnel_id": "abogados",
            "objective": "Conseguir consultas laborales por WhatsApp.",
            "budget_daily_usd": 15,
            "angles": [{"hook": "Te despidieron?"}],
            "creative_benchmark": {
                "name": "eliana_v3",
                "reference_assets": [
                    "media/ads/eliana-garcia/ads/v3/01-abogada-te-ayudo-a-cobrar.png",
                    "media/ads/eliana-garcia/ads/v3/02-abogada-art-reclamar.png",
                    "media/ads/eliana-garcia/ads/v3/03-abogada-ordena-proceso.png",
                ],
                "strongest_reference": "rear-end crashed car with a stressed person and dominant problem headline",
            },
            "creative_testing": {
                "concept_count": 3,
                "variations_per_concept": 10,
                "selection_strategy": "publish all variants in Meta and let delivery optimize to winners",
            },
            "idempotency_key": "campaign-agent-1",
        },
    )
    assert campaign_result["ok"] is True
    campaign_id = campaign_result["result"]["campaign"]["id"]
    campaign = PlatformAdCampaign.list_recent(client_id="client-agent-1")[0]
    assert campaign.id == campaign_id
    assert campaign.creative_benchmark()["name"] == "eliana_v3"
    assert campaign.creative_testing()["variations_per_concept"] == 10
    assert campaign_result["result"]["campaign"]["creative_testing"]["selection_strategy"].startswith("publish all")

    asset_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="stage_creative_asset",
        arguments={
            "campaign_id": campaign_id,
            "client_id": "client-agent-1",
            "asset_type": "image",
            "prompt": "Persona revisando recibo de sueldo con abogado.",
            "file_path": "media/ads/client-agent-1/laboral.png",
            "idempotency_key": "asset-agent-1",
        },
    )
    assert asset_result["ok"] is True
    assert PlatformCreativeAsset.list_recent(campaign_id=campaign_id)[0].asset_type == "image"

    publish_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="stage_meta_publish_attempt",
        arguments={
            "campaign_id": campaign_id,
            "request_payload": {"objective": "LEADS"},
            "approval_status": "pending",
            "idempotency_key": "publish-agent-1",
        },
    )
    assert publish_result["ok"] is True
    assert PlatformMetaPublishAttempt.list_recent(campaign_id=campaign_id)[0].request_payload()["objective"] == "LEADS"

    blocked_plan_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": campaign_id,
            "client_id": "client-agent-1",
            "funnel_id": "abogados",
            "campaign_name": "Plan incompleto",
            "idempotency_key": "publish-plan-blocked-agent-1",
        },
    )
    assert blocked_plan_result["ok"] is True
    assert blocked_plan_result["result"]["attempt"]["status"] == "blocked"
    assert "ad_account_id" in blocked_plan_result["result"]["required_before_live_publish"]
    assert "ad_sets" in blocked_plan_result["result"]["required_before_live_publish"]

    plan_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": campaign_id,
            "client_id": "client-agent-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_123",
            "campaign_name": "Abogados laborales - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_123",
                "whatsapp_phone_number_id": "wa_phone_123",
            },
            "ad_sets": [
                {
                    "name": "Despidos CABA",
                    "budget_daily_usd": 15,
                    "targeting": {"geo_locations": {"cities": [{"key": "Buenos Aires"}]}},
                    "ads": [
                        {
                            "name": "Te despidieron",
                            "creative": {
                                "creative_asset_id": "creative-1",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-agent-1",
        },
    )
    assert plan_result["ok"] is True
    assert plan_result["result"]["required_before_live_publish"] == []
    plan_payload = PlatformMetaPublishAttempt.list_recent(campaign_id=campaign_id)[0].request_payload()
    assert plan_payload["schema_version"] == "konecta.meta_publish_plan.v1"
    assert plan_payload["campaign"]["create_status"] == "PAUSED"
    assert plan_payload["ad_sets"][0]["ads"][0]["creative"]["headline"] == "Te despidieron?"

    preflight_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": plan_result["result"]["attempt"]["id"],
            "idempotency_key": "preflight-agent-1",
        },
    )
    assert preflight_result["ok"] is True
    assert preflight_result["result"]["preflight"]["status"] == "preflight_ready"
    assert preflight_result["result"]["preflight"]["ready_for_live_publish"] is False
    assert preflight_result["result"]["preflight"]["operations"][0]["path"] == "/act_123/campaigns"
    assert [operation["object_type"] for operation in preflight_result["result"]["preflight"]["operations"]] == [
        "campaign",
        "ad_set",
        "creative",
        "ad",
    ]
    assert PlatformMetaPublishAttempt.get_by_id(plan_result["result"]["attempt"]["id"]).status == "preflight_ready"

    inventory_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="sync_meta_inventory",
        arguments={
            "ad_account_id": "act_123",
            "business_id": "business_123",
            "idempotency_key": "sync-inventory-agent-1",
        },
    )
    assert inventory_result["ok"] is True
    assert inventory_result["result"]["snapshot"]["status"] == "missing_credentials"
    assert "META_MARKETING_ACCESS_TOKEN" in inventory_result["result"]["result"]["errors"]

    approval_blocked_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": plan_result["result"]["attempt"]["id"],
            "approved_by": "facundo",
            "approval_note": "No aprobar hasta tener inventario Meta listo.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 50,
            "max_estimated_monthly_budget_usd": 1500,
            "idempotency_key": "approval-blocked-agent-1",
        },
    )
    assert approval_blocked_result["ok"] is True
    assert approval_blocked_result["result"]["approval"]["approved"] is False
    assert "meta_inventory.status=missing_credentials" in approval_blocked_result["result"]["approval"]["blocked_reasons"]

    execution_blocked_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="execute_meta_publish_plan",
        arguments={
            "attempt_id": plan_result["result"]["attempt"]["id"],
            "live_writes_requested": True,
            "idempotency_key": "execution-blocked-agent-1",
        },
    )
    assert execution_blocked_result["ok"] is True
    assert execution_blocked_result["result"]["execution"]["status"] == "blocked"
    assert "approval_status=approved" in execution_blocked_result["result"]["execution"]["blocked_reasons"]

    update_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="create_client_update",
        arguments={
            "client_id": "client-agent-1",
            "campaign_id": campaign_id,
            "summary_text": "Primeras 24 horas: 2 leads.",
            "leads_count": 2,
            "blockers": ["Esperando aprobacion Meta"],
            "idempotency_key": "client-update-agent-1",
        },
    )
    assert update_result["ok"] is True
    assert PlatformClientUpdate.list_recent(client_id="client-agent-1")[0].blockers() == ["Esperando aprobacion Meta"]

    question_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="ask_human_question",
        arguments={
            "workflow": "client_update",
            "target_type": "client_profile",
            "target_id": "client-agent-1",
            "funnel_id": "abogados",
            "context_summary": "El cliente pregunto si pausar por pocos leads.",
            "trying_to_do": "Responder la actualizacion de 24 horas.",
            "question": "Le digo que seguimos optimizando o pausamos?",
            "options": ["seguir optimizando", "pausar"],
            "default_action": "Seguir optimizando si no hay respuesta.",
            "idempotency_key": "question-agent-1",
        },
    )
    assert question_result["ok"] is True
    question_id = question_result["result"]["question"]["id"]

    answer_result = call_tool(
        run_id="agent-run-lifecycle",
        tool_name="answer_human_question",
        arguments={
            "question_id": question_id,
            "answer_text": "Segui optimizando y explica que 24 horas es poco tiempo.",
            "memory_target_type": "client_profile",
            "memory_target_id": "client-agent-1",
            "idempotency_key": "answer-agent-1",
        },
    )
    assert answer_result["ok"] is True
    assert Path(answer_result["result"]["memory_path"]).exists()
    assert PlatformHumanQuestion.list_recent(status="answered")[0].answer_text.startswith("Segui optimizando")

    calls = AgentToolCall.list_by_run("agent-run-lifecycle")
    assert [call.status for call in calls] == ["succeeded"] * len(calls)
    assert {call.tool_name for call in calls} >= {
        "create_platform_meeting",
        "schedule_platform_meeting",
        "extract_client_profile_from_meeting_transcript",
        "stage_ad_campaign",
        "stage_meta_publish_attempt",
        "stage_meta_publish_plan",
        "preflight_meta_publish_plan",
        "approve_meta_publish_plan",
        "execute_meta_publish_plan",
        "sync_meta_inventory",
        "ask_human_question",
        "answer_human_question",
    }
    assert PlatformEvent.list_recent(target_type="meta_publish_attempt")[0].event_type in {
        "meta_publish.plan_staged",
        "meta_publish.preflight_checked",
        "meta_publish.approval_checked",
        "meta_publish.execution_checked",
    }
    failed_tool_result = call_tool(
        run_id="agent-run-observability-failure",
        tool_name="unknown_platform_tool",
        arguments={"target_type": "meta_publish_attempt", "target_id": "obs-failure"},
    )
    assert failed_tool_result["ok"] is False

    overview = TestClient(app).get("/api/platform/overview").json()
    assert overview["counts"]["agent_runs"] >= 1
    assert overview["counts"]["failed_agent_runs"] >= 1
    assert overview["counts"]["agent_tool_calls"] >= len(calls)
    assert overview["counts"]["failed_agent_tool_calls"] >= 1
    lifecycle_run = next(run for run in overview["agent_runs"] if run["id"] == "agent-run-lifecycle")
    assert "final_response_preview" in lifecycle_run
    assert "final_response" not in lifecycle_run
    staged_call = next(call for call in overview["agent_tool_calls"] if call["tool_name"] == "stage_meta_publish_plan")
    assert staged_call["arguments_preview"]
    assert staged_call["result_preview"]
    failed_call = next(call for call in overview["agent_tool_calls"] if call["tool_name"] == "unknown_platform_tool")
    assert "Unknown tool" in failed_call["error_preview"]


def test_codex_agent_tool_checks_domain_with_public_prices(monkeypatch, tmp_path) -> None:
    """Codex should be able to check domain availability without API credentials."""
    configure_contadores_db(monkeypatch, tmp_path)

    class FakeDomainResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "data": {
                    "results": [
                        {
                            "fqdn": "konecta-test-domain.com",
                            "available": True,
                            "status": "available",
                            "pricing": [
                                {
                                    "registrar": "example-registrar",
                                    "registration_price": 12.0,
                                    "renewal_price": 14.0,
                                    "currency": "USD",
                                },
                                {
                                    "registrar": "cheap-registrar",
                                    "registration_price": 9.5,
                                    "renewal_price": 11.0,
                                    "currency": "USD",
                                },
                            ],
                        }
                    ]
                }
            }

    def fake_post(url: str, *, json: dict, timeout: int) -> FakeDomainResponse:
        assert url == "https://api.namecrawl.dev/v1/public/check"
        assert json == {"domain": "konecta-test-domain.com"}
        assert timeout == 12
        return FakeDomainResponse()

    monkeypatch.setattr("backend.ai.codex_agent_tools.httpx.post", fake_post)

    result = call_tool(
        run_id="agent-run-domain",
        tool_name="check_domain_availability",
        arguments={"domain": "https://Konecta-Test-Domain.com/path"},
    )

    assert result["ok"] is True
    assert result["result"]["domain"] == "konecta-test-domain.com"
    assert result["result"]["available"] is True
    assert result["result"]["exists"] is False
    assert result["result"]["best_price"] == {
        "registrar": "cheap-registrar",
        "registration_price": 9.5,
        "renewal_price": 11.0,
        "currency": "USD",
    }
    calls = AgentToolCall.list_by_run("agent-run-domain")
    assert calls[0].tool_name == "check_domain_availability"
    assert calls[0].target_type == "domain"
    assert calls[0].target_id == "konecta-test-domain.com"


def test_codex_agent_tool_domain_check_falls_back_to_rdap(monkeypatch, tmp_path) -> None:
    """RDAP fallback should still tell Codex if a domain exists when price lookup fails."""
    configure_contadores_db(monkeypatch, tmp_path)

    class FakeRdapResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"registrarName": "Example Registrar"}

    def failing_post(*args, **kwargs):
        raise RuntimeError("public lookup down")

    def fake_get(url: str, *, timeout: int, follow_redirects: bool) -> FakeRdapResponse:
        assert url == "https://rdap.org/domain/example.com"
        assert timeout == 12
        assert follow_redirects is True
        return FakeRdapResponse()

    monkeypatch.setattr("backend.ai.codex_agent_tools.httpx.post", failing_post)
    monkeypatch.setattr("backend.ai.codex_agent_tools.httpx.get", fake_get)

    result = call_tool(
        run_id="agent-run-domain-rdap",
        tool_name="check_domain_availability",
        arguments={"domain": "example.com"},
    )

    assert result["ok"] is True
    assert result["result"]["exists"] is True
    assert result["result"]["available"] is False
    assert result["result"]["best_price"] is None
    assert result["result"]["source"] == "rdap"
    assert "public lookup down" in result["result"]["primary_source_error"]


def test_codex_agent_tool_moves_lead_and_sets_tags(monkeypatch, tmp_path) -> None:
    """The toolbelt should let Codex directly move and tag leads."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-move",
        phone="+5491777777797",
        full_name="Cliente Move",
        tags=["form"],
    )

    moved = call_tool(
        run_id="agent-run-move",
        tool_name="move_lead_to_funnel",
        arguments={
            "lead_id": lead.id,
            "funnel_id": "abogados",
            "stage": "needs_human",
            "reason": "El lead pidio asesoramiento legal, no contable.",
            "idempotency_key": "move-lead-agent-1",
        },
    )
    tagged = call_tool(
        run_id="agent-run-move",
        tool_name="set_lead_tags",
        arguments={
            "lead_id": lead.id,
            "tags": ["legal-intent"],
            "mode": "append",
            "idempotency_key": "tag-lead-agent-1",
        },
    )
    updated = ContadoresLead.get_by_id(lead.id)

    assert moved["ok"] is True
    assert tagged["ok"] is True
    assert updated is not None
    assert updated.funnel_id == "abogados"
    assert updated.stage == ContadoresLeadStage.NEEDS_HUMAN
    assert updated.automation_paused is True
    assert "form" in updated.tags
    assert "legal-intent" in updated.tags


def test_codex_agent_tool_marks_lead_converted_canonically(monkeypatch, tmp_path) -> None:
    """Codex agents should convert leads through the canonical conversion tool."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-converted",
        phone="+5491777777798",
        full_name="Cliente Converted",
    )
    converted_at = now_utc()

    result = call_tool(
        run_id="agent-run-mark-converted",
        tool_name="mark_converted",
        arguments={
            "lead_id": lead.id,
            "converted_at": converted_at.isoformat(),
            "reason": "El cliente acepto la propuesta.",
            "idempotency_key": "mark-converted-agent-1",
        },
    )
    updated = ContadoresLead.get_by_id(lead.id)

    assert result["ok"] is True
    assert result["result"]["converted"] is True
    assert result["result"]["stage"] == "awaiting_initial_reply"
    assert result["result"]["pipeline_stage"] == "converted"
    assert result["result"]["converted_at"] == result["result"]["booked_at"]
    assert updated is not None
    assert updated.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
    assert updated.pipeline_stage == "converted"
    assert updated.automation_paused is True
    assert updated.automation_paused_reason == CONTADORES_LEAD_MANUAL_CONVERTED_REASON
    assert updated.booked_at is not None
    assert updated.last_classification_label == "codex_agent_mark_converted"


def test_codex_agent_stage_tools_reject_legacy_booked_stage(monkeypatch, tmp_path) -> None:
    """Agent stage tools should route conversions through mark_converted, not booked."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-booked-rejected",
        phone="+5491777777799",
        full_name="Cliente Booked Rejected",
    )

    moved = call_tool(
        run_id="agent-run-booked-rejected",
        tool_name="move_lead_to_funnel",
        arguments={
            "lead_id": lead.id,
            "funnel_id": "abogados",
            "stage": "booked",
            "reason": "Legacy conversion route.",
            "idempotency_key": "move-booked-reject-1",
        },
    )
    updated = call_tool(
        run_id="agent-run-booked-rejected",
        tool_name="update_lead_state",
        arguments={
            "lead_id": lead.id,
            "stage": "booked",
            "reason": "Legacy conversion route.",
            "idempotency_key": "update-booked-reject-1",
        },
    )
    refreshed = ContadoresLead.get_by_id(lead.id)

    assert moved["ok"] is False
    assert moved["error_type"] == "ValidationError"
    assert "booked" in moved["error"]
    assert updated["ok"] is False
    assert updated["error_type"] == "ValidationError"
    assert "booked" in updated["error"]
    assert refreshed is not None
    assert refreshed.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
    assert refreshed.booked_at is None


def test_codex_agent_runtime_injects_harness_skill(monkeypatch, tmp_path) -> None:
    """Every autonomous run should load the generic harness before task skills."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(codex_agent_runtime, "OPENAI_API_KEY", "sk-test")
    captured: dict[str, list[CodexSkill]] = {}

    async def fake_run_codex_agent_once(**kwargs):
        captured["skills"] = kwargs["skills"]
        return CodexTurnResult(
            final_response="done",
            thread_id="thread-harness",
            turn_id="turn-harness",
            status="completed",
            error=None,
            items_count=0,
            usage=None,
            model="gpt-5.5",
            effort="medium",
            service_tier=None,
            cwd=Path("/Users/fgoiriz/private/repos/contadores"),
        )

    harness_skill = CodexSkill(
        name="contadores-agent-harness",
        path=str(codex_agent_runtime.AGENT_HARNESS_SKILL),
    )
    task_skill = CodexSkill(
        name="workstation-solo-page",
        path=str(Path("/tmp/workstation-solo-page/SKILL.md")),
    )
    monkeypatch.setattr(codex_agent_runtime, "_run_codex_agent_once", fake_run_codex_agent_once)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-harness",
        phone="+5491777777797",
        full_name="Harness Lead",
    )

    result = asyncio.run(
        codex_agent_runtime.run_codex_agent(
            target_type="lead",
            target_id=lead.id,
            objective="test harness skill",
            context_md="context",
            tool_specs=[],
            skills=[harness_skill, task_skill],
            prompt_version="test-harness",
        )
    )

    assert result.codex_result.thread_id == "thread-harness"
    assert [skill.name for skill in captured["skills"]] == [
        "contadores-agent-harness",
        "workstation-solo-page",
    ]


def test_codex_agent_runtime_persists_usage_and_budget_status(monkeypatch, tmp_path) -> None:
    """Completed runs should keep bounded usage metadata for operators."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(codex_agent_runtime, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CODEX_RUN_SOFT_TOKEN_BUDGET", "10")

    async def fake_run_codex_agent_once(**kwargs):
        return CodexTurnResult(
            final_response="done",
            thread_id="thread-usage",
            turn_id="turn-usage",
            status="completed",
            error=None,
            items_count=0,
            usage={"input_tokens": 7, "output_tokens": 5, "total_tokens": 12, "prompt": "raw"},
            model="gpt-5.5",
            effort="medium",
            service_tier=None,
            cwd=Path("/Users/fgoiriz/private/repos/contadores"),
        )

    monkeypatch.setattr(codex_agent_runtime, "_run_codex_agent_once", fake_run_codex_agent_once)
    result = asyncio.run(
        codex_agent_runtime.run_codex_agent(
            target_type="lead",
            target_id="lead-usage",
            objective="track usage",
            context_md="context",
            tool_specs=[],
            prompt_version="test-usage",
        )
    )

    row = AgentRun.get_by_id(result.run_id)
    assert row is not None
    assert row.budget_status == "soft_exceeded"
    usage = json.loads(row.usage_json)
    assert usage["total_tokens"] == 12
    assert usage["model"] == "gpt-5.5"
    assert "prompt" not in usage


def test_agent_tool_call_audit_redacts_arguments_and_results(monkeypatch, tmp_path) -> None:
    """Stored tool audit JSON should avoid raw contact details and secrets."""
    configure_contadores_db(monkeypatch, tmp_path)
    AgentRun.start(run_id="run-redact", agent_kind="codex", target_type="lead", target_id="lead-redact")

    call = AgentToolCall.add(
        run_id="run-redact",
        tool_name="test_tool",
        arguments={"phone": "+5491177778888", "api_token": "secret", "message_text": "hola test@example.com"},
        result={"external_id": "wamid.abcdefghijklmnopqrstuvwxyz", "path": "/Users/fgoiriz/private/file.txt"},
    )

    stored = json.dumps({"arguments": call.arguments_json, "result": call.result_json})
    assert "+5491177778888" not in stored
    assert "test@example.com" not in stored
    assert "secret" not in stored
    assert "[phone:*8888]" in stored
    assert "wamid....wxyz" in stored


def test_agent_artifact_retention_report_and_prune_preserve_active_runs(monkeypatch, tmp_path) -> None:
    """Retention should prune old completed context files but keep running runs."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    old_run = "run-old-context"
    active_run = "run-active-context"
    AgentRun.start(run_id=old_run, agent_kind="codex", target_type="lead", target_id="lead-old")
    AgentRun.finish(old_run, status="completed")
    AgentRun.start(run_id=active_run, agent_kind="codex", target_type="lead", target_id="lead-active")
    for run_id in (old_run, active_run):
        run_dir = codex_agent_runtime.run_context_dir(run_id)
        for name in ("context.md", "memory.md", "tools.json"):
            (run_dir / name).write_text("sensitive", encoding="utf-8")
    old_time = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    for path in (tmp_path / "data" / "agent-runs" / old_run).iterdir():
        os.utime(path, (old_time, old_time))
    os.utime(tmp_path / "data" / "agent-runs" / old_run, (old_time, old_time))

    dry_run = codex_agent_runtime.prune_agent_run_artifacts(retention_days=30, dry_run=True)
    assert [item["run_id"] for item in dry_run["prune_candidates"]] == [old_run]
    assert (tmp_path / "data" / "agent-runs" / old_run / "context.md").exists()

    pruned = codex_agent_runtime.prune_agent_run_artifacts(retention_days=30, dry_run=False)
    assert pruned["removed"]
    assert not (tmp_path / "data" / "agent-runs" / old_run / "context.md").exists()
    assert (tmp_path / "data" / "agent-runs" / active_run / "context.md").exists()


def test_workstation_tool_agent_short_circuits_legacy_decision(monkeypatch, tmp_path) -> None:
    """When enabled and a tool succeeds, Workstation should not ask legacy JSON decisioning."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_ENABLED", True)
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_WORKSTATION_ENABLED", True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-workstation",
        phone="+5491777777793",
        full_name="Cliente Tool Workstation",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
    )
    reply = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Como hago para mandarte mis trabajos?",
    )

    def fake_run_codex_agent(**kwargs):
        AgentToolCall.add(
            run_id="fake-workstation-agent-run",
            tool_name="send_whatsapp_text",
            arguments={"lead_id": lead.id, "text": "Mandemelos por aca."},
            result={"queued": True},
            status="succeeded",
            target_type="lead",
            target_id=lead.id,
        )
        return SimpleNamespace(
            run_id="fake-workstation-agent-run",
            tool_calls=AgentToolCall.list_by_run("fake-workstation-agent-run"),
            final_response="sent text",
            side_effect_count=1,
        )

    monkeypatch.setattr(workstation_endpoints, "run_codex_agent", fake_run_codex_agent)

    decision = asyncio.run(
        workstation_endpoints.decide_workstation_next_action(
            client=workstation,
            lead=lead,
            replies=[reply],
        )
    )

    assert decision.action == "no_action"
    assert "already acted" in decision.reason


def test_contadores_tick_processes_due_agent_followup(monkeypatch, tmp_path) -> None:
    """Lead follow-ups scheduled by Codex should wake up through the normal tick."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_ENABLED", True)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_CONVERSATION_ENABLED", True)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-due-followup",
        phone="+5491777777794",
        full_name="Cliente Due Followup",
    )
    ScheduledAgentTask.create(
        target_type="lead",
        target_id=lead.id,
        due_at=now_utc() - timedelta(minutes=1),
        reason="follow-up test",
        instruction="send a useful next message",
    )

    def fake_run_codex_agent(**kwargs):
        return SimpleNamespace(
            run_id="fake-due-followup-run",
            tool_calls=[],
            final_response="checked followup",
            side_effect_count=0,
        )

    monkeypatch.setattr(contadores_endpoints, "run_codex_agent", fake_run_codex_agent)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")

    assert response.status_code == 200
    assert response.json()["scheduled_agent_tasks_processed"] == 1
    assert ScheduledAgentTask.list_due(now=now_utc()) == []
