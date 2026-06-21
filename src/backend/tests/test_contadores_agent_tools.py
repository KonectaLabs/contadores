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
from backend.redaction import redact_sensitive_text
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



def test_codex_agent_tool_queues_whatsapp_text(monkeypatch, tmp_path) -> None:
    """The Codex tool runner should queue audited outbound messages through existing guards."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-text",
        phone="+5491777777791",
        full_name="Cliente Agent Tool",
    )
    add_recent_inbound(lead.id, text="Como agrego mis trabajos?")

    result = call_tool(
        run_id="agent-run-text",
        tool_name="send_whatsapp_text",
        arguments={
            "lead_id": lead.id,
            "text": "Mandeme los trabajos por aca y yo los agrego a la pagina.",
            "sequence_step": "codex_agent_test",
            "dispatch_after_minutes": 5,
            "idempotency_key": "agent-tool-text-1",
        },
    )

    assert result["ok"] is True
    rows = [message for message in ContadoresMessage.list_by_lead(lead.id) if message.from_me]
    assert len(rows) == 1
    assert rows[0].delivery_status == MessageDeliveryStatus.UNDELIVERED
    assert rows[0].sequence_step == "codex_agent_test"
    assert rows[0].dispatch_after.replace(tzinfo=timezone.utc) > now_utc()
    calls = AgentToolCall.list_by_run("agent-run-text")
    assert len(calls) == 1
    assert calls[0].tool_name == "send_whatsapp_text"
    assert calls[0].status == "succeeded"


def test_codex_agent_tool_schedules_followup(monkeypatch, tmp_path) -> None:
    """Codex follow-ups should be DB-backed scheduled tasks, not OS cron work."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-followup",
        phone="+5491777777792",
        full_name="Cliente Followup",
    )

    result = call_tool(
        run_id="agent-run-followup",
        tool_name="schedule_followup",
        arguments={
            "target_type": "lead",
            "target_id": lead.id,
            "run_after_minutes": 60,
            "reason": "El cliente pidio que le escribamos mas tarde.",
            "instruction": "Revisar si mando el contenido y responder con el siguiente paso.",
            "idempotency_key": "followup-key",
        },
    )
    duplicate = call_tool(
        run_id="agent-run-followup",
        tool_name="schedule_followup",
        arguments={
            "target_type": "lead",
            "target_id": lead.id,
            "run_after_minutes": 60,
            "reason": "duplicado",
            "instruction": "duplicado",
            "idempotency_key": "followup-key",
        },
    )

    assert result["ok"] is True
    assert duplicate["ok"] is True
    assert duplicate["result"]["task_id"] == redact_sensitive_text(result["result"]["task_id"])
    due = ScheduledAgentTask.list_due(now=now_utc() + timedelta(minutes=61))
    assert [task.id for task in due] == [result["result"]["task_id"]]


def test_codex_agent_tool_schedules_heartbeat(monkeypatch, tmp_path) -> None:
    """Codex should be able to wake its future self with DB-backed instructions."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-heartbeat",
        phone="+5491777777795",
        full_name="Cliente Heartbeat",
    )

    result = call_tool(
        run_id="agent-run-heartbeat",
        tool_name="schedule_heartbeat",
        arguments={
            "target_type": "lead",
            "target_id": lead.id,
            "run_after_minutes": 45,
            "reason": "Esperar a que mande una foto.",
            "instruction": "Revisar si el lead mando una foto y responder con el siguiente paso.",
            "idempotency_key": "heartbeat-key",
        },
    )

    assert result["ok"] is True
    due = ScheduledAgentTask.list_due(now=now_utc() + timedelta(minutes=46))
    assert [task.id for task in due] == [result["result"]["task_id"]]
    assert due[0].reason.startswith("heartbeat:")


def test_scheduled_agent_task_idempotency_and_claiming_are_atomic(monkeypatch, tmp_path) -> None:
    """Scheduled tasks should be unique by key and claimed before work starts."""
    configure_contadores_db(monkeypatch, tmp_path)
    database_module.ensure_scheduled_agent_task_idempotency_index()
    now = now_utc()

    keyed = ScheduledAgentTask.create(
        target_type="lead",
        target_id="lead-keyed",
        due_at=now + timedelta(hours=1),
        reason="first",
        instruction="first",
        idempotency_key="task-key-1",
    )
    duplicate = ScheduledAgentTask.create(
        target_type="lead",
        target_id="lead-keyed",
        due_at=now - timedelta(minutes=1),
        reason="duplicate",
        instruction="duplicate",
        idempotency_key="task-key-1",
    )
    first_due = ScheduledAgentTask.create(
        target_type="lead",
        target_id="lead-due-1",
        due_at=now - timedelta(minutes=2),
        reason="due 1",
        instruction="due 1",
    )
    second_due = ScheduledAgentTask.create(
        target_type="lead",
        target_id="lead-due-2",
        due_at=now - timedelta(minutes=1),
        reason="due 2",
        instruction="due 2",
    )

    claimed = ScheduledAgentTask.claim_due(now=now, limit=20, target_type="lead")
    claimed_again = ScheduledAgentTask.claim_due(now=now, limit=20, target_type="lead")

    assert duplicate.id == keyed.id
    assert [task.id for task in claimed] == [first_due.id, second_due.id]
    assert claimed_again == []
    with Session(database_module.engine) as session:
        rows = list(session.exec(select(ScheduledAgentTask).where(ScheduledAgentTask.id.in_([first_due.id, second_due.id]))).all())
        assert {row.status for row in rows} == {"running"}
        assert all(row.claimed_at is not None for row in rows)

    assert ScheduledAgentTask.fail_stale_running(now=now + timedelta(hours=2), stale_after_seconds=60) == 2
    with Session(database_module.engine) as session:
        rows = list(session.exec(select(ScheduledAgentTask).where(ScheduledAgentTask.id.in_([first_due.id, second_due.id]))).all())
        assert {row.status for row in rows} == {"failed"}
        assert {row.last_error for row in rows} == {"stale_running_recovery"}


def test_codex_agent_tool_memory_roundtrip(monkeypatch, tmp_path) -> None:
    """Autonomous runs should have durable target memory outside the prompt."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-memory",
        phone="+5491777777796",
        full_name="Cliente Memory",
    )

    written = call_tool(
        run_id="agent-run-memory",
        tool_name="write_agent_memory",
        arguments={
            "target_type": "lead",
            "target_id": lead.id,
            "title": "Pending photo",
            "note": "El lead prometio mandar una foto casual para mejorarla con AI.",
            "importance": "high",
            "idempotency_key": "agent-memory-1",
        },
    )
    read = call_tool(
        run_id="agent-run-memory",
        tool_name="read_agent_memory",
        arguments={"target_type": "lead", "target_id": lead.id},
    )

    assert written["ok"] is True
    assert read["ok"] is True
    assert "foto casual" in read["result"]["memory"]
    assert Path(read["result"]["path"]).exists()


def test_codex_agent_tool_configures_text_offer_funnel_without_ui(monkeypatch, tmp_path) -> None:
    """Agents should be able to configure a runnable text-offer funnel without the UI."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    result = call_tool(
        run_id="agent-run-platform-config",
        tool_name="configure_text_offer_funnel",
        arguments={
            "funnel_id": "dentistas",
            "label": "Dentistas",
            "enabled": True,
            "sheet_url": "https://docs.google.com/spreadsheets/d/test/export?format=csv&gid=123",
            "sheet_gid": "123",
            "opener_template_name": "dentistas_opener_v1",
            "opener_text": "Hola {nombre}, vi que dejaste tus datos para recibir mas pacientes.",
            "offer_text": "Son 599 USD mensuales. A cambio recibis consultas directo a tu WhatsApp.",
            "alert_emails": ["ops@example.com"],
            "reason": "Nuevo funnel configurado por agente.",
            "idempotency_key": "funnel-dentistas-1",
        },
    )

    assert result["ok"] is True
    funnel = get_funnel("dentistas")
    assert funnel is not None
    assert funnel.enabled is True
    assert funnel.offer_price_usd == 599
    assert funnel.strategies[0].id == "text_offer_599"
    assert funnel.strategies[0].delivery == "text"
    assert funnel.strategies[0].sequence_step == "text_offer"
    assert (tmp_path / "funnels.json").exists()
    calls = AgentToolCall.list_by_run("agent-run-platform-config")
    assert calls[0].target_type == "funnel"
    assert calls[0].target_id == "dentistas"
    events = PlatformEvent.list_recent(target_type="funnel", target_id="dentistas")
    assert events[0].event_type == "platform.funnel_text_offer_configured"

    validation = call_tool(
        run_id="agent-run-platform-config",
        tool_name="validate_platform_config",
        arguments={"include_disabled": True},
    )
    assert validation["ok"] is True
    assert not [
        issue
        for issue in validation["result"]["issues"]
        if issue["target_type"] == "funnel" and issue["target_id"] == "dentistas"
    ]

    snapshot = call_tool(
        run_id="agent-run-platform-config",
        tool_name="read_platform_config",
        arguments={"include_schema": True},
    )
    assert snapshot["ok"] is True
    snapshot_text = json.dumps(snapshot["result"], ensure_ascii=True)
    assert "https://docs.google.com/spreadsheets/d/test" not in snapshot_text
    assert "ops@example.com" not in snapshot_text
    assert str(tmp_path / "funnels.json") not in snapshot_text
    assert snapshot["result"]["field_sensitivity_policy"]["operator_full_config"]
    assert "funnel" in snapshot["result"]["schemas"]
    assert "stage_meta_publish_plan" in snapshot["result"]["agent_native_tools"]
    assert "stage_meta_publish_plan" in snapshot["result"]["schemas"]
    destination_schema = snapshot["result"]["schemas"]["stage_meta_publish_plan"]["$defs"]["MetaLeadDestinationPlan"][
        "properties"
    ]
    assert "whatsapp_referral_source_id" in destination_schema
    assert "client_lead_source_id" in destination_schema
    assert "preflight_meta_publish_plan" in snapshot["result"]["agent_native_tools"]
    assert "preflight_meta_publish_plan" in snapshot["result"]["schemas"]
    assert "approve_meta_publish_plan" in snapshot["result"]["agent_native_tools"]
    assert "approve_meta_publish_plan" in snapshot["result"]["schemas"]
    assert "execute_meta_publish_plan" in snapshot["result"]["agent_native_tools"]
    assert "execute_meta_publish_plan" in snapshot["result"]["schemas"]
    assert "upload_meta_creative_asset" in snapshot["result"]["agent_native_tools"]
    assert "upload_meta_creative_asset" in snapshot["result"]["schemas"]
    assert "import_meta_lead_form_to_delivery" in snapshot["result"]["agent_native_tools"]
    assert "import_meta_lead_form_to_delivery" in snapshot["result"]["schemas"]
    assert "fetch_meta_lead_form_to_delivery" in snapshot["result"]["agent_native_tools"]
    assert "fetch_meta_lead_form_to_delivery" in snapshot["result"]["schemas"]
    assert "schedule_platform_meeting" in snapshot["result"]["agent_native_tools"]
    assert "schedule_platform_meeting" in snapshot["result"]["schemas"]
    assert "sync_meta_inventory" in snapshot["result"]["agent_native_tools"]
    assert "sync_meta_inventory" in snapshot["result"]["schemas"]
    assert snapshot["result"]["meta_marketing"]["live_writes_enabled"] is False
    assert "extract_client_profile_from_meeting_transcript" in snapshot["result"]["agent_native_tools"]
    assert "extract_client_profile_from_meeting_transcript" in snapshot["result"]["schemas"]
    assert "mark_converted" in snapshot["result"]["agent_native_tools"]
    assert "mark_converted" in snapshot["result"]["schemas"]
    assert any(item["id"] == "dentistas" for item in snapshot["result"]["funnels"])


def test_agent_native_tool_call_creates_missing_audit_run(monkeypatch, tmp_path) -> None:
    """Direct tool calls should not fail audit writes when no AgentRun exists yet."""
    configure_contadores_db(monkeypatch, tmp_path)
    result = call_tool(
        run_id="direct-tool-run-1",
        tool_name="ask_human_question",
        arguments={
            "workflow": "meta_publish",
            "target_type": "platform",
            "target_id": "meta_publish_credentials",
            "question": "Where are the Meta credentials?",
            "default_action": "Keep staged mode.",
            "idempotency_key": "direct-tool-question-1",
        },
    )
    assert result["ok"] is True
    audit_run = AgentRun.get_by_id("direct-tool-run-1")
    assert audit_run is not None
    assert audit_run.status == "completed"
    assert audit_run.finished_at is not None
    calls = AgentToolCall.list_by_run("direct-tool-run-1")
    assert len(calls) == 1
    assert calls[0].tool_name == "ask_human_question"


def test_codex_agent_tool_configures_client_lead_delivery_without_ui(monkeypatch, tmp_path) -> None:
    """Agents should be able to configure client lead delivery sources directly."""
    configure_contadores_db(monkeypatch, tmp_path)

    result = call_tool(
        run_id="agent-run-delivery-config",
        tool_name="upsert_client_lead_delivery_source",
        arguments={
            "source_id": "mmb-contable-leads",
            "label": "MMB Contable leads",
            "enabled": True,
            "sheet_url": "https://docs.google.com/spreadsheets/d/client/export?format=csv&gid=0",
            "sheet_gid": "0",
            "recipient_name": "Mariana",
            "recipient_phone": "+5491111111111",
            "context_field_mapping": {"Servicio": "servicio", "Ciudad": "ciudad"},
            "reason": "Delivery configurado por agente.",
            "idempotency_key": "delivery-mmb-1",
        },
    )

    assert result["ok"] is True
    source = ClientLeadSource.get_by_id("mmb-contable-leads")
    assert source is not None
    assert source.enabled is True
    assert source.sheet_gid == "0"
    assert source.context_field_mapping == {"Servicio": "servicio", "Ciudad": "ciudad"}
    calls = AgentToolCall.list_by_run("agent-run-delivery-config")
    assert calls[0].target_type == "client_lead_source"
    assert calls[0].target_id == "mmb-contable-leads"
    events = PlatformEvent.list_recent(target_type="client_lead_source", target_id="mmb-contable-leads")
    assert events[0].event_type == "platform.client_lead_source_upserted"
