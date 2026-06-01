"""Regression tests for the dedicated Contadores flow."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import time
import zipfile

from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

import backend.ai.contadores_conversation_bot as contadores_conversation_bot_module
import backend.calendar_events as calendar_events_module
import backend.database as database_module
import backend.endpoints.contadores as contadores_endpoints
import backend.endpoints.workstation as workstation_endpoints
import backend.meta_ads_publish as meta_ads_publish_module
import backend.meta_lead_forms as meta_lead_forms_module
import backend.platform_profile_extraction as profile_extraction_module
from backend.audio_transcription import AudioTranscriptionError
from backend.codex_utils import CodexSkill, CodexTurnResult
from backend.meta_ads_inventory import sync_meta_inventory
from backend.ai.client_profile_extractor import (
    ClientProfileAdAngle,
    ClientProfileExtractionResult,
    ClientProfileSegment,
    ClientProfileSourceSnippet,
)
from backend.ai.contadores_conversation_bot import ContadoresConversationBotResult, REJECTION_SURVEY_REPLY
from backend.ai import codex_agent_runtime
from backend.contadores_strategies import get_contadores_strategy
from backend.database import (
    AgentRun,
    AgentToolCall,
    ClientLeadSource,
    CONTADORES_LEAD_MANUAL_CONVERTED_REASON,
    ContadoresConfig,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresRuntimeAlert,
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
)
from backend.funnel_config import get_funnel
from backend.ai.codex_agent_tools import call_tool
from backend.main import app


def now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp for test fixtures."""
    return datetime.now(timezone.utc)


def configure_contadores_db(monkeypatch, tmp_path) -> None:
    """Point database and Contadores router state at a temporary SQLite file."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_ENABLED", False)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_CONVERSATION_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_WORKSTATION_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_BACKEND_ENABLED", True)
    monkeypatch.setattr(contadores_conversation_bot_module, "CODEX_BACKEND_ENABLED", True)
    monkeypatch.setattr(codex_agent_runtime, "CODEX_BACKEND_ENABLED", True)
    monkeypatch.setattr(database_module, "DEFAULT_CONTADORES_LEAD_CODEX_ENABLED", True)
    db_path = tmp_path / "contadores.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(contadores_endpoints, "engine", engine)
    SQLModel.metadata.create_all(engine)


def fake_profile_extraction(**kwargs) -> ClientProfileExtractionResult:
    """Return deterministic transcript extraction for lifecycle tests."""
    return ClientProfileExtractionResult(
        business_summary="Clinica dental enfocada en implantes premium.",
        offer_summary="Evaluacion inicial para pacientes que necesitan implantes.",
        market_summary="Pacientes adultos que quieren recuperar sonrisa sin vueltas.",
        segments=[
            ClientProfileSegment(
                name="pacientes implantes premium",
                description="Adultos con perdida dental y capacidad de pago.",
                geo="Montevideo",
                meta_targeting_notes="Usar geo local y copies sobre recuperar sonrisa.",
            )
        ],
        ad_angles=[
            ClientProfileAdAngle(
                hook="Recupera tu sonrisa sin esperar meses",
                problem="Perdida dental",
                desired_outcome="Volver a sonreir con confianza",
                without_objection="sin tratamientos eternos",
                evidence="quiere pacientes premium",
            )
        ],
        meta_planning={
            "objective": "OUTCOME_LEADS",
            "lead_destination": "whatsapp",
            "suggested_daily_budget_usd": 20,
            "required_before_meta_publish": ["page_id", "whatsapp_phone_number_id"],
        },
        delivery_notes={"lead_sheet": "Crear Google Sheet de delivery para el cliente."},
        unresolved_questions=["Confirmar radio geografico exacto antes de publicar en Meta."],
        source_snippets=[
            ClientProfileSourceSnippet(
                topic="oferta",
                quote="El cliente vende implantes y quiere pacientes premium.",
                use_for="Meta copy y segmentacion",
            )
        ],
        confidence="high",
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


def force_loom_strategy(monkeypatch, strategy_id: str = "loom_mp4") -> None:
    """Force one Loom strategy in automation tests."""
    strategy = get_contadores_strategy("loom", strategy_id)
    assert strategy is not None
    monkeypatch.setattr(contadores_endpoints, "choose_contadores_strategy", lambda **kwargs: strategy)


def add_recent_inbound(lead_id: str, *, text: str = "Si, me interesa") -> ContadoresMessage:
    """Add one recent inbound WhatsApp message to keep the 24-hour window open."""
    return ContadoresMessage.add(
        lead_id=lead_id,
        from_me=False,
        text=text,
        created_at=now_utc() - timedelta(minutes=5),
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


def test_codex_agent_tool_rejects_disabled_lead(monkeypatch, tmp_path) -> None:
    """Audited Codex tools must stop side effects after the lead switch is turned off."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agent-tool-disabled",
        phone="+5491777777790",
        full_name="Cliente Codex Disabled",
    )
    ContadoresLead.set_codex_enabled(lead.id, enabled=False)

    result = call_tool(
        run_id="agent-run-disabled",
        tool_name="send_whatsapp_text",
        arguments={
            "lead_id": lead.id,
            "text": "Esto no deberia salir.",
        },
    )

    assert result["ok"] is False
    assert result["error"] == "Codex is disabled for this lead."
    assert ContadoresMessage.list_by_lead(lead.id) == []


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
    assert result["result"]["task_id"] == duplicate["result"]["task_id"]
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


def test_meta_publish_plan_requires_instant_form_delivery_source(monkeypatch, tmp_path) -> None:
    """Instant-form plans should prove how leads enter Client Lead Delivery."""
    configure_contadores_db(monkeypatch, tmp_path)

    blocked_result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-form-1",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados instant form",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "instant_form",
                "page_id": "page_routing_1",
                "lead_form_id": "lead_form_routing_1",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-1",
                                "image_hash": "hash_routing_1",
                                "primary_text": "Si te despidieron, completa tus datos.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
        },
    )
    assert blocked_result["ok"] is True
    assert "destination.client_lead_source_id" in blocked_result["result"]["required_before_live_publish"]

    ClientLeadSource.upsert(
        source_id="abogados-meta-form-leads",
        label="Abogados Meta form leads",
        enabled=True,
        sheet_url="https://docs.google.com/spreadsheets/d/client/export?format=csv&gid=0",
        sheet_gid="0",
        recipient_name="Alan",
        recipient_phone="+5491111111111",
    )

    ready_result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-form-2",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados instant form ready",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "instant_form",
                "page_id": "page_routing_1",
                "lead_form_id": "lead_form_routing_1",
                "client_lead_source_id": "abogados-meta-form-leads",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-2",
                                "image_hash": "hash_routing_2",
                                "primary_text": "Si te despidieron, completa tus datos.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
        },
    )
    assert ready_result["ok"] is True
    assert ready_result["result"]["required_before_live_publish"] == []
    payload = ready_result["result"]["attempt"]["request_payload"]
    assert payload["lead_routing"]["route_type"] == "client_lead_delivery_source"
    assert payload["lead_routing"]["client_lead_source_id"] == "abogados-meta-form-leads"


def test_meta_publish_plan_blocks_wrong_whatsapp_source_mapping(monkeypatch, tmp_path) -> None:
    """A provided CTWA source id must map to the same funnel before live publish."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(
        tmp_path,
        build_abogados_test_funnel(referral_ids=["ctwa-good-source"]),
        build_contadores_test_funnel(),
    )

    result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-wa-1",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_routing_1",
                "whatsapp_phone_number_id": "wa_phone_routing_1",
                "whatsapp_referral_source_id": "ctwa-wrong-source",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-wa-1",
                                "image_hash": "hash_routing_wa_1",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
        },
    )

    assert result["ok"] is True
    assert "destination.whatsapp_referral_source_id.funnel_mapping" in result["result"][
        "required_before_live_publish"
    ]
    payload = result["result"]["attempt"]["request_payload"]
    assert payload["lead_routing"]["whatsapp_referral_source_id"] == "ctwa-wrong-source"
    assert payload["lead_routing"]["mapped_funnel_ids"] == []


def test_meta_inventory_sync_persists_read_only_inventory(monkeypatch, tmp_path) -> None:
    """Meta inventory sync should persist sanitized read-only provider state."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        del params
        if path == "me/adaccounts":
            return {"data": [{"id": "act_123", "name": "Agency account", "currency": "USD"}]}
        if path == "act_123":
            return {"id": "act_123", "name": "Agency account", "account_status": 1}
        if path == "act_123/campaigns":
            return {"data": [{"id": "campaign_1", "name": "Existing campaign", "status": "PAUSED"}]}
        if path == "act_123/adspixels":
            return {"data": [{"id": "pixel_1", "name": "Main pixel"}]}
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "Client Page", "access_token": "secret-page-token"}]}
        if path == "page_1/leadgen_forms":
            return {"data": [{"id": "form_1", "name": "Lead form", "status": "ACTIVE"}]}
        if path == "business_1/owned_whatsapp_business_accounts":
            return {"data": [{"id": "waba_1", "name": "WABA"}]}
        if path == "waba_1/phone_numbers":
            return {"data": [{"id": "wa_phone_1", "display_phone_number": "+54 9 11 1234-5678"}]}
        raise AssertionError(path)

    snapshot, result = sync_meta_inventory(
        ad_account_id="act_123",
        business_id="business_1",
        source="test",
        actor="tester",
        graph_get=fake_graph_get,
    )

    assert result.status == "ready"
    assert snapshot.status == "ready"
    assert snapshot.inventory()["ad_accounts"][0]["id"] == "act_123"
    assert snapshot.inventory()["pages"][0].get("access_token") is None
    assert snapshot.inventory()["lead_forms"][0]["page_id"] == "page_1"
    assert snapshot.inventory()["whatsapp_phone_numbers"][0]["id"] == "wa_phone_1"
    assert PlatformEvent.list_recent(target_type="meta_inventory", target_id=snapshot.id)[0].event_type == "meta_inventory.synced"


def test_meta_inventory_sync_redacts_access_token_from_errors(monkeypatch, tmp_path) -> None:
    """Meta inventory errors must not persist provider URLs with raw tokens."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        del params
        if path == "me/adaccounts":
            return {"data": [{"id": "act_123", "name": "Agency account"}]}
        if path == "act_123":
            return {"id": "act_123", "name": "Agency account"}
        if path == "act_123/campaigns":
            return {"data": []}
        if path == "act_123/adspixels":
            return {"data": []}
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "Client Page"}]}
        if path == "page_1/leadgen_forms":
            raise RuntimeError("403 for https://graph.facebook.com/v25.0/page_1/leadgen_forms?access_token=secret-token&limit=50")
        if path == "business_1/owned_whatsapp_business_accounts":
            return {"data": []}
        raise AssertionError(path)

    snapshot, result = sync_meta_inventory(
        ad_account_id="act_123",
        business_id="business_1",
        source="test",
        actor="tester",
        graph_get=fake_graph_get,
    )

    error_text = json.dumps(result.errors + snapshot.errors())
    assert result.status == "partial"
    assert "secret-token" not in error_text
    assert "access_token=[redacted]" in error_text


def test_meta_lead_form_write_tools_are_gated_and_post_expected_payloads(monkeypatch, tmp_path) -> None:
    """Lead form creation and webhook subscription should share the Meta live-write gate."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    blocked = call_tool(
        run_id="agent-run-meta-lead-form-blocked",
        tool_name="create_meta_lead_form",
        arguments={
            "page_id": "page_1",
            "name": "Consulta laboral",
            "privacy_policy_url": "https://example.com/privacy",
            "reason": "Test blocked gate.",
        },
    )
    assert blocked["ok"] is True
    assert blocked["result"]["status"] == "blocked"
    assert "live_writes_requested" in blocked["result"]["blocked"]
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in blocked["result"]["blocked"]

    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    calls = []

    def fake_graph_post(path: str, params: dict) -> dict:
        calls.append((path, params))
        if path == "page_1/leadgen_forms":
            assert params["name"] == "Consulta laboral"
            assert params["privacy_policy"]["url"] == "https://example.com/privacy"
            assert params["questions"] == [{"type": "FULL_NAME"}]
            return {"id": "form_created_1"}
        if path == "page_1/subscribed_apps":
            assert params["subscribed_fields"] == "leadgen"
            return {"success": True}
        raise AssertionError(path)

    created = meta_lead_forms_module.create_meta_lead_form(
        meta_lead_forms_module.CreateMetaLeadFormArgs(
            page_id="page_1",
            name="Consulta laboral",
            questions=[{"type": "FULL_NAME"}],
            privacy_policy_url="https://example.com/privacy",
            live_writes_requested=True,
            reason="Create test form.",
        ),
        graph_post=fake_graph_post,
        source="test",
        actor="tester",
    )
    subscribed = meta_lead_forms_module.subscribe_meta_lead_webhook(
        meta_lead_forms_module.SubscribeMetaLeadWebhookArgs(
            page_id="page_1",
            live_writes_requested=True,
            reason="Subscribe test page.",
        ),
        graph_post=fake_graph_post,
        source="test",
        actor="tester",
    )

    assert created.status == "created"
    assert created.lead_form_id == "form_created_1"
    assert subscribed.status == "subscribed"
    assert [path for path, _params in calls] == ["page_1/leadgen_forms", "page_1/subscribed_apps"]


def test_meta_publish_attempt_idempotency_key_has_db_guard(monkeypatch, tmp_path) -> None:
    """Meta publish idempotency should be enforced below the application lookup."""
    configure_contadores_db(monkeypatch, tmp_path)
    database_module.ensure_platform_meta_publish_attempt_idempotency_index()

    first = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-unique-1",
        request_payload={"objective": "LEADS"},
        idempotency_key="publish-unique-1",
    )
    retry = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-unique-1",
        request_payload={"objective": "LEADS"},
        idempotency_key="publish-unique-1",
    )
    assert retry.id == first.id

    duplicate = PlatformMetaPublishAttempt(
        campaign_id="campaign-unique-1",
        request_json=json.dumps({"objective": "LEADS"}),
        idempotency_key="publish-unique-1",
    )
    raised = False
    with Session(database_module.engine) as session:
        session.add(duplicate)
        try:
            session.commit()
        except IntegrityError:
            raised = True
            session.rollback()
    assert raised is True


def test_meta_creative_asset_upload_patches_publish_plan(monkeypatch, tmp_path) -> None:
    """Generated files should become Meta-ready image hashes before live publish."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    creative_file = data_dir / "meta-assets" / "creative.png"
    creative_file.parent.mkdir(parents=True, exist_ok=True)
    creative_file.write_bytes(b"png-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ads_publish_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")

    asset_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="stage_creative_asset",
        arguments={
            "campaign_id": "campaign-upload-1",
            "client_id": "client-upload-1",
            "asset_type": "image",
            "prompt": "Problem-first ad creative.",
            "file_path": "data/meta-assets/creative.png",
        },
    )
    assert asset_result["ok"] is True
    asset_id = asset_result["result"]["asset"]["id"]

    plan_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-upload-1",
            "client_id": "client-upload-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_upload_1",
            "campaign_name": "Abogados upload - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_upload_1",
                "whatsapp_phone_number_id": "wa_phone_upload_1",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": asset_id,
                                "asset_file_path": "data/meta-assets/creative.png",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-upload-agent-1",
        },
    )
    assert plan_result["ok"] is True
    attempt_id = plan_result["result"]["attempt"]["id"]

    live_preflight_before_upload = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert live_preflight_before_upload["ok"] is True
    assert "ad_sets[1].ads[1].creative.meta_asset" in live_preflight_before_upload["result"]["preflight"][
        "blocked_reasons"
    ]

    upload_calls: list[tuple[str, Path, str, dict]] = []

    def fake_graph_uploader(*, api_version: str, access_token: str, timeout: float = 120):
        assert api_version == "v25.0"
        assert access_token == "test-token"
        assert timeout == 120

        def graph_upload(path: str, file_path: Path, file_field: str, params: dict) -> dict:
            upload_calls.append((path, file_path, file_field, params))
            assert file_path.read_bytes() == b"png-bytes"
            return {"images": {file_path.name: {"hash": "hash_uploaded_1", "access_token": "do-not-store"}}}

        return graph_upload

    monkeypatch.setattr(meta_ads_publish_module, "_default_graph_uploader", fake_graph_uploader)
    upload_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="upload_meta_creative_asset",
        arguments={
            "asset_id": asset_id,
            "ad_account_id": "act_upload_1",
            "live_writes_requested": True,
        },
    )
    assert upload_result["ok"] is True
    assert upload_result["result"]["upload"]["status"] == "uploaded"
    assert upload_result["result"]["upload"]["image_hash"] == "hash_uploaded_1"
    assert upload_result["result"]["upload"]["linked_publish_attempts"] == [attempt_id]
    assert upload_calls[0][0] == "/act_upload_1/adimages"
    assert upload_calls[0][2] == "filename"

    uploaded_asset = PlatformCreativeAsset.get_by_id(asset_id)
    assert uploaded_asset.status == "uploaded_to_meta"
    assert uploaded_asset.image_hash == "hash_uploaded_1"
    assert "access_token" not in json.dumps(uploaded_asset.meta_upload_response())

    patched_plan = PlatformMetaPublishAttempt.get_by_id(attempt_id).request_payload()
    patched_creative = patched_plan["ad_sets"][0]["ads"][0]["creative"]
    assert patched_creative["image_hash"] == "hash_uploaded_1"

    live_preflight_after_upload = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert live_preflight_after_upload["ok"] is True
    assert "ad_sets[1].ads[1].creative.meta_asset" not in live_preflight_after_upload["result"]["preflight"][
        "blocked_reasons"
    ]


def test_meta_creative_asset_upload_blocks_without_credentials(monkeypatch, tmp_path) -> None:
    """Agent-native uploads should report exact blockers instead of trying live writes."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    asset = PlatformCreativeAsset.add(
        campaign_id="campaign-upload-blocked-1",
        client_id="client-upload-blocked-1",
        asset_type="image",
        file_path="data/meta-assets/missing.png",
    )
    result = call_tool(
        run_id="agent-run-meta-creative-upload-blocked",
        tool_name="upload_meta_creative_asset",
        arguments={
            "asset_id": asset.id,
            "ad_account_id": "act_upload_blocked_1",
            "live_writes_requested": True,
        },
    )
    assert result["ok"] is True
    blockers = result["result"]["upload"]["blocked_reasons"]
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in blockers
    assert "META_MARKETING_ACCESS_TOKEN" in blockers
    assert "META_MARKETING_API_VERSION" in blockers
    assert "asset.file_path.exists" in blockers
    assert PlatformCreativeAsset.get_by_id(asset.id).status == "upload_blocked"


def test_meta_publish_approval_gate_requires_inventory_and_budget(monkeypatch, tmp_path) -> None:
    """Meta approval should be explicit, budget-capped, inventory-backed, and still no live write."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    plan_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert plan_result["ok"] is True
    attempt_id = plan_result["result"]["attempt"]["id"]

    idempotency_conflict = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - changed",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert idempotency_conflict["ok"] is False
    assert "idempotency conflict" in idempotency_conflict["error"]

    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    unapproved_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id},
    )
    assert unapproved_preflight["ok"] is True
    assert unapproved_preflight["result"]["preflight"]["ready_for_live_publish"] is False

    fake_approved_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_attempt",
        arguments={
            "campaign_id": "campaign-fake-approval-1",
            "approval_status": "approved",
            "request_payload": {
                "schema_version": "konecta.meta_publish_plan.v1",
                "provider": "meta_marketing_api",
                "publish_mode": "approved_live_candidate",
                "live_writes_allowed": True,
                "ad_account_id": "act_999",
                "budget_currency": "USD",
                "campaign": {
                    "name": "Fake approved plan",
                    "objective": "OUTCOME_LEADS",
                    "buying_type": "AUCTION",
                    "special_ad_categories": [],
                    "create_status": "PAUSED",
                },
                "destination": {
                    "destination_type": "whatsapp",
                    "page_id": "page_999",
                    "whatsapp_phone_number_id": "wa_phone_999",
                },
                "ad_sets": [
                    {
                        "name": "Fake ad set",
                        "budget_daily_usd": 10,
                        "status": "PAUSED",
                        "targeting": {"geo_locations": {"countries": ["AR"]}},
                        "ads": [
                            {
                                "name": "Fake ad",
                                "status": "PAUSED",
                                "creative": {
                                    "creative_asset_id": "creative-approval-1",
                                    "image_hash": "hash_approval_fake_1",
                                    "primary_text": "Manda tu caso por WhatsApp.",
                                    "headline": "Necesitas ayuda?",
                                },
                            }
                        ],
                    }
                ],
                "required_before_live_publish": [],
            },
            "idempotency_key": "publish-plan-fake-approved-agent-1",
        },
    )
    assert fake_approved_result["ok"] is True
    fake_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": fake_approved_result["result"]["attempt"]["id"],
            "live_writes_requested": True,
        },
    )
    assert fake_preflight["ok"] is True
    assert fake_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "meta_publish.approval_gate" in fake_preflight["result"]["preflight"]["blocked_reasons"]
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    blocked_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Test approval should stay blocked until inventory and cap pass.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 50,
            "max_estimated_monthly_budget_usd": 1500,
        },
    )
    assert blocked_result["ok"] is True
    assert blocked_result["result"]["approval"]["approved"] is False
    assert "budget.daily_cap" in blocked_result["result"]["approval"]["blocked_reasons"]
    assert "meta_inventory.ready" in blocked_result["result"]["approval"]["blocked_reasons"]

    inventory_bypass_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Inventory cannot be bypassed for live writes.",
            "approve_live_writes": True,
            "require_inventory_ready": False,
            "max_daily_budget_usd": 100,
            "max_estimated_monthly_budget_usd": 3000,
        },
    )
    assert inventory_bypass_result["ok"] is True
    assert inventory_bypass_result["result"]["approval"]["approved"] is False
    assert "require_inventory_ready=true" in inventory_bypass_result["result"]["approval"]["blocked_reasons"]

    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_999",
        business_id="business_999",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_999", "currency": "USD"}],
            "selected_ad_account": {"id": "act_999", "currency": "USD"},
            "pages": [{"id": "page_999", "name": "Abogados"}],
            "lead_forms": [],
            "pixels": [],
            "whatsapp_business_accounts": [{"id": "waba_999"}],
            "whatsapp_phone_numbers": [{"id": "wa_phone_999", "whatsapp_business_account_id": "waba_999"}],
            "campaigns": [],
        },
    )
    approved_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Budget and inventory reviewed.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 100,
            "max_estimated_monthly_budget_usd": 3000,
        },
    )
    assert approved_result["ok"] is True
    assert approved_result["result"]["approval"]["approved"] is True
    approved_attempt = PlatformMetaPublishAttempt.get_by_id(attempt_id)
    assert approved_attempt.approval_status == "approved"
    assert approved_attempt.request_payload()["live_writes_allowed"] is True
    assert approved_attempt.request_payload()["approval_policy"]["approved_by"] == "facundo"

    blocked_execute = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={"attempt_id": attempt_id},
    )
    assert blocked_execute["ok"] is True
    assert blocked_execute["result"]["execution"]["status"] == "blocked"
    assert "live_writes_requested=true" in blocked_execute["result"]["execution"]["blocked_reasons"]

    posted: list[tuple[str, dict]] = []

    def fake_graph_poster(*, api_version: str, access_token: str, timeout: float = 30):
        assert api_version == "v25.0"
        assert access_token == "test-token"

        def graph_post(path: str, params: dict) -> dict:
            posted.append((path, params))
            return {"id": f"meta_{len(posted)}", "access_token": "do-not-store"}

        return graph_post

    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(meta_ads_publish_module, "_default_graph_poster", fake_graph_poster)
    execute_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert execute_result["ok"] is True
    assert execute_result["result"]["execution"]["status"] == "submitted"
    assert execute_result["result"]["execution"]["live_write_executed"] is True
    assert [path for path, _ in posted] == [
        "/act_999/campaigns",
        "/act_999/adsets",
        "/act_999/adcreatives",
        "/act_999/ads",
    ]
    assert posted[1][1]["campaign_id"] == "meta_1"
    assert posted[3][1]["adset_id"] == "meta_2"
    assert posted[3][1]["creative"]["creative_id"] == "meta_3"
    execute_payload = PlatformMetaPublishAttempt.get_by_id(attempt_id).response_payload()
    assert execute_payload["schema_version"] == "konecta.meta_publish_execution.v1"
    assert execute_payload["operation_results"][0]["provider_id"] == "meta_1"
    assert "access_token" not in execute_payload["operation_results"][0]["response"]
    updated_plan = PlatformMetaPublishAttempt.get_by_id(attempt_id).request_payload()
    assert updated_plan["lead_routing"]["mapped_source_ids"] == ["meta_4"]
    assert "meta_4" in get_funnel("abogados").whatsapp_referral_source_ids
    routing_events = [
        event
        for event in PlatformEvent.list_recent(target_type="funnel", target_id="abogados")
        if event.event_type == "meta_publish.lead_routing_mapped"
    ]
    assert routing_events[0].payload_dict()["mapped_source_ids"] == ["meta_4"]

    retry_execute = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert retry_execute["ok"] is True
    assert retry_execute["result"]["execution"]["status"] == "already_submitted"
    assert retry_execute["result"]["execution"]["live_write_executed"] is False
    assert len(posted) == 4

    failure_plan_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-failure-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_998",
            "campaign_name": "Abogados failure - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_998",
                "whatsapp_phone_number_id": "wa_phone_998",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-approval-failure-1",
                                "image_hash": "hash_approval_failure_1",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-failure-agent-1",
        },
    )
    assert failure_plan_result["ok"] is True
    failure_attempt_id = failure_plan_result["result"]["attempt"]["id"]
    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_998",
        business_id="business_998",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_998", "currency": "USD"}],
            "selected_ad_account": {"id": "act_998", "currency": "USD"},
            "pages": [{"id": "page_998", "name": "Abogados"}],
            "lead_forms": [],
            "pixels": [],
            "whatsapp_business_accounts": [{"id": "waba_998"}],
            "whatsapp_phone_numbers": [{"id": "wa_phone_998", "whatsapp_business_account_id": "waba_998"}],
            "campaigns": [],
        },
    )
    failure_approval = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": failure_attempt_id,
            "approved_by": "facundo",
            "approval_note": "Failure path reviewed.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 50,
            "max_estimated_monthly_budget_usd": 1500,
        },
    )
    assert failure_approval["ok"] is True
    failure_posts: list[str] = []

    def failing_graph_post(path: str, params: dict) -> dict:
        del params
        failure_posts.append(path)
        if path.endswith("/adsets"):
            raise RuntimeError("Meta rejected ad set")
        return {"id": f"failure_meta_{len(failure_posts)}"}

    failed_attempt, failed_execution = meta_ads_publish_module.execute_meta_publish_attempt(
        attempt_id=failure_attempt_id,
        live_writes_requested=True,
        graph_post=failing_graph_post,
    )
    assert failed_execution.status == "partial_failed"
    assert failed_execution.operation_results[0].status == "executed"
    assert failed_execution.operation_results[1].status == "failed"
    assert "Meta rejected ad set" in failed_attempt.error
    assert PlatformMetaPublishAttempt.get_by_id(failure_attempt_id).request_payload()["live_execution_state"][
        "operation_results"
    ][0]["provider_id"] == "failure_meta_1"

    idempotent_retry = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert idempotent_retry["ok"] is True
    assert idempotent_retry["result"]["attempt"]["id"] == attempt_id

    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    missing_api_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert missing_api_preflight["ok"] is True
    assert missing_api_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "META_MARKETING_API_VERSION" in missing_api_preflight["result"]["preflight"]["blocked_reasons"]
    assert "meta_publish.approval_gate" not in missing_api_preflight["result"]["preflight"]["blocked_reasons"]
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    live_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "live_writes_requested": True},
    )
    assert live_preflight["ok"] is True
    assert live_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in live_preflight["result"]["preflight"]["blocked_reasons"]
    assert "META_MARKETING_ACCESS_TOKEN" in live_preflight["result"]["preflight"]["blocked_reasons"]


def test_platform_meeting_calendar_gate_builds_and_creates_event(monkeypatch, tmp_path) -> None:
    """Meeting scheduling should build the Calendar payload and gate live writes on credentials."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_CALENDAR_DELEGATED_USER", raising=False)
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
        },
    )
    assert blocked_live["ok"] is True
    assert blocked_live["result"]["calendar"]["status"] == "calendar_blocked"
    assert "GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE" in blocked_live["result"]["calendar"]["blocked_reasons"]
    assert "GOOGLE_CALENDAR_DELEGATED_USER" not in blocked_live["result"]["calendar"]["blocked_reasons"]

    insert_calls: list[dict] = []

    def fake_insert(calendar_id: str, event_payload: dict, send_updates: str, conference_data_version: int) -> dict:
        assert calendar_id == "team-calendar@example.com"
        assert send_updates == "all"
        assert conference_data_version == 1
        assert "attendees" not in event_payload
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
        },
    )
    assert live_result["ok"] is True
    assert live_result["result"]["calendar"]["status"] == "scheduled"
    assert live_result["result"]["calendar"]["calendar_event_id"] == "calendar-event-1"
    assert "without Google attendees" in " ".join(live_result["result"]["calendar"]["warnings"])
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
        arguments={"attempt_id": plan_result["result"]["attempt"]["id"]},
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
        arguments={"ad_account_id": "act_123", "business_id": "business_123"},
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
        },
    )
    tagged = call_tool(
        run_id="agent-run-move",
        tool_name="set_lead_tags",
        arguments={
            "lead_id": lead.id,
            "tags": ["legal-intent"],
            "mode": "append",
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
        },
    )
    updated = call_tool(
        run_id="agent-run-booked-rejected",
        tool_name="update_lead_state",
        arguments={
            "lead_id": lead.id,
            "stage": "booked",
            "reason": "Legacy conversion route.",
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


def test_disable_codex_action_clears_pending_codex_tasks(monkeypatch, tmp_path) -> None:
    """The central lead switch should disable Codex and retire queued wake-ups."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-disable-codex-action",
        phone="+5491777777798",
        full_name="Cliente Switch",
    )
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )
    ScheduledAgentTask.create(
        target_type="lead",
        target_id=lead.id,
        due_at=now_utc() - timedelta(minutes=1),
        reason="lead codex",
        instruction="check lead",
    )
    ScheduledAgentTask.create(
        target_type="workstation_client",
        target_id=workstation.id,
        due_at=now_utc() - timedelta(minutes=1),
        reason="workstation codex",
        instruction="check workstation",
    )

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/actions/disable-codex")

    assert response.status_code == 200
    assert response.json()["lead"]["codex_enabled"] is False
    assert ContadoresLead.get_by_id(lead.id).codex_enabled is False
    assert ScheduledAgentTask.list_due(now=now_utc()) == []


def build_abogados_test_funnel(
    *,
    referral_ids: list[str] | None = None,
    initial_reply_quiet_seconds: int = 1,
) -> dict[str, object]:
    """Build a compact Abogados funnel fixture."""
    return {
        "id": "abogados",
        "label": "Abogados",
        "kind": "campaign",
        "enabled": True,
        "sheet_url": None,
        "sheet_gid": None,
        "sheet_source_filter": None,
        "sheet_poll_seconds": 30,
        "template_language": "es",
        "opener_text": (
            "Hola {nombre}, llenaste el formulario para abogados de {pais} sobre como conseguir "
            "casos redituables a tu whatsapp. es correcto?"
        ),
        "opener_template_name": "abogados_intro_nombre_pais_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "manual_ping_text": "Hola, queria saber si queres que retomemos la conversacion",
        "manual_ping_template_name": None,
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/facundogoiriz/crecimiento",
        "alert_emails": [],
        "whatsapp_referral_source_ids": referral_ids or [],
        "initial_reply_quiet_seconds": initial_reply_quiet_seconds,
        "post_loom_min_seconds": 600,
        "post_loom_quiet_seconds": 30,
        "strategies": [
            {
                "step": "loom",
                "id": "loom_mp4",
                "label": "WhatsApp MP4",
                "weight": 100,
                "delivery": "video",
                "sequence_step": "loom_video",
                "message_text": "Video enviado por WhatsApp.",
                "media_type": "video",
                "media_path": "data/abogados/videos/loom_60_seconds_captions.mp4",
                "media_caption": None,
            }
        ],
    }


def build_contadores_test_funnel(**overrides: object) -> dict[str, object]:
    """Build a compact Contadores funnel fixture."""
    funnel = build_abogados_test_funnel(initial_reply_quiet_seconds=30)
    funnel.update(
        {
            "id": "contadores",
            "label": "Contadores",
            "sheet_url": "https://docs.google.com/spreadsheets/d/example",
            "sheet_gid": "0",
            "opener_text": (
                "Hola {nombre}, llenaste el formulario para contadores de {pais} sobre como conseguir "
                "clientes a tu whatsapp. es correcto?"
            ),
            "opener_template_name": "contadores_intro_nombre_pais_es_v1",
            "opener_followup_text": "Queria compartirte informacion sobre como podes obtener clientes.",
            "opener_followup_template_name": "contadores_followup_es_v1",
            "manual_ping_template_name": "contadores_manual_ping_es_v1",
            "loom_intro_text": "Perfecto. Te cuento rapido como funciona:",
            "calendly_base_url": "https://calendly.com/test/contadores",
            "whatsapp_referral_source_ids": [],
        }
    )
    funnel["strategies"][0]["media_path"] = "data/contadores/videos/loom_60_seconds_captions.mp4"
    funnel.update(overrides)
    return funnel


def write_funnels_config(tmp_path, *funnels: dict[str, object]) -> None:
    """Write the test funnel override config."""
    (tmp_path / "funnels.json").write_text(
        json.dumps({"version": 1, "funnels": list(funnels)}),
        encoding="utf-8",
    )


def test_runtime_endpoint_reports_sheet_readiness(monkeypatch, tmp_path) -> None:
    """Runtime status should expose non-secret sheet readiness."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_contadores_test_funnel())

    with TestClient(app) as client:
        response = client.get("/api/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sheet_configured"] is True
    assert payload["sheet_gid"] == "0"
    assert payload["ready"] is True
    assert payload["ready_campaign_funnels"] == ["contadores"]
    assert payload["funnel_config_path"] == str(tmp_path / "funnels.json")


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

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert csv_response.status_code == 200
    assert "lead_id,funnel_id,full_name,email" in csv_response.text
    assert "converted_at,booked_at" in csv_response.text
    assert warm.id in csv_response.text
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
    assert by_id[converted.id]["converted_at"] is not None
    assert by_id[converted.id]["converted_at"] == by_id[converted.id]["booked_at"]
    assert by_id[converted.id]["exclusion_reasons"] == ["closed_converted_or_archived"]
    assert by_id[venezuelan.id]["excluded"] is True
    assert by_id[venezuelan.id]["suggested_buckets"] == []

    assert len(ContadoresMessage.list_by_lead(warm.id)) == 1
    assert len(ContadoresMessage.list_by_lead(booking.id)) == 1
    assert len(ContadoresMessage.list_by_lead(venezuelan.id)) == 1


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
    assert payload["running"] is True
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
                "latest_log_tail": "synced tail",
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
    assert synced_payload["launchd_out_tail"] == "synced stdout"

    history_text = (reports_dir / "contadores-crm-followup-history.md").read_text(encoding="utf-8")
    assert history_text.count("Synced summary") == 1


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
                "codex_enabled": True,
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


def test_active_offer_reply_uses_conversation_bot_without_starting_old_sequence(monkeypatch, tmp_path) -> None:
    """Replies after a promo/offer broadcast should follow that offer instead of the opener/Loom path."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer",
        phone="+593991111111",
        full_name="Karen Acosta",
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
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Cuanto demora la entrega?",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["current_stage"] == "awaiting_initial_reply"
            assert "KONECTA step=promo_web_profesional_20260505" in kwargs["conversation"]
            assert kwargs["latest_inbound"] == "Cuanto demora la entrega?"
            return ContadoresConversationBotResult(
                action="ask_scheduling_details",
                message_text="Perfecto. Me pasa su email, dia y horario para coordinar una llamada corta?",
                classification_label="active_offer_scheduling_requested",
                reason="El lead mostro interes en la promo activa.",
                missing_fields=["email", "day", "time"],
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        first_tick = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending_after_first_tick = client.get("/api/contadores/messages/pending-delivery")
        second_tick = client.post("/api/contadores/automation/tick")
        pending_after_second_tick = client.get("/api/contadores/messages/pending-delivery")

    assert first_tick.status_code == 200
    assert first_tick.json()["opener_sent"] == 0
    assert first_tick.json()["scheduling_detail_requests_sent"] == 1
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "awaiting_initial_reply"
    assert detail.json()["lead"]["automation_paused"] is False
    assert detail.json()["lead"]["last_classification_label"] == "active_offer_scheduling_requested"
    assert pending_after_first_tick.status_code == 200
    assert [item["sequence_step"] for item in pending_after_first_tick.json()["messages"]] == ["ai_reply"]
    assert "email" in pending_after_first_tick.json()["messages"][0]["text"].lower()

    assert second_tick.status_code == 200
    assert second_tick.json()["opener_sent"] == 0
    assert second_tick.json()["scheduling_detail_requests_sent"] == 0
    assert [item["sequence_step"] for item in pending_after_second_tick.json()["messages"]] == ["ai_reply"]


def test_active_offer_reply_waits_when_new_inbound_arrives_during_ai(monkeypatch, tmp_path) -> None:
    """If another lead message arrives while AI is thinking, do not answer the stale batch."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    clock = {"now": now_utc()}
    monkeypatch.setattr(contadores_endpoints, "now_utc", lambda: clock["now"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer-backoff",
        phone="+593991111112",
        full_name="Marielis",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola Marielis, si te interesa esta oferta respondeme y te mostramos un ejemplo.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=clock["now"] - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Cuanto demora?",
        created_at=clock["now"] - timedelta(seconds=45),
    )
    seen_latest_inbound: list[str] = []

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            seen_latest_inbound.append(kwargs["latest_inbound"])
            if len(seen_latest_inbound) == 1:
                ContadoresMessage.add(
                    lead_id=lead.id,
                    from_me=False,
                    text="Y el dominio?",
                    created_at=clock["now"] + timedelta(seconds=1),
                )
            return ContadoresConversationBotResult(
                action="ask_scheduling_details",
                message_text="Perfecto. Me pasa su email, dia y horario para coordinar una llamada corta?",
                classification_label="active_offer_scheduling_requested",
                reason="El lead mostro interes en la promo activa.",
                missing_fields=["email", "day", "time"],
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        first_tick = client.post("/api/contadores/automation/tick")
        pending_after_first_tick = client.get("/api/contadores/messages/pending-delivery")
        clock["now"] = clock["now"] + timedelta(seconds=41)
        second_tick = client.post("/api/contadores/automation/tick")
        pending_after_second_tick = client.get("/api/contadores/messages/pending-delivery")

    assert first_tick.status_code == 200
    assert first_tick.json()["scheduling_detail_requests_sent"] == 0
    assert pending_after_first_tick.status_code == 200
    assert pending_after_first_tick.json()["messages"] == []

    assert second_tick.status_code == 200
    assert second_tick.json()["scheduling_detail_requests_sent"] == 1
    assert seen_latest_inbound == ["Cuanto demora?", "Y el dominio?"]
    assert pending_after_second_tick.status_code == 200
    assert [item["sequence_step"] for item in pending_after_second_tick.json()["messages"]] == ["ai_reply"]


def test_conversation_batch_claim_prevents_duplicate_ai_replies(monkeypatch, tmp_path) -> None:
    """Two concurrent processors should not queue two different AI replies for one inbound."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-claim-dedupe",
        phone="+593991111113",
        full_name="Claim Dedupe",
    )
    offer = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Promo solo pagina por 19 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    inbound = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="hasta cuando es la promo?",
        created_at=now_utc() - timedelta(seconds=10),
    )
    calls = 0

    class SlowConversationBot:
        async def aforward(self, **kwargs):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text=f"Respuesta #{calls}",
                classification_label="answered_promo_deadline",
                reason="Pregunta cubierta.",
            )

    async def run_two_processors() -> list[dict[str, int]]:
        now = now_utc()
        return await asyncio.gather(
            contadores_endpoints.process_conversation_reply_batch(
                lead=lead,
                replies_in_window=[inbound],
                reply_window_start=offer.created_at,
                quiet_seconds=1,
                conversation_bot=SlowConversationBot(),
                now=now,
                active_offer_context=True,
            ),
            contadores_endpoints.process_conversation_reply_batch(
                lead=lead,
                replies_in_window=[inbound],
                reply_window_start=offer.created_at,
                quiet_seconds=1,
                conversation_bot=SlowConversationBot(),
                now=now,
                active_offer_context=True,
            ),
        )

    results = asyncio.run(run_two_processors())
    messages = [message for message in ContadoresMessage.list_by_lead(lead.id) if message.from_me]
    ai_replies = [message for message in messages if message.sequence_step == "ai_reply"]

    assert sum(result["ai_replies_sent"] for result in results) == 1
    assert calls == 1
    assert [message.text for message in ai_replies] == ["Respuesta #1"]


def test_active_offer_reply_handles_venezuela_leads(monkeypatch, tmp_path) -> None:
    """A deliberate promo can continue with Venezuelan leads even though legacy follow-ups skip them."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer-ve",
        phone="+584121234567",
        full_name="Maria Gomez",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola Maria, promo para contadores de Venezuela:\n\nSolo 19 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Cuanto demora la entrega?",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert "Venezuela" in kwargs["conversation"]
            return ContadoresConversationBotResult(
                action="ask_scheduling_details",
                message_text="Perfecto. Me pasa su email, dia y horario para coordinar una llamada corta?",
                classification_label="active_offer_scheduling_requested",
                reason="El lead mostro interes en la promo activa.",
                missing_fields=["email", "day", "time"],
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["opener_sent"] == 0
    assert tick.json()["scheduling_detail_requests_sent"] == 1
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["ai_reply"]


def test_active_offer_complete_scheduling_handoff_alerts_human(monkeypatch, tmp_path) -> None:
    """When active-offer replies include email/day/time, the normal scheduling alert path should run."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-active-offer-scheduling",
        phone="+593992222222",
        full_name="Luis Perez",
    )
    offer_sent_at = now_utc() - timedelta(minutes=4)
    ai_question_at = now_utc() - timedelta(minutes=3)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola Luis, promo para contadores de Ecuador:\n\nSolo 29 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=offer_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Perfecto. Me pasa su email, dia y horario?",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="ai_reply",
        created_at=ai_question_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Martes 10, luis@example.com",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["latest_inbound"] == "Martes 10, luis@example.com"
            return ContadoresConversationBotResult(
                action="handoff_scheduling",
                message_text="Perfecto, con esos datos lo dejamos para coordinar y le confirmamos la invitacion.",
                classification_label="booking_details_collected",
                reason="El lead paso email, dia y horario.",
                scheduling_email="luis@example.com",
                scheduling_day="Martes",
                scheduling_time="10",
                timezone="America/Guayaquil",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending_messages = client.get("/api/contadores/messages/pending-delivery")
        pending_alerts = client.get("/api/contadores/alerts/pending")

    assert tick.status_code == 200
    assert tick.json()["scheduling_handoffs"] == 1
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "booking_details_collected"
    assert "luis@example.com" in detail.json()["lead"]["last_classification_reason"]
    assert [item["sequence_step"] for item in pending_messages.json()["messages"]] == [
        "scheduling_handoff_confirmation"
    ]
    assert pending_alerts.status_code == 200
    assert pending_alerts.json()["items"][0]["lead_id"] == lead.id
    assert pending_alerts.json()["items"][0]["alert_emails"] == ["facu@example.com"]


def test_manual_outbound_can_queue_multiple_uploaded_files(monkeypatch, tmp_path) -> None:
    """Manual outbound should persist multiple operator attachments for bot delivery."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-file",
        phone="+5491888888877",
        full_name="File Lead",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        upload_response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual-media",
            data={"text": "Te mando el presupuesto"},
            files=[
                ("file", ("presupuesto.pdf", b"pdf-bytes", "application/pdf")),
                ("file", ("foto.png", b"png-bytes", "image/png")),
                ("file", ("demo.mp4", b"video-bytes", "video/mp4")),
            ],
        )
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert upload_response.status_code == 200
    assert len(upload_response.json()["queued_message_ids"]) == 3
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert len(messages) == 3
    assert messages[0]["text"] == "Te mando el presupuesto"
    assert messages[0]["media_type"] == "document"
    assert messages[0]["media_filename"] == "presupuesto.pdf"
    assert messages[0]["media_mime_type"] == "application/pdf"
    assert messages[0]["media_path"].startswith(f"data/contadores/outbound_media/{lead.id}/")
    assert messages[1]["text"] == "[image] foto.png"
    assert messages[1]["media_type"] == "image"
    assert messages[1]["media_filename"] == "foto.png"
    assert messages[2]["text"] == "[video] demo.mp4"
    assert messages[2]["media_type"] == "video"
    assert messages[2]["media_filename"] == "demo.mp4"

    media_file = data_dir / Path(messages[0]["media_path"]).relative_to("data")
    assert media_file.read_bytes() == b"pdf-bytes"
    image_file = data_dir / Path(messages[1]["media_path"]).relative_to("data")
    assert image_file.read_bytes() == b"png-bytes"
    video_file = data_dir / Path(messages[2]["media_path"]).relative_to("data")
    assert video_file.read_bytes() == b"video-bytes"
    outbound_messages = [item for item in detail_response.json()["messages"] if item["from_me"]]
    assert [item["media_type"] for item in outbound_messages] == ["document", "image", "video"]
    assert outbound_messages[0]["media_url"].startswith("/api/contadores/media/")


def test_mark_converted_action_sets_conversion_without_raw_booked_stage(monkeypatch, tmp_path) -> None:
    """Operators can mark a lead converted without sending WhatsApp."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-mark-converted",
        phone="+5491888888877",
        full_name="Converted Manual",
    )

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/mark-converted")
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert messages == []

    assert detail_response.status_code == 200
    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "converted"
    assert lead_payload["raw_stage"] == "awaiting_initial_reply"
    assert lead_payload["pipeline_stage"] == "converted"
    assert lead_payload["booked_at"] is not None
    assert lead_payload["automation_paused"] is True
    assert lead_payload["automation_paused_reason"] == "manual_converted"


def test_mark_converted_endpoint_is_canonical_and_bookings_endpoint_is_legacy_alias(monkeypatch, tmp_path) -> None:
    """The public conversion endpoint should be canonical while old booking marks still work."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    converted_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-conversions-mark",
        phone="+5491888888811",
        full_name="Conversions Endpoint",
    )
    legacy_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-bookings-legacy",
        phone="+5491888888812",
        full_name="Bookings Alias",
    )
    converted_at = now_utc()
    legacy_at = now_utc()

    with TestClient(app) as client:
        converted_response = client.post(
            f"/api/contadores/conversions/mark?lead_id={converted_lead.id}",
            json={"converted_at": converted_at.isoformat()},
        )
        legacy_response = client.post(
            f"/api/contadores/bookings/mark?lead_id={legacy_lead.id}",
            json={"booked_at": legacy_at.isoformat()},
        )
        stage_alias_response = client.get("/api/contadores/leads?stage=booked")

    assert converted_response.status_code == 200
    converted_payload = converted_response.json()
    assert converted_payload["stage"] == "converted"
    assert converted_payload["raw_stage"] == "awaiting_initial_reply"
    assert converted_payload["pipeline_stage"] == "converted"
    assert converted_payload["attention_state"] == "converted"
    assert converted_payload["converted_at"] is not None
    assert converted_payload["converted_at"] == converted_payload["booked_at"]
    assert converted_payload["automation_paused_reason"] == "manual_converted"

    assert stage_alias_response.status_code == 200
    assert {item["id"] for item in stage_alias_response.json()["leads"]} == {converted_lead.id, legacy_lead.id}

    assert legacy_response.status_code == 200
    legacy_payload = legacy_response.json()
    assert legacy_payload["stage"] == "converted"
    assert legacy_payload["raw_stage"] == "awaiting_initial_reply"
    assert legacy_payload["pipeline_stage"] == "converted"
    assert legacy_payload["converted_at"] is not None
    assert legacy_payload["converted_at"] == legacy_payload["booked_at"]
    assert legacy_payload["automation_paused_reason"] == "manual_converted"
    legacy_row = ContadoresLead.get_by_id(legacy_lead.id)
    assert legacy_row is not None
    assert legacy_row.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
    assert legacy_row.booked_at is not None


def test_lifecycle_v2_fields_are_persisted_after_flow_updates(monkeypatch, tmp_path) -> None:
    """The conceptual lifecycle state should live in DB, not only response serialization."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-lifecycle-v2",
        phone="+5491888888801",
        full_name="Lifecycle Persisted",
    )

    assert ContadoresLead.get_by_id(lead.id).pipeline_stage == "new"

    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )
    meeting_lead = ContadoresLead.get_by_id(lead.id)
    assert meeting_lead.pipeline_stage == "meeting_sent"
    assert meeting_lead.queue_state == "automation"
    assert meeting_lead.terminal_state == "open"
    assert meeting_lead.attention_state == "clear"

    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.BOOKED,
        booked_at=now_utc(),
        automation_paused=True,
        automation_paused_reason="manual_converted",
    )
    converted_lead = ContadoresLead.get_by_id(lead.id)
    assert converted_lead.pipeline_stage == "converted"
    assert converted_lead.queue_state == "none"
    assert converted_lead.terminal_state == "open"
    assert converted_lead.attention_state == "converted"

    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CLOSED,
        closed_at=now_utc(),
        stage_before_closed=ContadoresLeadStage.BOOKED,
    )
    closed_lead = ContadoresLead.get_by_id(lead.id)
    assert closed_lead.pipeline_stage == "closed"
    assert closed_lead.queue_state == "none"
    assert closed_lead.terminal_state == "closed"
    assert closed_lead.attention_state == "closed"


def test_lifecycle_v2_fields_refresh_after_message_activity(monkeypatch, tmp_path) -> None:
    """Inbound/outbound messages should update persisted owner and attention state."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-lifecycle-messages",
        phone="+5491888888802",
        full_name="Lifecycle Messages",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_handoff",
    )

    inbound_at = now_utc()
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="tengo una duda",
        created_at=inbound_at,
    )
    needs_reply_lead = ContadoresLead.get_by_id(lead.id)
    assert needs_reply_lead.queue_state == "operator"
    assert needs_reply_lead.attention_state == "needs_reply"

    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="ahi te respondo",
        created_at=inbound_at + timedelta(minutes=1),
    )
    answered_lead = ContadoresLead.get_by_id(lead.id)
    assert answered_lead.queue_state == "operator"
    assert answered_lead.attention_state == "answered"


def test_lifecycle_v2_backfill_repairs_stale_persisted_values(monkeypatch, tmp_path) -> None:
    """Schema maintenance should repair v2 lifecycle fields on existing rows."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-lifecycle-backfill",
        phone="+5491888888803",
        full_name="Lifecycle Backfill",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.BOOKED,
        booked_at=now_utc(),
    )
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql(
            """
            UPDATE contadores_leads
            SET pipeline_stage = 'new',
                queue_state = 'automation',
                terminal_state = 'open',
                attention_state = 'clear'
            WHERE id = ?
            """,
            (lead.id,),
        )

    database_module.ensure_contadores_lifecycle_columns()

    backfilled_lead = ContadoresLead.get_by_id(lead.id)
    assert backfilled_lead.pipeline_stage == "converted"
    assert backfilled_lead.queue_state == "none"
    assert backfilled_lead.terminal_state == "open"
    assert backfilled_lead.attention_state == "converted"


def test_pause_automation_action_keeps_stage_and_blocks_due_agent_followup(monkeypatch, tmp_path) -> None:
    """Operators can stop bot automation without moving the lead or sending WhatsApp."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_ENABLED", True)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_CONVERSATION_ENABLED", True)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-pause-automation",
        phone="+5491888888879",
        full_name="Paused Automation",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc() - timedelta(hours=1),
    )
    ScheduledAgentTask.create(
        target_type="lead",
        target_id=lead.id,
        due_at=now_utc() - timedelta(minutes=1),
        reason="follow-up test",
        instruction="send a useful next message",
    )

    def fail_run_codex_agent(**kwargs):
        raise AssertionError("paused lead should not wake Codex")

    monkeypatch.setattr(contadores_endpoints, "run_codex_agent", fail_run_codex_agent)

    with TestClient(app) as client:
        pause_response = client.post(f"/api/contadores/leads/{lead.id}/actions/pause-automation")
        tick_response = client.post("/api/contadores/automation/tick")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert pause_response.status_code == 200
    assert tick_response.status_code == 200
    assert tick_response.json()["scheduled_agent_tasks_processed"] == 0
    assert ScheduledAgentTask.list_due(now=now_utc()) == []
    assert pending_response.json()["messages"] == []

    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "calendly_sent"
    assert lead_payload["automation_paused"] is True
    assert lead_payload["automation_paused_reason"] == "manual_pause"


def test_legacy_mark_booked_alias_keeps_converted_leads_out_of_pending_manual_ping(monkeypatch, tmp_path) -> None:
    """The old mark-booked action must still convert and block pending WhatsApp dispatch."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-booked-with-ping",
        phone="+5491888888878",
        full_name="Booked With Ping",
    )
    manual_booked_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-booked-alias",
        phone="+5491888888879",
        full_name="Manual Booked Alias",
    )

    with TestClient(app) as client:
        ping_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        booked_response = client.post(f"/api/contadores/leads/{lead.id}/actions/mark-booked")
        manual_booked_response = client.post(
            f"/api/contadores/leads/{manual_booked_lead.id}/actions/send-manual-booked"
        )
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert ping_response.status_code == 200
    assert booked_response.status_code == 200
    assert manual_booked_response.status_code == 200
    assert pending_response.status_code == 200
    assert pending_response.json()["messages"] == []
    booked_payload = booked_response.json()["lead"]
    assert booked_payload["stage"] == "converted"
    assert booked_payload["raw_stage"] == "needs_human"
    assert booked_payload["pipeline_stage"] == "converted"
    assert booked_payload["converted_at"] == booked_payload["booked_at"]
    manual_booked_payload = manual_booked_response.json()["lead"]
    assert manual_booked_payload["stage"] == "converted"
    assert manual_booked_payload["raw_stage"] == "awaiting_initial_reply"
    assert manual_booked_payload["pipeline_stage"] == "converted"
    assert manual_booked_payload["converted_at"] == manual_booked_payload["booked_at"]
    booked_row = ContadoresLead.get_by_id(lead.id)
    manual_booked_row = ContadoresLead.get_by_id(manual_booked_lead.id)
    assert booked_row is not None
    assert manual_booked_row is not None
    assert booked_row.stage == ContadoresLeadStage.NEEDS_HUMAN
    assert manual_booked_row.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY


def test_converted_leads_with_legacy_stage_do_not_expose_pending_delivery(monkeypatch, tmp_path) -> None:
    """Converted leads must stay out of dispatch even if the raw stage was not rewritten."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-booked-at-with-ping",
        phone="+5491888888876",
        full_name="Converted With Legacy Stage",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_handoff",
    )

    with TestClient(app) as client:
        ping_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        ContadoresLead.update_flow_state(
            lead.id,
            booked_at=now_utc(),
            automation_paused=True,
            automation_paused_reason="manual_workstation_conversion",
        )
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert ping_response.status_code == 200
    assert pending_response.status_code == 200
    assert pending_response.json()["messages"] == []
    assert detail_response.status_code == 200
    lead_payload = detail_response.json()["lead"]
    assert lead_payload["raw_stage"] == "needs_human"
    assert lead_payload["stage"] == "converted"
    assert lead_payload["pipeline_stage"] == "converted"


def test_converted_leads_reject_new_crm_outbound_before_queueing(monkeypatch, tmp_path) -> None:
    """Converted leads should not accumulate CRM follow-up messages that dispatch later suppresses."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-converted-no-crm-outbound",
        phone="+5491888888875",
        full_name="Converted No CRM Outbound",
    )
    add_recent_inbound(lead.id)
    ContadoresLead.mark_converted(lead.id, automation_paused=True, automation_paused_reason="manual_converted")

    with TestClient(app) as client:
        manual_message_response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual",
            json={"text": "Te escribo de vuelta"},
        )
        manual_ping_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert manual_message_response.status_code == 400
    assert manual_message_response.json()["detail"] == (
        "Lead is converted. Use Workstation delivery instead of CRM follow-up messages."
    )
    assert manual_ping_response.status_code == 400
    assert manual_ping_response.json()["detail"] == (
        "Lead is converted. Use Workstation delivery instead of CRM follow-up messages."
    )
    assert pending_response.json()["messages"] == []
    assert [message for message in ContadoresMessage.list_by_lead(lead.id) if message.from_me] == []


def test_converted_leads_still_allow_workstation_delivery_steps(monkeypatch, tmp_path) -> None:
    """Converted clients can still receive Workstation deliverables through explicit delivery steps."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-converted-workstation-outbound",
        phone="+5491888888874",
        full_name="Converted Workstation Outbound",
    )
    add_recent_inbound(lead.id)
    converted = ContadoresLead.mark_converted(
        lead.id,
        automation_paused=True,
        automation_paused_reason="workstation_solo_page_started",
    )
    assert converted is not None

    row = contadores_endpoints.enqueue_lead_outbound(
        lead=converted,
        text="Le dejo la vista previa.",
        sequence_step="workstation_preview_video",
    )

    assert row.id is not None
    assert row.sequence_step == "workstation_preview_video"


def test_archived_overlay_rejects_new_outbound_and_suppresses_existing_pending(monkeypatch, tmp_path) -> None:
    """Archived overlays should behave as terminal even if the raw stage has not been rewritten."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-archived-overlay-outbound",
        phone="+5491888888873",
        full_name="Archived Overlay Outbound",
    )
    add_recent_inbound(lead.id)
    pending = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Mensaje viejo",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step="manual",
    )
    assert pending.id is not None
    ContadoresLead.update_flow_state(lead.id, archived_at=now_utc())

    with TestClient(app) as client:
        manual_message_response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual",
            json={"text": "Nuevo mensaje"},
        )
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert manual_message_response.status_code == 400
    assert manual_message_response.json()["detail"] == (
        "Lead is archived. Unarchive the lead before sending WhatsApp messages."
    )
    assert pending_response.json()["messages"] == []


def test_bulk_manual_ping_queues_selected_leads(monkeypatch, tmp_path) -> None:
    """Operators can apply the manual ping template to selected chats in one request."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    first = ContadoresLead.upsert(
        external_lead_id="bulk-ping-1",
        phone="+5491888888801",
        full_name="Bulk One",
    )
    second = ContadoresLead.upsert(
        external_lead_id="bulk-ping-2",
        phone="+5491888888802",
        full_name="Bulk Two",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/leads/bulk-action",
            json={
                "lead_ids": [first.id, second.id],
                "action": "send-manual-ping",
                "manual_ping_confirmed": True,
            },
        )
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert len(payload["queued_message_ids"]) == 2
    assert [item["ok"] for item in payload["results"]] == [True, True]

    messages = pending_response.json()["messages"]
    assert [item["lead_id"] for item in messages] == [first.id, second.id]
    assert {item["sequence_step"] for item in messages} == {"manual_ping_template"}
    assert {item["whatsapp_template_name"] for item in messages} == {"contadores_manual_ping_es_v1"}


def test_bulk_manual_ping_requires_explicit_confirmation(monkeypatch, tmp_path) -> None:
    """Bulk Manual ping should not run from a default, stale modal, or ambiguous script."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="bulk-ping-unconfirmed",
        phone="+5491888888803",
        full_name="Bulk Unconfirmed",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/leads/bulk-action",
            json={
                "lead_ids": [lead.id],
                "action": "send-manual-ping",
            },
        )

    assert response.status_code == 400
    assert "explicit confirmation" in response.json()["detail"]
    assert ContadoresMessage.list_by_lead(lead.id) == []


def test_bulk_custom_message_pauses_selected_leads(monkeypatch, tmp_path) -> None:
    """Custom batch messages should pause automation for each selected lead."""
    configure_contadores_db(monkeypatch, tmp_path)
    first = ContadoresLead.upsert(
        external_lead_id="bulk-custom-1",
        phone="+5491888888811",
        full_name="Custom One",
    )
    second = ContadoresLead.upsert(
        external_lead_id="bulk-custom-2",
        phone="+5491888888812",
        full_name="Custom Two",
    )
    add_recent_inbound(first.id)
    add_recent_inbound(second.id)

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/leads/bulk-action",
            json={
                "lead_ids": [first.id, second.id],
                "action": "custom",
                "text": "Hola, retomo por aca.",
            },
        )
        first_detail = client.get(f"/api/contadores/leads/{first.id}")
        second_detail = client.get(f"/api/contadores/leads/{second.id}")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["succeeded"] == 2
    assert first_detail.json()["lead"]["stage"] == "needs_human"
    assert first_detail.json()["lead"]["automation_paused"] is True
    assert second_detail.json()["lead"]["stage"] == "needs_human"
    assert second_detail.json()["lead"]["automation_paused"] is True
    assert [item["text"] for item in pending_response.json()["messages"]] == [
        "Hola, retomo por aca.",
        "Hola, retomo por aca.",
    ]


def test_contadores_config_normalizes_configured_calendly_base_url(monkeypatch, tmp_path) -> None:
    """Calendly values should stay config-owned while trimming unstable trailing slash noise."""
    configure_contadores_db(monkeypatch, tmp_path)

    ContadoresConfig.update(calendly_base_url=" https://calendly.com/custom/funnel/ ")
    config = ContadoresConfig.get()

    assert config.calendly_base_url == "https://calendly.com/custom/funnel"


def test_contadores_config_does_not_expose_calendly_webhook_tracking(monkeypatch, tmp_path) -> None:
    """Config should not surface Calendly webhook tracking state to operators."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("CALENDLY_WEBHOOK_SIGNING_KEY", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/contadores/config")

    assert response.status_code == 200
    assert "calendly_webhook_configured" not in response.json()


def test_contadores_automation_tick_sends_video_check_after_wait(monkeypatch, tmp_path) -> None:
    """When the Loom wait expires without replies, the video-check prompt must be queued."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-2",
        phone="+5491222222222",
        full_name="Bruno Diaz",
    )
    loom_sent_at = now_utc() - timedelta(minutes=6)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        last_inbound_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["video_checks_sent"] == 1
    assert pending.status_code == 200
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["video_check"]


def test_contadores_automation_tick_sends_24h_opener_followup_without_changing_stage(monkeypatch, tmp_path) -> None:
    """After 24 hours without inbound, the lead should get one reminder and stay in the same stage."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-followup",
        phone="+5491222000000",
        full_name="Opener Followup",
    )
    opener_sent_at = now_utc() - timedelta(hours=25)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=opener_sent_at,
    )

    with TestClient(app) as client:
        first_tick = client.post("/api/contadores/automation/tick")
        detail_after_first_tick = client.get(f"/api/contadores/leads/{lead.id}")
        pending_after_first_tick = client.get("/api/contadores/messages/pending-delivery")
        second_tick = client.post("/api/contadores/automation/tick")
        pending_after_second_tick = client.get("/api/contadores/messages/pending-delivery")

    assert first_tick.status_code == 200
    assert detail_after_first_tick.status_code == 200
    assert detail_after_first_tick.json()["lead"]["stage"] == "awaiting_initial_reply"
    assert detail_after_first_tick.json()["lead"]["raw_stage"] == "awaiting_initial_reply"
    assert pending_after_first_tick.status_code == 200
    assert [item["sequence_step"] for item in pending_after_first_tick.json()["messages"]] == [
        "opener_followup_24h"
    ]
    assert pending_after_first_tick.json()["messages"][0]["text"] == (
        "Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable"
    )
    assert pending_after_first_tick.json()["messages"][0]["whatsapp_template_name"] == (
        "contadores_opener_followup_24h_es_v1"
    )
    assert pending_after_first_tick.json()["messages"][0]["whatsapp_template_language"] == "es"

    assert second_tick.status_code == 200
    assert pending_after_second_tick.status_code == 200
    assert [item["sequence_step"] for item in pending_after_second_tick.json()["messages"]] == [
        "opener_followup_24h"
    ]


def test_contadores_automation_tick_skips_hard_excluded_followups(monkeypatch, tmp_path) -> None:
    """Automated follow-ups must not queue messages for hard-excluded leads."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    opener_sent_at = now_utc() - timedelta(hours=25)

    venezuelan = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-followup-ve",
        phone="0412-7174588",
        full_name="Venezuela Followup",
    )
    workstation = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-followup-workstation",
        phone="+5491222000001",
        full_name="Workstation Followup",
    )
    eligible = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-followup-eligible",
        phone="+5491222000002",
        full_name="Eligible Followup",
    )
    WorkstationClient.create_for_lead(workstation)

    for lead in [venezuelan, workstation, eligible]:
        ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
            opener_sent_at=opener_sent_at,
        )

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert pending.status_code == 200
    messages = pending.json()["messages"]
    assert [item["lead_id"] for item in messages] == [eligible.id]
    assert [item["sequence_step"] for item in messages] == ["opener_followup_24h"]
    assert ContadoresMessage.list_by_lead(venezuelan.id) == []
    assert ContadoresMessage.list_by_lead(workstation.id) == []


def test_contadores_automation_tick_affirmative_reply_asks_for_scheduling_details(monkeypatch, tmp_path) -> None:
    """A clear affirmative post-Loom reply should ask for call details, not send Calendly."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-3",
        phone="+5491333333333",
        full_name="Carla Soto",
    )
    loom_sent_at = now_utc() - timedelta(minutes=6)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si, entendi todo y quiero avanzar.",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert "quiero avanzar" in kwargs["latest_inbound"].lower()
            assert "LEAD" in kwargs["conversation"]
            return ContadoresConversationBotResult(
                action="ask_scheduling_details",
                message_text="Perfecto. Me pasaria su email, dia y horario para coordinar una llamada de 15 minutos?",
                classification_label="scheduling_details_requested",
                reason="El lead quiere avanzar pero faltan datos de agenda.",
                missing_fields=["email", "dia", "horario"],
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["scheduling_detail_requests_sent"] == 1
    assert detail.status_code == 200
    assert response.json()["calendly_sent"] == 0
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "ai_reply_conversation"
    assert detail.json()["lead"]["manual_reply_status"] == "answered"
    assert detail.json()["lead"]["last_classification_label"] == "scheduling_details_requested"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["ai_reply"]
    assert "email" in pending.json()["messages"][0]["text"].lower()


def test_contadores_automation_tick_answers_simple_video_confirmation(monkeypatch, tmp_path) -> None:
    """A plain watched-video confirmation should get one bot reply and move to Manual."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-video-confirmation",
        phone="+59175432222",
        full_name="Video Confirmation",
        funnel_id="abogados",
    )
    loom_sent_at = now_utc() - timedelta(minutes=11)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
        last_inbound_at=now_utc() - timedelta(seconds=45),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["funnel_id"] == "abogados"
            assert kwargs["funnel_label"] == "Abogados"
            assert kwargs["phone"] == "+59175432222"
            assert kwargs["latest_inbound"] == "Si"
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text=(
                    "Perfecto.\n\n"
                    "Nosotros lo que hacemos es ayudarle a conseguir mas consultas de potenciales "
                    "clientes en Bolivia, directo a su WhatsApp.\n\n"
                    "Para avanzar, que dia le queda mejor esta semana?"
                ),
                classification_label="video_confirmation_answered",
                reason="Solo confirmo que vio el video.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        create_funnel = client.post("/api/funnels", json=build_abogados_test_funnel())
        first_tick = client.post("/api/contadores/automation/tick", params={"funnel_id": "abogados"})
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending_after_first_tick = client.get("/api/contadores/messages/pending-delivery")
        second_tick = client.post("/api/contadores/automation/tick", params={"funnel_id": "abogados"})
        pending_after_second_tick = client.get("/api/contadores/messages/pending-delivery")

    assert create_funnel.status_code == 200
    assert first_tick.status_code == 200
    assert first_tick.json()["ai_replies_sent"] == 1
    assert first_tick.json()["video_confirmation_recaps_sent"] == 0
    assert first_tick.json()["calendly_sent"] == 0
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "ai_reply_conversation"
    assert detail.json()["lead"]["manual_reply_status"] == "answered"
    assert detail.json()["lead"]["last_classification_label"] == "video_confirmation_answered"
    assert pending_after_first_tick.status_code == 200
    first_messages = pending_after_first_tick.json()["messages"]
    assert [item["sequence_step"] for item in first_messages] == ["ai_reply"]
    assert "Bolivia" in first_messages[0]["text"]
    assert "directo a su WhatsApp" in first_messages[0]["text"]

    assert second_tick.status_code == 200
    assert second_tick.json()["ai_replies_sent"] == 0
    assert pending_after_second_tick.status_code == 200
    assert [item["sequence_step"] for item in pending_after_second_tick.json()["messages"]] == [
        "ai_reply"
    ]


def test_conversation_bot_can_offer_solo_page_promo_for_warm_deferral(monkeypatch, tmp_path) -> None:
    """A warm post-video deferral can receive the page-only promo and stay automated."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-warm-deferral-promo",
        phone="+593991111111",
        full_name="Luis Gerardo",
        funnel_id="abogados",
    )
    loom_sent_at = now_utc() - timedelta(minutes=11)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
        last_inbound_at=now_utc() - timedelta(seconds=45),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Perfecto, mirelo tranquilo.\n\nEs corto, son 60 segundos. Cualquier duda me escribe por aca.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="ai_reply",
        created_at=now_utc() - timedelta(minutes=1),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si ya lo vi yo les estaré comunicando muchas gracias",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["funnel_id"] == "abogados"
            assert kwargs["latest_inbound"] == "Si ya lo vi yo les estaré comunicando muchas gracias"
            return ContadoresConversationBotResult(
                action="offer_solo_page_promo",
                classification_label="warm_deferral_solo_page_promo",
                reason="El lead mostro interes tibio despues del video.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)
    monkeypatch.setattr(contadores_endpoints, "choose_solo_page_promo_price_usd", lambda lead_id: 99)

    with TestClient(app) as client:
        create_funnel = client.post("/api/funnels", json=build_abogados_test_funnel())
        tick = client.post("/api/contadores/automation/tick", params={"funnel_id": "abogados"})
        pending = client.get("/api/contadores/messages/pending-delivery")
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert create_funnel.status_code == 200
    assert tick.status_code == 200
    assert tick.json()["ai_replies_sent"] == 1
    assert pending.status_code == 200
    messages = pending.json()["messages"]
    assert [item["sequence_step"] for item in messages] == ["offer_solo_page_promo"]
    assert "solo la pagina web profesional" in messages[0]["text"]
    assert "99 USD" in messages[0]["text"]
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "awaiting_video_reply"
    assert detail.json()["lead"]["automation_paused"] is False
    assert detail.json()["lead"]["last_classification_label"] == "solo_page_promo_offered"


def test_conversation_bot_answers_common_questions_without_human_handoff(monkeypatch, tmp_path) -> None:
    """Known objections should get AI replies and move the conversation to Manual."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    inbound_texts = [
        "Cuanto cuesta?",
        "En que pais es yo soy de Bolivia",
        "Aun no vi el video, estaba manejando",
        "Que garantia hay si no llegan clientes?",
        "Pagina web tengo",
    ]
    loom_sent_at = now_utc() - timedelta(minutes=7)
    leads: list[ContadoresLead] = []
    for index, inbound_text in enumerate(inbound_texts):
        lead = ContadoresLead.upsert(
            external_lead_id=f"sheet-row-common-question-{index}",
            phone=f"+54913333333{index:02d}",
            full_name=f"Common Question {index}",
        )
        ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
            opener_sent_at=loom_sent_at - timedelta(minutes=1),
            first_reply_received_at=loom_sent_at - timedelta(minutes=1),
            loom_sent_at=loom_sent_at,
        )
        ContadoresMessage.add(
            lead_id=lead.id,
            from_me=False,
            text=inbound_text,
            created_at=now_utc() - timedelta(seconds=45),
        )
        leads.append(lead)

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text=f"Respuesta util para: {kwargs['latest_inbound']}",
                classification_label="answered_known_question",
                reason="Pregunta cubierta por el playbook.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        pending = client.get("/api/contadores/messages/pending-delivery")
        alerts = client.get("/api/contadores/alerts/pending")
        details = [client.get(f"/api/contadores/leads/{lead.id}") for lead in leads]

    assert response.status_code == 200
    assert response.json()["ai_replies_sent"] == len(inbound_texts)
    assert response.json()["human_handoffs"] == 0
    assert pending.status_code == 200
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["ai_reply"] * len(inbound_texts)
    assert alerts.status_code == 200
    assert alerts.json()["items"] == []
    assert [detail.json()["lead"]["stage"] for detail in details] == ["needs_human"] * len(inbound_texts)
    assert [detail.json()["lead"]["automation_paused_reason"] for detail in details] == [
        "ai_reply_conversation"
    ] * len(inbound_texts)
    assert [detail.json()["lead"]["manual_reply_status"] for detail in details] == ["answered"] * len(inbound_texts)


def test_conversation_bot_sends_rejection_survey_and_closes_lead(monkeypatch, tmp_path) -> None:
    """A service rejection should receive the exact survey and then leave automation."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-rejection-survey",
        phone="+5491333333388",
        full_name="Rejection Survey",
    )
    loom_sent_at = now_utc() - timedelta(minutes=7)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="No me interesa, gracias",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["latest_inbound"] == "No me interesa, gracias"
            return ContadoresConversationBotResult(
                action="close_lead",
                message_text=REJECTION_SURVEY_REPLY,
                classification_label="service_rejection_survey",
                reason="El lead rechazo el servicio.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")
        second_tick = client.post("/api/contadores/automation/tick")
        pending_after_second_tick = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["closed_by_ai"] == 1
    assert response.json()["ai_replies_sent"] == 1
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "closed"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "ai_closed"
    assert pending.status_code == 200
    assert len(pending.json()["messages"]) == 1
    assert pending.json()["messages"][0]["text"] == REJECTION_SURVEY_REPLY
    assert pending.json()["messages"][0]["sequence_step"] == "ai_rejection_survey"
    assert second_tick.status_code == 200
    assert second_tick.json()["closed_by_ai"] == 0
    assert [item["message_id"] for item in pending_after_second_tick.json()["messages"]] == [
        pending.json()["messages"][0]["message_id"]
    ]


def test_conversation_bot_codex_failure_records_runtime_alert_without_handoff(monkeypatch, tmp_path) -> None:
    """Codex fallback alerts should keep the AI reply and move the lead to Manual."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
        alert_emails=["ops@example.com"],
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-codex-fallback",
        phone="+5491333333377",
        full_name="Codex Fallback",
    )
    loom_sent_at = now_utc() - timedelta(minutes=7)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Cuanto cuesta?",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert "funnel_info" in kwargs
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text="La inversion es de 599 USD mensuales.",
                classification_label="answered_price",
                reason="Fallback respondio precio.",
                runtime_provider="dspy_fallback",
                runtime_error=(
                    "Codex ChatGPT failed: RuntimeError: boom. "
                    "Para reautenticar ChatGPT Codex, generar un codigo nuevo con "
                    "`env -u OPENAI_API_KEY codex login --device-auth` y abrir "
                    "https://auth.openai.com/codex/device."
                ),
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")
        alerts = client.get("/api/contadores/alerts/pending")

    assert response.status_code == 200
    assert response.json()["ai_replies_sent"] == 1
    assert response.json()["human_handoffs"] == 0
    assert response.json()["codex_fallback_alerts"] == 1
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "ai_reply_conversation"
    assert detail.json()["lead"]["manual_reply_status"] == "answered"
    assert pending.json()["messages"][0]["sequence_step"] == "ai_reply"
    assert alerts.status_code == 200
    assert len(alerts.json()["items"]) == 1
    alert = alerts.json()["items"][0]
    assert alert["alert_kind"] == "runtime"
    assert alert["codex_error"].startswith("Codex ChatGPT failed: RuntimeError: boom")
    assert "https://auth.openai.com/codex/device" in alert["codex_error"]
    assert alert["fallback_action"] == "send_reply"
    assert alert["latest_inbound_text"] == "Cuanto cuesta?"
    assert "Codex ChatGPT fallo" in alert["reason"]
    assert "codex login --device-auth" in alert["reason"]


def test_unanswered_question_email_reply_sends_whatsapp_and_teaches_playbook(monkeypatch, tmp_path) -> None:
    """Unknown questions should wait for an email reply, then answer and save the teaching."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    learned_codex = tmp_path / ".codex" / "operator-learned-answers.md"
    learned_wiki = tmp_path / "wiki" / "operator-learned-answers.md"
    monkeypatch.setattr(
        contadores_endpoints,
        "OPERATOR_LEARNED_ANSWER_PATHS",
        [learned_codex, learned_wiki],
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-unanswered-question",
        phone="+593991111114",
        full_name="Unknown Question",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Promo solo pagina por 19 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="hasta cuando es la promo?",
        created_at=now_utc() - timedelta(seconds=10),
    )

    class UnknownConversationBot:
        async def aforward(self, **kwargs):
            return ContadoresConversationBotResult(
                action="handoff_human",
                message_text="",
                classification_label="unknown_promo_deadline",
                reason="No hay fecha de vencimiento de promo en source of truth.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", UnknownConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        pending_before = client.get("/api/contadores/messages/pending-delivery")
        alerts = client.get("/api/contadores/alerts/pending")
        alert_id = alerts.json()["items"][0]["runtime_alert_id"]
        marked = client.post(
            f"/api/contadores/runtime-alerts/{alert_id}/mark-alerted",
            json={
                "email_thread_id": "thread-promo-deadline",
                "email_message_id": "email-alert-1",
                "email_inbox_id": "alerts-inbox",
                "email_inbox_address": "alerts@example.com",
            },
        )
        reply = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "alerts-inbox",
                "message_id": "email-reply-1",
                "from_email": "facu@example.com",
                "thread_id": "thread-promo-deadline",
                "plain_text": (
                    "Respuesta: La promo esta disponible hasta el viernes.\n\n"
                    "Si le interesa, le mostramos un ejemplo y vemos si le sirve para su caso."
                ),
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending_after = client.get("/api/contadores/messages/pending-delivery")

    assert tick.status_code == 200
    assert tick.json()["human_handoffs"] == 1
    assert pending_before.json()["messages"] == []
    assert alerts.status_code == 200
    assert alerts.json()["items"][0]["automation_paused_reason"] == "unanswered_lead_question"
    assert "NO SE COMO RESPONDER" in alerts.json()["items"][0]["reason"]
    assert "Promo solo pagina por 19 USD." in alerts.json()["items"][0]["conversation_transcript"]
    assert "hasta cuando es la promo?" in alerts.json()["items"][0]["conversation_transcript"]
    assert marked.status_code == 200
    assert reply.status_code == 200
    assert reply.json()["queued_message_ids"] == [pending_after.json()["messages"][0]["message_id"]]
    assert detail.json()["lead"]["stage"] == "awaiting_initial_reply"
    assert detail.json()["lead"]["automation_paused"] is False
    assert pending_after.json()["messages"][0]["text"].startswith("La promo esta disponible")
    assert "hasta cuando es la promo?" in learned_codex.read_text(encoding="utf-8")
    assert "La promo esta disponible hasta el viernes." in learned_wiki.read_text(encoding="utf-8")


def test_unanswered_question_email_reply_only_teaches_when_crm_already_answered(monkeypatch, tmp_path) -> None:
    """A late operator email reply should not duplicate a CRM answer already sent."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    learned_codex = tmp_path / ".codex" / "operator-learned-answers.md"
    learned_wiki = tmp_path / "wiki" / "operator-learned-answers.md"
    monkeypatch.setattr(
        contadores_endpoints,
        "OPERATOR_LEARNED_ANSWER_PATHS",
        [learned_codex, learned_wiki],
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-late-email-answer",
        phone="+593991111115",
        full_name="Late Email Answer",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Promo solo pagina por 19 USD.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="hasta cuando es la promo?",
        created_at=now_utc() - timedelta(seconds=10),
    )

    class UnknownConversationBot:
        async def aforward(self, **kwargs):
            return ContadoresConversationBotResult(
                action="handoff_human",
                message_text="",
                classification_label="unknown_promo_deadline",
                reason="No hay fecha de vencimiento de promo en source of truth.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", UnknownConversationBot)

    with TestClient(app) as client:
        tick = client.post("/api/contadores/automation/tick")
        alerts = client.get("/api/contadores/alerts/pending")
        alert_id = alerts.json()["items"][0]["runtime_alert_id"]
        marked = client.post(
            f"/api/contadores/runtime-alerts/{alert_id}/mark-alerted",
            json={
                "email_thread_id": "thread-late-promo-deadline",
                "email_message_id": "email-alert-1",
                "email_inbox_id": "alerts-inbox",
                "email_inbox_address": "alerts@example.com",
            },
        )
        manual_answer = client.post(
            f"/api/contadores/followup/leads/{lead.id}/messages",
            headers={"X-Internal-Token": "test-internal-token"},
            json={"text": "La promo esta disponible hasta el viernes.", "dedupe_hours": 24},
        )
        reply = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "alerts-inbox",
                "message_id": "email-reply-1",
                "from_email": "facu@example.com",
                "thread_id": "thread-late-promo-deadline",
                "plain_text": "Respuesta: La promo esta disponible hasta el viernes.",
            },
        )
        pending_after = client.get("/api/contadores/messages/pending-delivery")
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert tick.status_code == 200
    assert marked.status_code == 200
    assert manual_answer.status_code == 200
    assert reply.status_code == 200
    assert reply.json()["status"] == "learned_no_send"
    assert reply.json()["reason"] == "lead_already_answered"
    assert reply.json()["queued_message_ids"] == []
    assert [item["text"] for item in pending_after.json()["messages"]] == ["La promo esta disponible hasta el viernes."]
    assert detail.json()["lead"]["manual_reply_status"] == "answered"
    assert "hasta cuando es la promo?" in learned_codex.read_text(encoding="utf-8")
    assert "La promo esta disponible hasta el viernes." in learned_wiki.read_text(encoding="utf-8")


def test_conversation_bot_handoffs_complete_scheduling_details(monkeypatch, tmp_path) -> None:
    """Email, day, and time should trigger a scheduling handoff alert, not Calendly."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-scheduling-complete",
        phone="+5491133333399",
        full_name="Scheduling Complete",
        email="crm@example.com",
    )
    loom_sent_at = now_utc() - timedelta(minutes=7)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Martes a las 15 hs. Mi mail es cliente@example.com",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            return ContadoresConversationBotResult(
                action="handoff_scheduling",
                message_text="Perfecto, con esos datos lo dejamos para coordinar y le confirmamos la invitacion.",
                classification_label="booking_details_collected",
                reason="El lead dio todos los datos para coordinar.",
                scheduling_email="cliente@example.com",
                scheduling_day="martes",
                scheduling_time="15 hs",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")
        alerts = client.get("/api/contadores/alerts/pending")

    assert response.status_code == 200
    assert response.json()["scheduling_handoffs"] == 1
    assert response.json()["calendly_sent"] == 0
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "booking_details_collected"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == [
        "scheduling_handoff_confirmation"
    ]
    assert alerts.status_code == 200
    assert [item["lead_id"] for item in alerts.json()["items"]] == [lead.id]
    assert "cliente@example.com" in alerts.json()["items"][0]["reason"]
    assert "martes" in alerts.json()["items"][0]["reason"]
    assert "15 hs" in alerts.json()["items"][0]["reason"]
    assert "America/Buenos_Aires" in alerts.json()["items"][0]["reason"]


def test_post_calendly_inbound_question_is_answered_by_conversation_bot(monkeypatch, tmp_path) -> None:
    """A question after Calendly should be answered by the bot instead of immediate handoff."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_quiet_seconds=1,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-post-cal-question",
        phone="+5491444444401",
        full_name="Lara Reply",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=calendly_sent_at,
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["current_stage"] == "calendly_sent"
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text="Si, le explico. La inversion es de 599 USD mensuales.",
                classification_label="answered_post_calendly_question",
                reason="Pregunta conocida posterior al cierre.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        inbound = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": lead.phone,
                "text": "Tengo una duda antes de agendar. Cuanto cuesta?",
            },
        )
        detail_after_inbound = client.get(f"/api/contadores/leads/{lead.id}")
        monkeypatch.setattr(
            contadores_endpoints,
            "now_utc",
            lambda: datetime.now(timezone.utc) + timedelta(seconds=5),
        )
        tick = client.post("/api/contadores/automation/tick")
        detail_after_tick = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")
        alerts = client.get("/api/contadores/alerts/pending")

    assert inbound.status_code == 200
    assert detail_after_inbound.json()["lead"]["stage"] == "calendly_sent"
    assert detail_after_inbound.json()["lead"]["automation_paused"] is False
    assert tick.status_code == 200
    assert tick.json()["ai_replies_sent"] == 1
    assert detail_after_tick.json()["lead"]["stage"] == "calendly_sent"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["ai_reply"]
    assert alerts.json()["items"] == []


def test_conversation_bot_escalates_untranscribed_audio_without_guessing(monkeypatch, tmp_path) -> None:
    """Audio/media-only inbound should go to human review without calling the bot."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-audio-handoff",
        phone="+5491333333388",
        full_name="Audio Handoff",
    )
    loom_sent_at = now_utc() - timedelta(minutes=7)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[audio]",
        media_type="audio",
        created_at=now_utc() - timedelta(seconds=45),
    )

    class FailingConversationBot:
        async def aforward(self, **kwargs):
            raise AssertionError("Conversation bot should not be called for untranscribed media")

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FailingConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["human_handoffs"] == 1
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused_reason"] == "untranscribed_media"
    assert pending.json()["messages"] == []


def test_conversation_bot_answers_transcribed_audio(monkeypatch, tmp_path) -> None:
    """A transcribed inbound audio should be handled like normal text."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    data_dir = tmp_path / "data"
    media_file = data_dir / "contadores" / "inbound_media" / "lead-audio-price.ogg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"audio-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(
        contadores_endpoints,
        "transcribe_audio_media",
        lambda media_path, *, mime_type=None: "Me interesa, cuanto cuesta?",
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-audio-transcribed",
        phone="+5491333333366",
        full_name="Audio Transcribed",
    )
    loom_sent_at = now_utc() - timedelta(minutes=7)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        opener_sent_at=loom_sent_at - timedelta(minutes=1),
        first_reply_received_at=loom_sent_at - timedelta(minutes=1),
        loom_sent_at=loom_sent_at,
    )

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            assert kwargs["latest_inbound"] == "Me interesa, cuanto cuesta?"
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text="La inversion es de 599 USD mensuales.",
                classification_label="answered_audio_price",
                reason="Audio transcripto con pregunta de precio.",
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        inbound = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": lead.phone,
                "text": "[audio]",
                "media_type": "audio",
                "media_path": "data/contadores/inbound_media/lead-audio-price.ogg",
                "media_mime_type": "audio/ogg",
                "media_filename": "lead-audio-price.ogg",
            },
        )
        monkeypatch.setattr(
            contadores_endpoints,
            "now_utc",
            lambda: datetime.now(timezone.utc) + timedelta(seconds=45),
        )
        tick = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert inbound.status_code == 200
    assert tick.status_code == 200
    assert tick.json()["ai_replies_sent"] == 1
    messages = detail.json()["messages"]
    assert messages[0]["text"] == "[audio]"
    assert messages[0]["media_type"] == "audio"
    assert messages[0]["media_url"].startswith("/api/contadores/media/")
    assert messages[1]["text"] == "Me interesa, cuanto cuesta?"
    assert messages[1]["media_type"] is None
    assert messages[1]["sequence_step"] == contadores_endpoints.AUDIO_TRANSCRIPT_SEQUENCE_STEP
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused_reason"] == "ai_reply_conversation"
    assert detail.json()["lead"]["manual_reply_status"] == "answered"
    assert pending.json()["messages"][0]["text"] == "La inversion es de 599 USD mensuales."


def test_whatsapp_inbound_image_mirrors_to_existing_workstation_client(monkeypatch, tmp_path) -> None:
    """Images sent by an existing Workstation client should land in that client's media folder."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-live-image",
        phone="+5491333333399",
        full_name="Cliente Imagen",
    )
    workstation = WorkstationClient.create_for_lead(lead)
    source_path = data_dir / "contadores" / "inbound_media" / "lead-photo.jpg"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"lead-photo-bytes")
    payload = {
        "phone": lead.phone,
        "text": "[image]",
        "external_id": "wamid.image.workspace.1",
        "media_type": "image",
        "media_path": "data/contadores/inbound_media/lead-photo.jpg",
        "media_caption": "Foto del estudio",
        "media_mime_type": "image/jpeg",
        "media_filename": "lead photo.jpg",
    }

    with TestClient(app) as client:
        first = client.post("/api/contadores/whatsapp/inbound", json=payload)
        retry = client.post("/api/contadores/whatsapp/inbound", json=payload)

    assert first.status_code == 200
    assert retry.status_code == 200
    media_assets = WorkstationMediaAsset.list_by_client(workstation.id)
    assert len(media_assets) == 1
    assert media_assets[0].title == "Foto del estudio"
    assert media_assets[0].stored_path.startswith("data/workstation/clients/")
    mirrored_path = data_dir / Path(media_assets[0].stored_path).relative_to("data")
    assert mirrored_path.read_bytes() == b"lead-photo-bytes"


def test_workstation_creation_mirrors_existing_whatsapp_images(monkeypatch, tmp_path) -> None:
    """Images already present in the conversation should be copied when a workspace is created."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-workstation-existing-image",
        phone="+5491333333400",
        full_name="Cliente Imagen Previa",
    )
    source_path = data_dir / "contadores" / "inbound_media" / "previous-photo.png"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"previous-photo-bytes")
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[image]",
        media_type="image",
        media_path="data/contadores/inbound_media/previous-photo.png",
        media_caption="Logo actual",
        media_mime_type="image/png",
        media_filename="logo actual.png",
    )

    with TestClient(app) as client:
        created = client.post(f"/api/workstation/clients/from-lead/{lead.id}")

    assert created.status_code == 200
    media_payload = created.json()["media"]
    assert len(media_payload) == 1
    assert media_payload[0]["title"] == "Logo actual"
    mirrored_path = data_dir / Path(media_payload[0]["stored_path"]).relative_to("data")
    assert mirrored_path.read_bytes() == b"previous-photo-bytes"


def test_contadores_reply_after_24h_followup_still_advances_to_offer(monkeypatch, tmp_path) -> None:
    """A reply after the 24-hour reminder should use the usual next stage and offer copy."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(
        enabled=True,
        initial_reply_quiet_seconds=1,
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-opener-followup-reply",
        phone="+5491333000000",
        full_name="Followup Reply",
    )
    opener_sent_at = now_utc() - timedelta(hours=25)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
        opener_sent_at=opener_sent_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text=contadores_endpoints.build_opener_followup_text(),
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step=contadores_endpoints.OPENER_FOLLOWUP_SEQUENCE_STEP,
        created_at=now_utc() - timedelta(minutes=1),
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si, contame.",
        created_at=now_utc() - timedelta(seconds=5),
    )

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["loom_sent"] == 1
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "awaiting_video_reply"
    assert detail.json()["lead"]["raw_stage"] == "awaiting_video_reply"
    assert pending.status_code == 200
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["text_offer"]
    assert pending.json()["messages"][0]["media_type"] is None
    assert pending.json()["messages"][0]["strategy_id"] == "text_offer_599"


def test_contadores_inbound_routing_marks_ambiguous_phone_as_needs_human(monkeypatch, tmp_path) -> None:
    """A shared phone number across active Contadores leads must not auto-route blindly."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-4",
        phone="+5491112345678",
        full_name="Dario Luna",
    )
    other_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-4b",
        phone="+5491112345678",
        full_name="Dario Luna Duplicate",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491112345678",
                "text": "Hola, tengo una duda.",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 200
    assert response.json()["route"] == "ambiguous"
    assert response.json()["reason"] == "ambiguous_phone_match"
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "awaiting_initial_reply"
    assert other_lead.id != lead.id


def test_contadores_inbound_matches_mexico_52_and_521_variants(monkeypatch, tmp_path) -> None:
    """WhatsApp can send Mexico numbers with 521 while sheets often store 52."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-mx",
        phone="+523314184390",
        full_name="Mexico Lead",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "5213314184390",
                "text": "Hola, vengo del anuncio.",
                "external_id": "wamid.mx.1",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 200
    assert response.json()["route"] == "contadores"
    assert response.json()["lead_id"] == lead.id
    assert detail.status_code == 200
    assert detail.json()["lead"]["first_reply_received_at"] is not None
    assert detail.json()["messages"][0]["external_id"] == "wamid.mx.1"


def test_contadores_inbound_external_id_is_idempotent(monkeypatch, tmp_path) -> None:
    """Meta webhook retries should not duplicate an already stored inbound message."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-dedupe",
        phone="+5491112345678",
        full_name="Dedupe Lead",
    )
    payload = {
        "phone": "+5491112345678",
        "text": "Si, me interesa",
        "external_id": "wamid.dedupe.1",
    }

    with TestClient(app) as client:
        first = client.post("/api/contadores/whatsapp/inbound", json=payload)
        second = client.post("/api/contadores/whatsapp/inbound", json=payload)
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["reason"] == "duplicate_external_id"
    assert [message["external_id"] for message in detail.json()["messages"]] == ["wamid.dedupe.1"]


def test_inbound_whatsapp_profile_name_fills_missing_lead_name(monkeypatch, tmp_path) -> None:
    """An existing phone-only lead should pick up the sender's WhatsApp profile name."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-no-name",
        phone="+5491112345601",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491112345601",
                "text": "Hola, soy Ana.",
                "profile_name": "Ana WhatsApp",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 200
    assert response.json()["lead_id"] == lead.id
    assert detail.status_code == 200
    assert detail.json()["lead"]["full_name"] == "Ana WhatsApp"
    assert detail.json()["messages"][0]["text"] == "Hola, soy Ana."


def test_inbound_whatsapp_profile_name_does_not_replace_existing_lead_name(monkeypatch, tmp_path) -> None:
    """Sheet or operator names should win over a later WhatsApp profile name."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-named",
        phone="+5491112345602",
        full_name="Nombre de Sheet",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491112345602",
                "text": "Hola.",
                "profile_name": "Nombre WhatsApp",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 200
    assert response.json()["lead_id"] == lead.id
    assert detail.status_code == 200
    assert detail.json()["lead"]["full_name"] == "Nombre de Sheet"
    assert detail.json()["messages"][0]["text"] == "Hola."


def test_abogados_ctwa_referral_creates_lead_and_reaches_loom(monkeypatch, tmp_path) -> None:
    """A configured Abogados Click-to-WhatsApp ad should start after the opener step."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        initial_reply_quiet_seconds=1,
        strategy_weights={"loom": {"loom_mp4": 100}},
    )
    abogados_funnel = {
        "id": "abogados",
        "label": "Abogados",
        "kind": "campaign",
        "enabled": True,
        "sheet_url": None,
        "sheet_gid": None,
        "sheet_source_filter": None,
        "sheet_poll_seconds": 30,
        "template_language": "es",
        "opener_text": (
            "Hola {nombre}, llenaste el formulario para abogados de {pais} sobre como conseguir "
            "casos redituables a tu whatsapp. es correcto?"
        ),
        "opener_template_name": "abogados_intro_nombre_pais_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "manual_ping_text": "Hola, queria saber si queres que retomemos la conversacion",
        "manual_ping_template_name": None,
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/facundogoiriz/crecimiento",
        "alert_emails": [],
        "whatsapp_referral_source_ids": ["120244283740930010"],
        "initial_reply_quiet_seconds": 1,
        "post_loom_min_seconds": 600,
        "post_loom_quiet_seconds": 30,
        "strategies": [
            {
                "step": "loom",
                "id": "loom_mp4",
                "label": "WhatsApp MP4",
                "weight": 100,
                "delivery": "video",
                "sequence_step": "loom_video",
                "message_text": "Video enviado por WhatsApp.",
                "media_type": "video",
                "media_path": "data/abogados/videos/loom_60_seconds_captions.mp4",
                "media_caption": None,
            }
        ],
    }

    with TestClient(app) as client:
        create_funnel = client.post("/api/funnels", json=abogados_funnel)
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491155555555",
                "text": "Hola, quiero mas info",
                "profile_name": "Rocio WhatsApp",
                "external_id": "wamid.ctwa.1",
                "referral": {
                    "source_type": "ad",
                    "source_id": "120244283740930010",
                    "headline": "Clientes potenciales",
                    "body": "Anuncio de contadores",
                    "ctwa_clid": "clid-123",
                },
            },
        )
        lead_id = response.json()["lead_id"]
        lead = ContadoresLead.get_by_id(lead_id)
        assert lead is not None
        quiet_at = now_utc() - timedelta(seconds=2)
        ContadoresLead.update_flow_state(
            lead.id,
            first_reply_received_at=quiet_at,
            last_inbound_at=quiet_at,
        )
        tick = client.post("/api/contadores/automation/tick?funnel_id=abogados")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert create_funnel.status_code == 200
    assert response.status_code == 200
    assert response.json()["route"] == "abogados"
    assert lead.external_lead_id == "ctwa:abogados:5491155555555"
    assert lead.platform == "whatsapp_ctwa"
    assert lead.funnel_id == "abogados"
    assert lead.full_name == "Rocio WhatsApp"
    assert lead.tags == ["whatsapp_funnel"]
    assert lead.opener_sent_at is None
    assert lead.first_reply_received_at is not None

    assert tick.status_code == 200
    assert tick.json()["opener_sent"] == 0
    assert tick.json()["loom_sent"] == 1

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "awaiting_video_reply"
    assert detail.json()["messages"][0]["text"] == "Hola, quiero mas info"

    assert pending.status_code == 200
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["loom_intro", "loom_video"]


def test_abogados_prefilled_whatsapp_message_routes_without_referral(monkeypatch, tmp_path) -> None:
    """The approved Abogados prefilled WhatsApp text should bypass the General inbox."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_funnel = client.post("/api/funnels", json=build_abogados_test_funnel())
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491155555588",
                "text": "¡Hola! Quiero más información de su propuesta para abogados!",
                "profile_name": "Lucia WhatsApp",
                "external_id": "wamid.prefilled.abogados.1",
            },
        )
        lead_id = response.json()["lead_id"]
        detail = client.get(f"/api/contadores/leads/{lead_id}")
        general_list = client.get("/api/contadores/leads?funnel_id=general")

    lead = ContadoresLead.get_by_id(lead_id)

    assert create_funnel.status_code == 200
    assert response.status_code == 200
    assert response.json()["route"] == "abogados"
    assert lead is not None
    assert lead.external_lead_id == "ctwa:abogados:5491155555588"
    assert lead.platform == "whatsapp_ctwa"
    assert lead.funnel_id == "abogados"
    assert lead.full_name == "Lucia WhatsApp"
    assert lead.first_reply_received_at is not None

    assert detail.status_code == 200
    assert detail.json()["messages"][0]["external_id"] == "wamid.prefilled.abogados.1"
    assert general_list.status_code == 200
    assert general_list.json()["leads"] == []


def test_unmatched_whatsapp_inbound_creates_general_inbox_lead(monkeypatch, tmp_path) -> None:
    """Inbound WhatsApp without a matching reply/referral should land in the General inbox."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491155555599",
                "text": "Hola, quiero consultar algo",
                "profile_name": "Camila WhatsApp",
                "external_id": "wamid.general.1",
            },
        )
        lead_id = response.json()["lead_id"]
        detail = client.get(f"/api/contadores/leads/{lead_id}")
        general_list = client.get("/api/contadores/leads?funnel_id=general")
        tick = client.post("/api/contadores/automation/tick?funnel_id=general")

    assert response.status_code == 200
    assert response.json()["route"] == "general"
    assert detail.status_code == 200
    assert detail.json()["lead"]["funnel_id"] == "general"
    assert detail.json()["lead"]["full_name"] == "Camila WhatsApp"
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["tags"] == ["whatsapp"]
    assert detail.json()["messages"][0]["external_id"] == "wamid.general.1"
    assert general_list.status_code == 200
    assert [item["id"] for item in general_list.json()["leads"]] == [lead_id]
    assert tick.status_code == 200
    assert tick.json()["status"] == "inbox"


def test_general_inbox_lead_can_move_to_campaign_stage(monkeypatch, tmp_path) -> None:
    """Operators can route a General inbox chat into an existing campaign and phase."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        inbound = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": "+5491155555501",
                "text": "Soy contador y quiero informacion",
            },
        )
        lead_id = inbound.json()["lead_id"]
        move_response = client.post(
            f"/api/contadores/leads/{lead_id}/move",
            json={"funnel_id": "contadores", "stage": "awaiting_initial_reply"},
        )
        contadores_list = client.get("/api/contadores/leads?funnel_id=contadores")

    assert inbound.status_code == 200
    assert move_response.status_code == 200
    assert move_response.json()["funnel_id"] == "contadores"
    assert move_response.json()["stage"] == "awaiting_initial_reply"
    assert move_response.json()["automation_paused"] is False
    assert [item["id"] for item in contadores_list.json()["leads"]] == [lead_id]


def test_contadores_lead_tags_update_and_filter_with_stage(monkeypatch, tmp_path) -> None:
    """Operator tags should combine with the normal stage filters."""
    configure_contadores_db(monkeypatch, tmp_path)
    first = ContadoresLead.upsert(
        external_lead_id="tagged-form-1",
        phone="+5491155555511",
        full_name="Tagged One",
        tags=["form"],
    )
    second = ContadoresLead.upsert(
        external_lead_id="tagged-form-2",
        phone="+5491155555512",
        full_name="Tagged Two",
        tags=["form"],
    )

    with TestClient(app) as client:
        update_response = client.put(
            f"/api/contadores/leads/{first.id}/tags",
            json={"tags": ["form", "prioridad"]},
        )
        filtered_response = client.get(
            "/api/contadores/leads?stage=awaiting_initial_reply&tag=prioridad"
        )

    assert update_response.status_code == 200
    assert update_response.json()["tags"] == ["form", "prioridad"]
    assert filtered_response.status_code == 200
    payload = filtered_response.json()
    assert payload["tag_options"] == ["form", "prioridad"]
    assert [item["id"] for item in payload["leads"]] == [first.id]
    assert payload["metrics"]["total"] == 1
    assert second.id != first.id


def test_bulk_action_replaces_selected_lead_tags(monkeypatch, tmp_path) -> None:
    """Operators should change tags only through selected batch leads."""
    configure_contadores_db(monkeypatch, tmp_path)
    first = ContadoresLead.upsert(
        external_lead_id="bulk-tags-1",
        phone="+5491888888831",
        full_name="Tagged Bulk One",
        tags=["form"],
    )
    second = ContadoresLead.upsert(
        external_lead_id="bulk-tags-2",
        phone="+5491888888832",
        full_name="Tagged Bulk Two",
        tags=["whatsapp"],
    )
    untouched = ContadoresLead.upsert(
        external_lead_id="bulk-tags-3",
        phone="+5491888888833",
        full_name="Tagged Bulk Three",
        tags=["form"],
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/leads/bulk-action",
            json={
                "lead_ids": [first.id, second.id],
                "action": "set-tags",
                "tags": ["prioridad", "whatsapp_funnel", "prioridad"],
            },
        )
        filtered_response = client.get("/api/contadores/leads?tag=whatsapp_funnel")

    assert response.status_code == 200
    payload = response.json()
    assert payload["succeeded"] == 2
    assert payload["failed"] == 0
    assert payload["queued_message_ids"] == []
    assert [item["lead"]["tags"] for item in payload["results"]] == [
        ["prioridad", "whatsapp_funnel"],
        ["prioridad", "whatsapp_funnel"],
    ]
    assert ContadoresLead.get_by_id(untouched.id).tags == ["form"]
    assert [item["id"] for item in filtered_response.json()["leads"]] == [second.id, first.id]


def test_contadores_detail_keeps_manual_stage_with_calendly_milestone(monkeypatch, tmp_path) -> None:
    """Calendly milestones should not hide a current manual handoff."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5",
        phone="+5491444444444",
        full_name="Lara Costa",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        calendly_sent_at=calendly_sent_at,
    )

    with TestClient(app) as client:
        response = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 200
    assert response.json()["lead"]["stage"] == "needs_human"
    assert response.json()["lead"]["raw_stage"] == "needs_human"


def test_contadores_send_calendly_keeps_manual_handoff(monkeypatch, tmp_path) -> None:
    """Manual Calendly send should keep the lead in Manual while marking the milestone."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, calendly_base_url="https://calendly.com/test/contadores")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5b",
        phone="+5491444444400",
        full_name="Lara Calendly",
    )
    add_recent_inbound(lead.id)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
        needs_human_notified_at=now_utc() - timedelta(minutes=1),
    )

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-calendly")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lead"]["stage"] == "needs_human"
    assert payload["lead"]["raw_stage"] == "needs_human"
    assert payload["lead"]["automation_paused"] is True
    assert payload["lead"]["automation_paused_reason"] == "manual_calendly_send"
    assert payload["lead"]["calendly_sent_at"] is not None
    assert payload["lead"]["meeting_sent_at"] == payload["lead"]["calendly_sent_at"]
    assert payload["queued_message_ids"] == [2, 3]

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["calendly_url"] == "https://calendly.com/test/contadores"
    assert detail.json()["lead"]["meeting_url"] == "https://calendly.com/test/contadores"
    assert "calendly_tracking_token" not in detail.json()["lead"]
    assert detail.json()["lead"]["automation_paused"] is True
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_intro", "calendly_url"]
    assert pending.json()["messages"][1]["text"] == "https://calendly.com/test/contadores"


def test_contadores_send_calendly_requires_configured_url(monkeypatch, tmp_path) -> None:
    """A portable empty seed should not enqueue a blank Calendly message."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5b-missing-calendly",
        phone="+5491444444403",
        full_name="Missing Calendly",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-calendly")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 400
    assert response.json()["detail"] == "Calendly URL is not configured for this funnel."
    assert pending.json()["messages"] == []


def test_contadores_send_calendly_link_only_marks_calendly_sent(monkeypatch, tmp_path) -> None:
    """Operators can send only the Calendly URL without the intro text."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, calendly_base_url="https://calendly.com/test/contadores")
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5b-link",
        phone="+5491444444402",
        full_name="Lara Calendly Link",
    )
    add_recent_inbound(lead.id)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
        needs_human_notified_at=now_utc() - timedelta(minutes=1),
    )

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-calendly-link")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lead"]["stage"] == "needs_human"
    assert payload["lead"]["automation_paused"] is True
    assert payload["lead"]["automation_paused_reason"] == "manual_calendly_send"
    assert payload["lead"]["calendly_sent_at"] is not None
    assert payload["queued_message_ids"] == [2]

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["calendly_url"] == "https://calendly.com/test/contadores"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_url"]
    assert pending.json()["messages"][0]["text"] == "https://calendly.com/test/contadores"


def test_calendly_webhook_records_scheduled_meeting_without_conversion(monkeypatch, tmp_path) -> None:
    """Calendly scheduled is a meeting milestone; it is not a converted client."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-calendly-scheduled",
        phone="+5491444444404",
        full_name="Scheduled Meeting",
    )
    scheduled_at = now_utc()

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/calendly/webhook",
            json={
                "token": lead.calendly_tracking_token,
                "event_type": "invitee.created",
                "occurred_at": scheduled_at.isoformat(),
            },
        )
        meeting_response = client.get("/api/contadores/leads?stage=calendly_sent")
        converted_response = client.get("/api/contadores/leads?converted=true")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "calendly_sent"
    assert payload["pipeline_stage"] == "meeting_sent"
    assert payload["queue_state"] == "paused"
    assert payload["attention_state"] == "paused"
    assert payload["meeting_scheduled_at"] is not None
    assert payload["meeting_scheduled_at"] != payload["converted_at"]
    assert payload["converted_at"] is None
    assert payload["booked_at"] is None
    assert payload["conversion_type"] is None
    assert payload["automation_paused"] is True
    assert payload["automation_paused_reason"] == "meeting_scheduled"

    assert meeting_response.status_code == 200
    assert meeting_response.json()["metrics"]["meeting_sent"] == 1
    assert meeting_response.json()["metrics"]["converted"] == 0
    assert [item["id"] for item in meeting_response.json()["leads"]] == [lead.id]

    assert converted_response.status_code == 200
    assert converted_response.json()["leads"] == []


def test_contadores_post_calendly_inbound_does_not_immediately_handoff(monkeypatch, tmp_path) -> None:
    """A new inbound after Calendly should remain eligible for the conversation bot."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5c",
        phone="+5491444444401",
        full_name="Lara Reply",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=calendly_sent_at,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": lead.phone,
                "text": "Tengo una duda antes de agendar.",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        alerts = client.get("/api/contadores/alerts/pending")

    assert response.status_code == 200
    assert response.json()["route"] == "contadores"

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "calendly_sent"
    assert detail.json()["lead"]["raw_stage"] == "calendly_sent"
    assert detail.json()["lead"]["automation_paused"] is False
    assert detail.json()["lead"]["automation_paused_reason"] is None
    assert detail.json()["lead"]["last_classification_label"] is None

    assert alerts.status_code == 200
    assert alerts.json()["items"] == []


def test_contadores_inbound_audio_payload_is_persisted_and_playable(monkeypatch, tmp_path) -> None:
    """Audio sent by leads should be stored on the message and exposed through the media endpoint."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    media_file = data_dir / "contadores" / "inbound_media" / "lead-audio.ogg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"audio-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(
        contadores_endpoints,
        "transcribe_audio_media",
        lambda media_path, *, mime_type=None: "Me interesa, cuanto cuesta?",
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-media",
        phone="+5491444444499",
        full_name="Media Reply",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": lead.phone,
                "text": "[audio]",
                "external_id": "wamid.audio.1",
                "media_id": "media-audio-1",
                "media_type": "audio",
                "media_path": "data/contadores/inbound_media/lead-audio.ogg",
                "media_mime_type": "audio/ogg",
                "media_filename": "lead-audio.ogg",
                "media_sha256": "sha-audio",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        messages = detail.json()["messages"]
        audio_message = messages[0]
        transcript_message = messages[1]
        media = client.get(audio_message["media_url"])

    assert response.status_code == 200
    assert response.json()["route"] == "contadores"

    assert detail.status_code == 200
    assert audio_message["text"] == "[audio]"
    assert audio_message["external_id"] == "wamid.audio.1"
    assert audio_message["media_type"] == "audio"
    assert audio_message["media_path"] == "data/contadores/inbound_media/lead-audio.ogg"
    assert audio_message["media_mime_type"] == "audio/ogg"
    assert audio_message["media_filename"] == "lead-audio.ogg"
    assert audio_message["media_id"] == "media-audio-1"
    assert audio_message["media_url"].startswith("/api/contadores/media/")
    assert transcript_message["text"] == "Me interesa, cuanto cuesta?"
    assert transcript_message["media_type"] is None
    assert transcript_message["media_path"] is None
    assert transcript_message["media_url"] is None
    assert transcript_message["sequence_step"] == contadores_endpoints.AUDIO_TRANSCRIPT_SEQUENCE_STEP
    assert media.status_code == 200
    assert media.content == b"audio-bytes"
    assert media.headers["content-type"] == "audio/ogg"


def test_contadores_inbound_audio_transcription_failure_keeps_media_playable(monkeypatch, tmp_path) -> None:
    """If audio transcription fails, keep the audio metadata and placeholder text."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    media_file = data_dir / "contadores" / "inbound_media" / "lead-audio-fail.ogg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"audio-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)

    def fail_transcription(media_path, *, mime_type=None):
        del media_path
        del mime_type
        raise AudioTranscriptionError("bad audio")

    monkeypatch.setattr(contadores_endpoints, "transcribe_audio_media", fail_transcription)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-media-fail",
        phone="+5491444444488",
        full_name="Media Fail",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/whatsapp/inbound",
            json={
                "phone": lead.phone,
                "text": "[audio]",
                "external_id": "wamid.audio.fail",
                "media_type": "audio",
                "media_path": "data/contadores/inbound_media/lead-audio-fail.ogg",
                "media_mime_type": "audio/ogg",
                "media_filename": "lead-audio-fail.ogg",
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        message = detail.json()["messages"][0]
        media = client.get(message["media_url"])

    assert response.status_code == 200
    assert message["text"] == "[audio]"
    assert message["media_type"] == "audio"
    assert message["media_url"].startswith("/api/contadores/media/")
    assert media.status_code == 200
    assert media.content == b"audio-bytes"


def test_contadores_outbound_video_uses_stable_media_path_url(monkeypatch, tmp_path) -> None:
    """Repeated outbound strategy videos should point at one shared media URL."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    media_file = data_dir / "contadores" / "videos" / "strategy-video.mp4"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"video-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-video",
        phone="+5491444444488",
        full_name="Video Reply",
    )
    media_path = "data/contadores/videos/strategy-video.mp4"
    first = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Video de explicacion enviado por WhatsApp.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        media_type="video",
        media_path=media_path,
    )
    second = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Video de explicacion enviado por WhatsApp.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        media_type="video",
        media_path=media_path,
    )

    with TestClient(app) as client:
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        messages = detail.json()["messages"]
        media = client.get(messages[0]["media_url"])

    assert detail.status_code == 200
    assert messages[0]["id"] == first.id
    assert messages[1]["id"] == second.id
    assert messages[0]["media_url"] == messages[1]["media_url"]
    assert messages[0]["media_url"].startswith("/api/contadores/media/")
    assert media.status_code == 200
    assert media.content == b"video-bytes"
    assert media.headers["content-type"] == "video/mp4"
    assert media.headers["content-disposition"].startswith("inline;")


def test_contadores_manual_reply_can_be_marked_answered(monkeypatch, tmp_path) -> None:
    """Operators must be able to clear a manual reply cue without sending another message."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5c2",
        phone="+5491444444411",
        full_name="Marcelo Martino",
    )
    first_message_at = now_utc() - timedelta(minutes=3)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Te mande la info.",
        created_at=first_message_at,
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="[reaction: thumbs_up]",
        created_at=first_message_at + timedelta(minutes=1),
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="post_calendly_inbound",
    )

    with TestClient(app) as client:
        detail_before = client.get(f"/api/contadores/leads/{lead.id}")
        needs_reply_response = client.get("/api/contadores/leads?manual_reply_status=needs_reply")
        answered_before_response = client.get("/api/contadores/leads?manual_reply_status=answered")
        mark_response = client.post(f"/api/contadores/leads/{lead.id}/actions/mark-answered")
        manual_response = client.get("/api/contadores/leads?needs_human=true")
        answered_after_response = client.get("/api/contadores/leads?manual_reply_status=answered")
        detail_after = client.get(f"/api/contadores/leads/{lead.id}")
        alerts_after = client.get("/api/contadores/alerts/pending")

        ContadoresMessage.add(
            lead_id=lead.id,
            from_me=False,
            text="Ahora si, tengo una pregunta.",
            created_at=now_utc() + timedelta(seconds=1),
        )
        detail_after_new_reply = client.get(f"/api/contadores/leads/{lead.id}")
        alerts_after_new_reply = client.get("/api/contadores/alerts/pending")

    assert detail_before.status_code == 200
    assert detail_before.json()["lead"]["manual_reply_status"] == "needs_reply"
    assert needs_reply_response.status_code == 200
    assert [item["id"] for item in needs_reply_response.json()["leads"]] == [lead.id]
    assert answered_before_response.status_code == 200
    assert answered_before_response.json()["leads"] == []

    assert mark_response.status_code == 200
    marked_payload = mark_response.json()["lead"]
    assert marked_payload["stage"] == "needs_human"
    assert marked_payload["manual_reply_status"] == "answered"
    assert marked_payload["manual_reply_handled_at"] is not None

    assert manual_response.status_code == 200
    assert manual_response.json()["metrics"]["needs_human"] == 1
    assert manual_response.json()["leads"][0]["manual_reply_status"] == "answered"
    assert answered_after_response.status_code == 200
    assert [item["id"] for item in answered_after_response.json()["leads"]] == [lead.id]

    assert detail_after.status_code == 200
    assert detail_after.json()["lead"]["manual_reply_status"] == "answered"
    assert alerts_after.status_code == 200
    assert alerts_after.json()["items"] == []

    assert detail_after_new_reply.status_code == 200
    assert detail_after_new_reply.json()["lead"]["manual_reply_status"] == "needs_reply"
    assert alerts_after_new_reply.status_code == 200
    assert [item["lead_id"] for item in alerts_after_new_reply.json()["items"]] == [lead.id]


def test_manual_attention_counts_endpoint_groups_by_funnel(monkeypatch, tmp_path) -> None:
    """The nav badge count should include only manual handoffs awaiting an operator answer."""
    configure_contadores_db(monkeypatch, tmp_path)
    first_message_at = now_utc()

    contadores_lead = ContadoresLead.upsert(
        external_lead_id="needs-reply-contadores",
        phone="+5491111111111",
        full_name="Needs Contadores",
    )
    ContadoresLead.update_flow_state(
        contadores_lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="test",
    )
    ContadoresMessage.add(
        lead_id=contadores_lead.id,
        from_me=False,
        text="Necesito una respuesta",
        created_at=first_message_at,
    )

    answered_lead = ContadoresLead.upsert(
        external_lead_id="answered-contadores",
        phone="+5491111111112",
        full_name="Answered Contadores",
    )
    ContadoresLead.update_flow_state(
        answered_lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="test",
    )
    ContadoresMessage.add(
        lead_id=answered_lead.id,
        from_me=False,
        text="Ya respondieron",
        created_at=first_message_at,
    )
    ContadoresLead.update_flow_state(
        answered_lead.id,
        manual_reply_handled_at=first_message_at + timedelta(minutes=1),
    )

    general_lead = ContadoresLead.upsert(
        funnel_id="general",
        external_lead_id="needs-reply-general",
        phone="+5491111111113",
        full_name="Needs General",
    )
    ContadoresLead.update_flow_state(
        general_lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="test",
    )
    ContadoresMessage.add(
        lead_id=general_lead.id,
        from_me=False,
        text="Necesito respuesta en general",
        created_at=first_message_at,
    )

    with TestClient(app) as client:
        response = client.get("/api/contadores/manual-attention-counts")

    assert response.status_code == 200
    assert response.json()["counts"] == {"contadores": 1, "abogados": 0, "general": 1}


def test_contadores_resume_after_post_calendly_handoff_restores_calendly_sent(monkeypatch, tmp_path) -> None:
    """Resume automation should return post-Calendly handoffs to the Calendly stage."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5d",
        phone="+5491444444402",
        full_name="Lara Resume",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        calendly_sent_at=calendly_sent_at,
        last_inbound_at=calendly_sent_at + timedelta(minutes=1),
        automation_paused=True,
        automation_paused_reason="post_calendly_inbound",
    )

    with TestClient(app) as client:
        response = client.post(f"/api/contadores/leads/{lead.id}/resume-automation")

    assert response.status_code == 200
    assert response.json()["lead"]["stage"] == "calendly_sent"
    assert response.json()["lead"]["raw_stage"] == "calendly_sent"
    assert response.json()["lead"]["automation_paused"] is False
    assert response.json()["lead"]["automation_paused_reason"] is None


def test_contadores_close_and_reopen_restore_previous_stage(monkeypatch, tmp_path) -> None:
    """Closing a lead must be reversible back to the exact prior stage."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5e",
        phone="+5491444444403",
        full_name="Lara Closed",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=2)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=calendly_sent_at,
    )

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        closed_overview = client.get("/api/contadores/leads?stage=closed")
        reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/reopen")

    assert close_response.status_code == 200
    closed_payload = close_response.json()["lead"]
    assert closed_payload["stage"] == "closed"
    assert closed_payload["raw_stage"] == "closed"
    assert closed_payload["stage_before_closed"] == "calendly_sent"
    assert closed_payload["closed_at"] is not None

    assert closed_overview.status_code == 200
    assert closed_overview.json()["metrics"]["closed"] == 1
    assert [item["id"] for item in closed_overview.json()["leads"]] == [lead.id]

    assert reopen_response.status_code == 200
    reopened_payload = reopen_response.json()["lead"]
    assert reopened_payload["stage"] == "calendly_sent"
    assert reopened_payload["raw_stage"] == "calendly_sent"
    assert reopened_payload["stage_before_closed"] is None
    assert reopened_payload["closed_at"] is None


def test_contadores_closed_lead_stays_out_of_automation_until_reopened(monkeypatch, tmp_path) -> None:
    """Closed leads must stay out of the bot loop until an operator reopens them."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5f",
        phone="+5491444444404",
        full_name="Lara Hold",
    )

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        tick_while_closed = client.post("/api/contadores/automation/tick")
        pending_while_closed = client.get("/api/contadores/messages/pending-delivery")
        reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/reopen")
        tick_after_reopen = client.post("/api/contadores/automation/tick")
        pending_after_reopen = client.get("/api/contadores/messages/pending-delivery")

    assert close_response.status_code == 200
    assert tick_while_closed.status_code == 200
    assert tick_while_closed.json()["opener_sent"] == 0
    assert pending_while_closed.status_code == 200
    assert pending_while_closed.json()["messages"] == []

    assert reopen_response.status_code == 200
    assert tick_after_reopen.status_code == 200
    assert tick_after_reopen.json()["opener_sent"] == 1
    assert [item["sequence_step"] for item in pending_after_reopen.json()["messages"]] == ["opener"]


def test_contadores_closed_lead_hides_already_queued_pending_delivery(monkeypatch, tmp_path) -> None:
    """Already queued WhatsApp messages must not dispatch while the lead is closed."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5f-pending",
        phone="+5491444444406",
        full_name="Lara Pending Closed",
    )

    with TestClient(app) as client:
        ping_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        pending_before_close = client.get("/api/contadores/messages/pending-delivery")
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        pending_while_closed = client.get("/api/contadores/messages/pending-delivery")
        reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/reopen")
        pending_after_reopen = client.get("/api/contadores/messages/pending-delivery")

    assert ping_response.status_code == 200
    assert pending_before_close.status_code == 200
    assert [item["lead_id"] for item in pending_before_close.json()["messages"]] == [lead.id]
    assert close_response.status_code == 200
    assert pending_while_closed.status_code == 200
    assert pending_while_closed.json()["messages"] == []
    assert reopen_response.status_code == 200
    assert [item["lead_id"] for item in pending_after_reopen.json()["messages"]] == [lead.id]


def test_contadores_reopen_restores_manual_pause_state(monkeypatch, tmp_path) -> None:
    """Reopening should keep the prior manual-pause context intact."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5g",
        phone="+5491444444405",
        full_name="Lara Manual Pause",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
    )

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        reopen_response = client.post(f"/api/contadores/leads/{lead.id}/actions/reopen")

    assert close_response.status_code == 200
    assert reopen_response.status_code == 200
    reopened_payload = reopen_response.json()["lead"]
    assert reopened_payload["stage"] == "needs_human"
    assert reopened_payload["raw_stage"] == "needs_human"
    assert reopened_payload["automation_paused"] is True
    assert reopened_payload["automation_paused_reason"] == "manual_message"


def test_contadores_overview_and_alerts_use_effective_stage(monkeypatch, tmp_path) -> None:
    """Booked milestones should remove stale needs_human from operator lists and alerts."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-6",
        phone="+5491555555555",
        full_name="Nora Silva",
    )
    booked_at = now_utc() - timedelta(minutes=1)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        booked_at=booked_at,
    )

    with TestClient(app) as client:
        booked_response = client.get("/api/contadores/leads?stage=booked&booked=true")
        converted_response = client.get("/api/contadores/leads?converted=true")
        needs_human_response = client.get("/api/contadores/leads?needs_human=true")
        alerts_response = client.get("/api/contadores/alerts/pending")

    assert booked_response.status_code == 200
    assert booked_response.json()["metrics"]["booked"] == 1
    assert booked_response.json()["metrics"]["converted"] == 1
    assert booked_response.json()["metrics"]["pipeline_converted"] == 1
    assert [item["id"] for item in booked_response.json()["leads"]] == [lead.id]
    assert booked_response.json()["leads"][0]["stage"] == "converted"
    assert booked_response.json()["leads"][0]["raw_stage"] == "needs_human"
    assert booked_response.json()["leads"][0]["pipeline_stage"] == "converted"
    assert booked_response.json()["leads"][0]["terminal_state"] == "open"
    assert booked_response.json()["leads"][0]["attention_state"] == "converted"
    assert booked_response.json()["leads"][0]["converted_at"] == booked_response.json()["leads"][0]["booked_at"]

    assert converted_response.status_code == 200
    assert [item["id"] for item in converted_response.json()["leads"]] == [lead.id]

    assert needs_human_response.status_code == 200
    assert needs_human_response.json()["metrics"]["needs_human"] == 0
    assert needs_human_response.json()["leads"] == []

    assert alerts_response.status_code == 200
    assert alerts_response.json()["items"] == []


def test_contadores_leads_converted_and_booked_alias_must_match(monkeypatch, tmp_path) -> None:
    """The legacy booked query alias should match the canonical converted filter."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-converted-booked-alias",
        phone="+5491555555571",
        full_name="Converted Alias",
    )
    ContadoresLead.update_flow_state(lead.id, booked_at=now_utc())
    open_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-open-booked-alias",
        phone="+5491555555572",
        full_name="Open Alias",
    )

    with TestClient(app) as client:
        converted_alias_response = client.get("/api/contadores/leads?converted=true&booked=true")
        open_alias_response = client.get("/api/contadores/leads?converted=false&booked=false")

    assert converted_alias_response.status_code == 200
    assert [item["id"] for item in converted_alias_response.json()["leads"]] == [lead.id]

    assert open_alias_response.status_code == 200
    assert [item["id"] for item in open_alias_response.json()["leads"]] == [open_lead.id]


def test_contadores_leads_converted_and_booked_conflict_rejected(monkeypatch, tmp_path) -> None:
    """Contradictory converted/booked filters should fail instead of silently picking one."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresLead.upsert(
        external_lead_id="sheet-row-converted-booked-conflict",
        phone="+5491555555573",
        full_name="Converted Conflict",
    )

    with TestClient(app) as client:
        converted_true_conflict = client.get("/api/contadores/leads?converted=true&booked=false")
        converted_false_conflict = client.get("/api/contadores/leads?converted=false&booked=true")

    assert converted_true_conflict.status_code == 400
    assert "booked is a legacy alias" in converted_true_conflict.json()["detail"]
    assert converted_false_conflict.status_code == 400
    assert "booked is a legacy alias" in converted_false_conflict.json()["detail"]


def test_contadores_leads_stage_booked_alias_rejects_conflicting_canonical_filters(monkeypatch, tmp_path) -> None:
    """The old stage=booked alias should fail loudly when it disagrees with canonical state filters."""
    configure_contadores_db(monkeypatch, tmp_path)
    converted_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stage-booked-alias-conflict",
        phone="+5491555555574",
        full_name="Stage Booked Alias",
    )
    ContadoresLead.update_flow_state(converted_lead.id, booked_at=now_utc())

    with TestClient(app) as client:
        stage_alias_response = client.get("/api/contadores/leads?stage=booked")
        converted_false_conflict = client.get("/api/contadores/leads?stage=booked&converted=false")
        pipeline_conflict = client.get("/api/contadores/leads?stage=booked&pipeline_stage=meeting_sent")

    assert stage_alias_response.status_code == 200
    assert [item["id"] for item in stage_alias_response.json()["leads"]] == [converted_lead.id]
    assert stage_alias_response.json()["leads"][0]["pipeline_stage"] == "converted"

    assert converted_false_conflict.status_code == 400
    assert "stage=booked is a legacy alias" in converted_false_conflict.json()["detail"]
    assert pipeline_conflict.status_code == 400
    assert "stage=booked is a legacy alias" in pipeline_conflict.json()["detail"]


def test_contadores_calendly_bucket_includes_manual_post_calendly_leads(monkeypatch, tmp_path) -> None:
    """Calendly metrics should include leads that reached Calendly even if they later need manual follow-up."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-6b",
        phone="+5491555555556",
        full_name="Manual After Calendly",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=3)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        calendly_sent_at=calendly_sent_at,
        last_inbound_at=calendly_sent_at + timedelta(minutes=1),
        automation_paused=True,
        automation_paused_reason="post_calendly_inbound",
    )

    with TestClient(app) as client:
        calendly_response = client.get("/api/contadores/leads?stage=calendly_sent")
        manual_response = client.get("/api/contadores/leads?needs_human=true")

    assert calendly_response.status_code == 200
    assert calendly_response.json()["metrics"]["calendly_sent"] == 1
    assert calendly_response.json()["metrics"]["meeting_sent"] == 1
    assert calendly_response.json()["metrics"]["pipeline_meeting_sent"] == 1
    assert calendly_response.json()["metrics"]["attention_needs_reply"] == 1
    assert [item["id"] for item in calendly_response.json()["leads"]] == [lead.id]
    assert calendly_response.json()["leads"][0]["stage"] == "needs_human"
    assert calendly_response.json()["leads"][0]["raw_stage"] == "needs_human"
    assert calendly_response.json()["leads"][0]["pipeline_stage"] == "meeting_sent"
    assert calendly_response.json()["leads"][0]["queue_state"] == "operator"
    assert calendly_response.json()["leads"][0]["attention_state"] == "needs_reply"

    assert manual_response.status_code == 200
    assert manual_response.json()["metrics"]["needs_human"] == 1
    assert [item["id"] for item in manual_response.json()["leads"]] == [lead.id]


def test_contadores_stage_filter_does_not_recalculate_pipeline_metrics(monkeypatch, tmp_path) -> None:
    """Pipeline counts should stay independent when the operator clicks a stage pill."""
    configure_contadores_db(monkeypatch, tmp_path)
    opener_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stage-opener",
        phone="+5491555555560",
        full_name="Opener Count",
    )
    loom_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stage-loom",
        phone="+5491555555561",
        full_name="Loom Count",
    )
    calendly_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-stage-calendly",
        phone="+5491555555562",
        full_name="Calendly Count",
    )
    ContadoresLead.update_flow_state(
        opener_lead.id,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
    )
    ContadoresLead.update_flow_state(
        loom_lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        loom_sent_at=now_utc(),
    )
    ContadoresLead.update_flow_state(
        calendly_lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )

    with TestClient(app) as client:
        response = client.get("/api/contadores/leads?stage=calendly_sent")
        pipeline_response = client.get("/api/contadores/leads?pipeline_stage=meeting_sent")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["leads"]] == [calendly_lead.id]
    assert payload["metrics"]["total"] == 3
    assert payload["metrics"]["awaiting_initial_reply"] == 1
    assert payload["metrics"]["awaiting_video_reply"] == 1
    assert payload["metrics"]["calendly_sent"] == 1
    assert payload["metrics"]["pipeline_new"] == 1
    assert payload["metrics"]["pipeline_offer_sent"] == 1
    assert payload["metrics"]["pipeline_meeting_sent"] == 1

    assert pipeline_response.status_code == 200
    assert [item["id"] for item in pipeline_response.json()["leads"]] == [calendly_lead.id]
    assert pipeline_response.json()["leads"][0]["pipeline_stage"] == "meeting_sent"


def test_contadores_leads_sort_by_latest_interaction(monkeypatch, tmp_path) -> None:
    """Newest list rows should use the latest inbound or outbound message timestamp."""
    configure_contadores_db(monkeypatch, tmp_path)
    base_time = now_utc()
    outbound_newer_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-newer-outbound",
        phone="+5491555555563",
        full_name="Newer Outbound",
    )
    inbound_newer_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-newer-inbound",
        phone="+5491555555564",
        full_name="Newer Inbound",
    )
    ContadoresLead.update_flow_state(
        outbound_newer_lead.id,
        last_inbound_at=base_time - timedelta(days=3),
        last_outbound_at=base_time,
    )
    ContadoresLead.update_flow_state(
        inbound_newer_lead.id,
        last_inbound_at=base_time - timedelta(hours=1),
        last_outbound_at=base_time - timedelta(days=2),
    )

    with TestClient(app) as client:
        response = client.get("/api/contadores/leads")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["leads"]] == [
        outbound_newer_lead.id,
        inbound_newer_lead.id,
    ]


def test_contadores_leads_filter_by_prior_offer_strategy_inside_calendly(monkeypatch, tmp_path) -> None:
    """Operators should filter meeting leads by the offer strategy assigned earlier."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(enabled=True)
    unassigned_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-loom-link-filter",
        phone="+5491555555563",
        full_name="Unassigned Lead",
    )
    offer_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-text-offer-filter",
        phone="+5491555555564",
        full_name="Offer Lead",
    )
    add_recent_inbound(offer_lead.id)
    contadores_endpoints.send_loom_sequence(lead=offer_lead, config=config, strategy_id="text_offer_599")
    ContadoresLead.update_flow_state(
        unassigned_lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )
    ContadoresLead.update_flow_state(
        offer_lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/contadores/leads?stage=calendly_sent&strategy_step=loom&strategy_id=text_offer_599"
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["leads"]] == [offer_lead.id]
    assert payload["metrics"]["total"] == 1
    assert payload["metrics"]["calendly_sent"] == 1
    assert payload["leads"][0]["strategy_assignments"][0]["strategy_id"] == "text_offer_599"


def test_contadores_delete_lead_removes_messages(monkeypatch, tmp_path) -> None:
    """Deleting a Contadores lead should remove the lead and its stored messages."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-7",
        phone="+5491666666666",
        full_name="Borrar Chat",
    )
    contadores_endpoints.send_opener_sequence(lead=lead)

    with TestClient(app) as client:
        detail_before = client.get(f"/api/contadores/leads/{lead.id}")
        delete_response = client.delete(f"/api/contadores/leads/{lead.id}")
        detail_after = client.get(f"/api/contadores/leads/{lead.id}")
        leads_response = client.get("/api/contadores/leads")

    assert detail_before.status_code == 200
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "lead_id": lead.id}
    assert detail_after.status_code == 404
    assert [item["id"] for item in leads_response.json()["leads"]] == []


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


def test_manual_workstation_codex_start_requires_enabled_lead(monkeypatch, tmp_path) -> None:
    """Workstation buttons should not queue Codex work when the lead switch is off."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(database_module, "DATA_DIR", tmp_path / "data")
    workstation_endpoints.manual_solo_page_work_client_ids.clear()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-workstation-codex-disabled",
        phone="+5491777777712",
        full_name="Codex Disabled Workstation",
    )
    lead = ContadoresLead.set_codex_enabled(lead.id, enabled=False) or lead
    workstation = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/workstation/clients/{workstation.id}/solo-page/work",
            json={"prompt": "Hacer la pagina."},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Codex is disabled for this lead."
    assert workstation_endpoints.manual_solo_page_work_client_ids == set()


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
        assert {"profile.json", "notes.txt", "conversation.txt"}.issubset(names)
        assert f"media/{upload_response.json()['stored_filename']}" in names


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
    workstation_endpoints.professional_photo_jobs.clear()

    async def fake_run_codex_with_context(prompt: str, **kwargs) -> SimpleNamespace:
        output_marker = "Required output path:\n"
        output_path = prompt.split(output_marker, 1)[1].splitlines()[0].strip()
        Path(output_path).write_bytes(b"generated-job-jpg")
        return SimpleNamespace(final_response=f"created {output_path}", items=[])

    monkeypatch.setattr(workstation_endpoints, "run_codex_with_context", fake_run_codex_with_context)
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

        status_response = start_response
        for _ in range(20):
            status_response = client.get(f"/api/workstation/clients/{client_id}/professional-photo/jobs/{job_id}")
            if status_response.json()["status"] == "completed":
                break
            time.sleep(0.05)

        detail_response = client.get(f"/api/workstation/clients/{client_id}")

    workstation_endpoints.professional_photo_jobs.clear()

    assert start_response.status_code == 202
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["status"] == "completed"
    assert status_payload["result"]["version"] == "v001"
    assert status_payload["result"]["image_path"].endswith("professional-photo/v001/professional-photo.jpg")
    assert [photo["version"] for photo in detail_response.json()["professional_photos"]] == ["v001"]
