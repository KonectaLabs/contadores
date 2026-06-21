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


def test_conversation_prompt_text_is_bounded(monkeypatch, tmp_path) -> None:
    """Conversation prompt rendering should cap per-message and total text."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="prompt-cap-helper",
        phone="+5491222222200",
        full_name="Prompt Cap",
    )
    long_text = "x" * (contadores_endpoints.CONVERSATION_PROMPT_MESSAGE_CHARS + 500)
    for index in range(40):
        ContadoresMessage.add(
            lead_id=lead.id,
            from_me=bool(index % 2),
            text=f"{index}-{long_text}",
            created_at=now_utc() + timedelta(seconds=index),
        )

    messages = ContadoresMessage.list_by_lead(lead.id)
    transcript = contadores_endpoints.format_conversation_for_bot(messages)

    assert len(transcript) <= contadores_endpoints.CONVERSATION_PROMPT_TOTAL_CHARS
    assert "[truncated " in transcript
    assert "LEAD: 0-" not in transcript


def test_conversation_bot_receives_truncated_latest_inbound(monkeypatch, tmp_path) -> None:
    """Oversized latest inbound text should be capped before model invocation."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=30)
    lead = ContadoresLead.upsert(
        external_lead_id="prompt-cap-latest",
        phone="+593991111119",
        full_name="Prompt Latest",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola, si te interesa esta oferta respondeme y te mostramos un ejemplo.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        sequence_step="promo_web_profesional_20260505",
        created_at=now_utc() - timedelta(minutes=2),
    )
    long_inbound = "Cuanto demora? " + ("mucho " * 1200)
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text=long_inbound,
        created_at=now_utc() - timedelta(seconds=45),
    )
    seen: dict[str, str] = {}

    class FakeConversationBot:
        async def aforward(self, **kwargs):
            seen["latest_inbound"] = kwargs["latest_inbound"]
            seen["conversation"] = kwargs["conversation"]
            return ContadoresConversationBotResult(
                action="ask_scheduling_details",
                message_text="Perfecto. Me pasa su email, dia y horario?",
                classification_label="active_offer_scheduling_requested",
                reason="El lead mostro interes.",
                missing_fields=["email", "day", "time"],
            )

    monkeypatch.setattr(contadores_endpoints, "ContadoresConversationBotProgram", FakeConversationBot)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")

    assert response.status_code == 200
    assert len(seen["latest_inbound"]) <= contadores_endpoints.LATEST_INBOUND_PROMPT_CHARS
    assert "[truncated " in seen["latest_inbound"]
    assert len(seen["conversation"]) <= contadores_endpoints.CONVERSATION_PROMPT_TOTAL_CHARS


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


def test_pending_alerts_claim_prevents_immediate_duplicate_reads_and_recovers_stale(monkeypatch, tmp_path) -> None:
    """Pending alert reads should reserve lead and runtime alerts before AgentMail sends."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-alert-claim",
        phone="+5491333333301",
        full_name="Lead Claim",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
    )
    add_recent_inbound(lead.id, text="Necesito que me respondan esto")
    runtime_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-runtime-alert-claim",
        phone="+5491333333302",
        full_name="Runtime Claim",
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=runtime_lead,
        funnel_label="Contadores",
        alert_type="codex_fallback",
        error="Codex failed",
        fallback_action="send_reply",
        latest_inbound_text="Cuanto cuesta?",
        previous_stage="awaiting_initial_reply",
    )

    with TestClient(app) as client:
        first = client.get("/api/contadores/alerts/pending")
        second = client.get("/api/contadores/alerts/pending")
        stale_claimed_at = now_utc() - timedelta(seconds=contadores_endpoints.CONTADORES_ALERT_CLAIM_LEASE_SECONDS + 1)
        with database_module.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE contadores_leads SET alert_claimed_at = ? WHERE id IN (?, ?)",
                (stale_claimed_at, lead.id, runtime_lead.id),
            )
            connection.exec_driver_sql(
                "UPDATE contadores_runtime_alerts SET alert_claimed_at = ? WHERE id = ?",
                (stale_claimed_at, alert.id),
            )
        after_stale = client.get("/api/contadores/alerts/pending")

    assert first.status_code == 200
    first_items = first.json()["items"]
    assert {item["alert_kind"] for item in first_items} == {"needs_human", "runtime"}
    assert {item["lead_id"] for item in first_items} == {lead.id, runtime_lead.id}
    assert second.status_code == 200
    assert second.json()["items"] == []
    assert after_stale.status_code == 200
    after_stale_items = after_stale.json()["items"]
    assert {item["lead_id"] for item in after_stale_items} == {lead.id, runtime_lead.id}
    assert [item["runtime_alert_id"] for item in after_stale_items if item["alert_kind"] == "runtime"] == [alert.id]


def test_pending_alerts_retry_only_failed_recipient(monkeypatch, tmp_path) -> None:
    """Delivered alert recipients should not be returned again while failed ones retry when due."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, alert_emails=["sent@example.com", "fail@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-alert-recipient-retry",
        phone="+5491333333304",
        full_name="Recipient Retry",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
    )
    add_recent_inbound(lead.id, text="Necesito ayuda")
    now = now_utc()
    ContadoresAlertDelivery.mark_attempt(
        alert_kind="lead",
        target_id=lead.id,
        recipient="sent@example.com",
        sent_at=now,
        success=True,
        email_message_id="agentmail-sent",
    )
    ContadoresAlertDelivery.mark_attempt(
        alert_kind="lead",
        target_id=lead.id,
        recipient="fail@example.com",
        sent_at=now - timedelta(minutes=10),
        success=False,
        error="rejected",
        retry_after_seconds=0,
    )

    with TestClient(app) as client:
        pending = client.get("/api/contadores/alerts/pending")

    assert pending.status_code == 200
    assert pending.json()["items"][0]["alert_emails"] == ["fail@example.com"]


def test_runtime_alert_redacts_provider_error_before_persistence(monkeypatch, tmp_path) -> None:
    """Provider error strings should be sanitized before durable alert storage."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-runtime-alert-redact",
        phone="+5491333333303",
        full_name="Runtime Redact",
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="codex_fallback",
        error=(
            "RuntimeError: failed bearer sk-test-secret "
            "https://api.example.test/path?token=abc123 for lead@example.com "
            "+5491111112222 /Users/fgoiriz/private/repos/contadores/.env"
        ),
        fallback_action="send_reply",
        latest_inbound_text="Cuanto cuesta?",
        previous_stage="awaiting_initial_reply",
    )

    assert "sk-test-secret" not in alert.error
    assert "abc123" not in alert.error
    assert "lead@example.com" not in alert.error
    assert "+5491111112222" not in alert.error
    assert "/Users/fgoiriz" not in alert.error
    assert "[redacted]" in alert.error


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
    with TestClient(app) as client:
        image_media = client.get(outbound_messages[1]["media_url"])
    assert image_media.status_code == 200
    assert image_media.headers["x-content-type-options"] == "nosniff"
    assert image_media.headers["content-type"].startswith("image/png")
    assert "inline" in image_media.headers["content-disposition"]


def test_manual_outbound_media_rejects_too_many_files_without_partial_enqueue(monkeypatch, tmp_path) -> None:
    """Manual media upload should reject an oversized batch before writing rows."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "CONTADORES_MANUAL_MEDIA_MAX_FILES", 2)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-too-many",
        phone="+5491888888878",
        full_name="Too Many Files",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual-media",
            files=[
                ("file", ("one.pdf", b"one", "application/pdf")),
                ("file", ("two.pdf", b"two", "application/pdf")),
                ("file", ("three.pdf", b"three", "application/pdf")),
            ],
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 413
    assert response.json()["detail"] == "Attach at most 2 files"
    assert pending.json()["messages"] == []
    assert not (data_dir / "contadores" / "outbound_media" / lead.id).exists()


def test_manual_outbound_media_rejects_oversized_file_without_partial_enqueue(monkeypatch, tmp_path) -> None:
    """Manual media upload should reject a single oversized file before writing rows."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "CONTADORES_MANUAL_MEDIA_MAX_FILE_BYTES", 4)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-oversized",
        phone="+5491888888879",
        full_name="Oversized File",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual-media",
            files=[("file", ("large.pdf", b"12345", "application/pdf"))],
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 413
    assert response.json()["detail"] == "Each file must be at most 4 bytes"
    assert pending.json()["messages"] == []
    assert not (data_dir / "contadores" / "outbound_media" / lead.id).exists()


def test_manual_outbound_media_rejects_total_size_without_partial_enqueue(monkeypatch, tmp_path) -> None:
    """Manual media upload should reject a too-large total batch before writing rows."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "CONTADORES_MANUAL_MEDIA_MAX_FILE_BYTES", 10)
    monkeypatch.setattr(contadores_endpoints, "CONTADORES_MANUAL_MEDIA_MAX_TOTAL_BYTES", 5)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-total",
        phone="+5491888888880",
        full_name="Total Size",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual-media",
            files=[
                ("file", ("one.pdf", b"123", "application/pdf")),
                ("file", ("two.pdf", b"456", "application/pdf")),
            ],
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 413
    assert response.json()["detail"] == "Attached files must total at most 5 bytes"
    assert pending.json()["messages"] == []
    assert not (data_dir / "contadores" / "outbound_media" / lead.id).exists()


def test_manual_outbound_media_serves_svg_as_attachment(monkeypatch, tmp_path) -> None:
    """SVG-like uploads should not be served as same-origin inline executable content."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-svg",
        phone="+5491888888881",
        full_name="Svg File",
    )
    add_recent_inbound(lead.id)

    with TestClient(app) as client:
        upload_response = client.post(
            f"/api/contadores/leads/{lead.id}/messages/manual-media",
            files=[("file", ("bad.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml"))],
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        outbound = [item for item in detail.json()["messages"] if item["from_me"]][0]
        media = client.get(outbound["media_url"])

    assert upload_response.status_code == 200
    assert outbound["media_type"] == "document"
    assert outbound["media_mime_type"] == "application/octet-stream"
    assert media.status_code == 200
    assert media.headers["x-content-type-options"] == "nosniff"
    assert media.headers["content-type"].startswith("application/octet-stream")
    assert "attachment" in media.headers["content-disposition"]


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
    assert converted_lead is not None
    assert ContadoresLead.lead_is_converted(converted_lead) is True
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


def test_contadores_automation_tick_returns_busy_when_funnel_lock_is_held(monkeypatch, tmp_path) -> None:
    """Overlapping ticks for the same funnel should not scan or queue messages."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(tmp_path, build_contadores_test_funnel())
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-busy-tick",
        phone="+5491666666601",
        full_name="Busy Tick",
    )
    lock = asyncio.Lock()
    asyncio.run(lock.acquire())
    monkeypatch.setattr(contadores_endpoints, "get_contadores_automation_tick_lock", lambda funnel_id: lock)

    try:
        with TestClient(app) as client:
            response = client.post("/api/contadores/automation/tick")
    finally:
        lock.release()

    assert response.status_code == 200
    assert response.json()["status"] == "busy"
    assert ContadoresMessage.list_by_lead(lead.id) == []


def test_contadores_automation_tick_sends_video_check_after_wait(monkeypatch, tmp_path) -> None:
    """When the Loom wait expires without replies, the video-check prompt must be queued."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
        alert_emails=["facu@example.com"],
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
        alert_emails=["facu@example.com"],
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
                    "Si le interesa, le mostramos un ejemplo y vemos si le sirve para su caso.\n"
                    "-- \n"
                    "Firma del operador"
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
    assert "Firma del operador" not in pending_after.json()["messages"][0]["text"]
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


def test_unanswered_question_email_reply_dedupes_agentmail_replay(monkeypatch, tmp_path) -> None:
    """A replayed AgentMail message id must not queue the WhatsApp answer twice."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agentmail-replay",
        phone="+593991111116",
        full_name="AgentMail Replay",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="hasta cuando?",
        created_at=now_utc() - timedelta(minutes=2),
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="unanswered_lead_question",
        error="No answer",
        fallback_action="await_operator_teaching",
        latest_inbound_text="hasta cuando?",
        previous_stage="awaiting_initial_reply",
    )
    database_module.ContadoresRuntimeAlert.mark_notified(
        alert_id=alert.id or 0,
        email_thread_id="thread-agentmail-replay",
        email_message_id="email-alert-replay",
        email_inbox_id="alerts-inbox",
        email_inbox_address="alerts@example.com",
    )

    payload = {
        "inbox_id": "alerts-inbox",
        "message_id": "email-reply-replay",
        "from_email": "facu@example.com",
        "thread_id": "thread-agentmail-replay",
        "plain_text": "Respuesta: La promo va hasta el viernes.",
    }
    with TestClient(app) as client:
        first = client.post("/api/contadores/runtime-alerts/email-reply", json=payload)
        second = client.post("/api/contadores/runtime-alerts/email-reply", json=payload)
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert first.status_code == 200
    assert first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["queued_message_ids"] == first.json()["queued_message_ids"]
    assert [item["text"] for item in pending.json()["messages"]] == ["La promo va hasta el viernes."]


def test_unanswered_question_email_reply_requires_explicit_respuesta_block(monkeypatch, tmp_path) -> None:
    """Free-form AgentMail replies should not be forwarded to the lead."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agentmail-missing-block",
        phone="+593991111118",
        full_name="AgentMail Missing Block",
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="unanswered_lead_question",
        error="No answer",
        fallback_action="await_operator_teaching",
        latest_inbound_text="hasta cuando?",
        previous_stage="awaiting_initial_reply",
    )
    database_module.ContadoresRuntimeAlert.mark_notified(
        alert_id=alert.id or 0,
        email_thread_id="thread-agentmail-missing-block",
        email_message_id="email-alert-missing-block",
        email_inbox_id="alerts-inbox",
        email_inbox_address="alerts@example.com",
    )

    with TestClient(app) as client:
        reply = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "alerts-inbox",
                "message_id": "email-reply-missing-block",
                "from_email": "facu@example.com",
                "thread_id": "thread-agentmail-missing-block",
                "plain_text": "La promo va hasta el viernes.\n\nEl jue, Facu escribio:",
            },
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert reply.status_code == 200
    assert reply.json() == {"status": "ignored", "reason": "missing_operator_reply_block"}
    assert pending.json()["messages"] == []


def test_unanswered_question_email_reply_rejects_oversized_respuesta_block(monkeypatch, tmp_path) -> None:
    """AgentMail replies should not rely on WhatsApp provider chunking for huge text."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agentmail-long-block",
        phone="+593991111119",
        full_name="AgentMail Long Block",
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="unanswered_lead_question",
        error="No answer",
        fallback_action="await_operator_teaching",
        latest_inbound_text="hasta cuando?",
        previous_stage="awaiting_initial_reply",
    )
    database_module.ContadoresRuntimeAlert.mark_notified(
        alert_id=alert.id or 0,
        email_thread_id="thread-agentmail-long-block",
        email_message_id="email-alert-long-block",
        email_inbox_id="alerts-inbox",
        email_inbox_address="alerts@example.com",
    )

    with TestClient(app) as client:
        reply = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "alerts-inbox",
                "message_id": "email-reply-long-block",
                "from_email": "facu@example.com",
                "thread_id": "thread-agentmail-long-block",
                "plain_text": "Respuesta: " + ("a" * (contadores_endpoints.OPERATOR_WHATSAPP_REPLY_MAX_CHARS + 1)),
            },
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert reply.status_code == 200
    assert reply.json() == {"status": "ignored", "reason": "operator_reply_too_long"}
    assert pending.json()["messages"] == []


def test_unanswered_question_email_reply_rejects_unauthorized_sender_and_inbox(monkeypatch, tmp_path) -> None:
    """Only the original alert inbox and configured alert recipients may teach/send replies."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True, post_loom_quiet_seconds=1, alert_emails=["facu@example.com"])
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-agentmail-auth",
        phone="+593991111117",
        full_name="AgentMail Auth",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="hasta cuando?",
        created_at=now_utc() - timedelta(minutes=2),
    )
    alert = database_module.ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="unanswered_lead_question",
        error="No answer",
        fallback_action="await_operator_teaching",
        latest_inbound_text="hasta cuando?",
        previous_stage="awaiting_initial_reply",
    )
    database_module.ContadoresRuntimeAlert.mark_notified(
        alert_id=alert.id or 0,
        email_thread_id="thread-agentmail-auth",
        email_message_id="email-alert-auth",
        email_inbox_id="alerts-inbox",
        email_inbox_address="alerts@example.com",
    )

    with TestClient(app) as client:
        wrong_sender = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "alerts-inbox",
                "message_id": "email-reply-bad-sender",
                "from_email": "intruso@example.com",
                "thread_id": "thread-agentmail-auth",
                "plain_text": "Respuesta: mala respuesta",
            },
        )
        wrong_inbox = client.post(
            "/api/contadores/runtime-alerts/email-reply",
            json={
                "inbox_id": "other-inbox",
                "message_id": "email-reply-bad-inbox",
                "from_email": "facu@example.com",
                "thread_id": "thread-agentmail-auth",
                "plain_text": "Respuesta: mala respuesta",
            },
        )
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert wrong_sender.status_code == 200
    assert wrong_sender.json() == {"status": "ignored", "reason": "sender_not_allowed"}
    assert wrong_inbox.status_code == 200
    assert wrong_inbox.json() == {"status": "ignored", "reason": "email_inbox_mismatch"}
    assert pending.json()["messages"] == []


def test_alert_email_policy_rejects_disallowed_config_recipient(monkeypatch, tmp_path) -> None:
    """Configured alert emails must match the explicit allowlist when one exists."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTADORES_ALERT_ALLOWED_EMAILS", "ops@example.com")

    with TestClient(app) as client:
        response = client.put("/api/contadores/config", json={"alert_emails": ["other@example.com"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "Alert email recipient is not allowed: other@example.com"


def test_conversation_bot_handoffs_complete_scheduling_details(monkeypatch, tmp_path) -> None:
    """Email, day, and time should trigger a scheduling handoff alert, not Calendly."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(
        enabled=True,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
        alert_emails=["facu@example.com"],
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
