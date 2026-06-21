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
    ContadoresConfig.update(
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


def test_contadores_message_external_id_is_unique_per_direction(monkeypatch, tmp_path) -> None:
    """WhatsApp provider ids should not become ambiguous within one direction."""
    configure_contadores_db(monkeypatch, tmp_path)
    database_module.ensure_contadores_message_external_id_index()
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-external-id-unique",
        phone="+5491112345679",
        full_name="External Unique",
    )

    outbound = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Hola",
        external_id="wamid.same-direction",
        delivery_status=MessageDeliveryStatus.SENT,
    )
    inbound = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si",
        external_id="wamid.same-direction",
    )
    retry = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text="Si",
        external_id="wamid.same-direction",
    )

    assert inbound.id != outbound.id
    assert retry.id == inbound.id
    with pytest.raises(ValueError, match="Duplicate Contadores message external_id"):
        ContadoresMessage.add(
            lead_id=lead.id,
            from_me=True,
            text="Conflicting outbound",
            external_id="wamid.same-direction",
            delivery_status=MessageDeliveryStatus.SENT,
        )
    with pytest.raises(IntegrityError):
        with Session(database_module.engine) as session:
            session.add(
                ContadoresMessage(
                    lead_id=lead.id,
                    from_me=True,
                    text="Raw duplicate",
                    external_id="wamid.same-direction",
                    delivery_status=MessageDeliveryStatus.SENT,
                )
            )
            session.commit()


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
    event_received_at = now_utc()
    scheduled_at = event_received_at + timedelta(days=1)

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/calendly/webhook",
            json={
                "token": lead.calendly_tracking_token,
                "event_type": "invitee.created",
                "occurred_at": event_received_at.isoformat(),
                "scheduled_start_at": scheduled_at.isoformat(),
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
    scheduled_prefix = scheduled_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    received_prefix = event_received_at.isoformat(timespec="seconds").replace("+00:00", "Z")
    assert payload["meeting_scheduled_at"].startswith(scheduled_prefix)
    assert not payload["meeting_scheduled_at"].startswith(received_prefix)
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


def test_calendly_webhook_requires_scheduled_start_for_schedule_event(monkeypatch, tmp_path) -> None:
    """A webhook receipt time must not be stored as the booked meeting time."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-calendly-missing-start",
        phone="+5491444444405",
        full_name="Missing Start",
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/contadores/calendly/webhook",
            json={
                "token": lead.calendly_tracking_token,
                "event_type": "invitee.created",
                "occurred_at": now_utc().isoformat(),
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert response.status_code == 400
    assert response.json()["detail"] == "Calendly scheduled_start_at is required."
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] != "calendly_sent"
    assert detail.json()["lead"]["meeting_scheduled_at"] is None
    assert detail.json()["lead"]["automation_paused"] is False


def test_calendly_webhook_preserves_closed_lead_terminal_state(monkeypatch, tmp_path) -> None:
    """A late Calendly callback can record history but must not reopen a closed lead."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-calendly-closed",
        phone="+5491444444406",
        full_name="Closed Scheduled",
    )
    calendly_sent_at = now_utc() - timedelta(minutes=10)
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=calendly_sent_at,
    )
    scheduled_at = now_utc() + timedelta(days=2)

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        response = client.post(
            "/api/contadores/calendly/webhook",
            json={
                "token": lead.calendly_tracking_token,
                "event_type": "invitee.created",
                "occurred_at": now_utc().isoformat(),
                "scheduled_start_at": scheduled_at.isoformat(),
            },
        )
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert close_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "closed"
    assert payload["raw_stage"] == "closed"
    assert payload["stage_before_closed"] == "calendly_sent"
    assert payload["closed_at"] is not None
    assert payload["meeting_scheduled_at"] is not None
    assert payload["automation_paused"] is False
    assert payload["automation_paused_reason"] is None

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "closed"
    assert detail.json()["lead"]["raw_stage"] == "closed"

    events = PlatformEvent.list_recent(
        target_type="lead",
        target_id=lead.id,
        event_type="contadores.lead.calendly_scheduled",
    )
    assert len(events) == 1
    assert events[0].lifecycle_stage == "calendly_scheduled"


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
    ContadoresConfig.update(enabled=True, alert_emails=["facu@example.com"])
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


def test_contadores_resume_automation_rejects_closed_lead(monkeypatch, tmp_path) -> None:
    """Resume automation must not implicitly reopen a closed lead."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-closed-resume",
        phone="+5491444444407",
        full_name="Closed Resume",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_handoff",
    )

    with TestClient(app) as client:
        close_response = client.post(f"/api/contadores/leads/{lead.id}/actions/close")
        response = client.post(f"/api/contadores/leads/{lead.id}/resume-automation")
        detail = client.get(f"/api/contadores/leads/{lead.id}")

    assert close_response.status_code == 200
    assert response.status_code == 409
    assert response.json()["detail"] == "Lead is closed. Reopen it before resuming automation."
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "closed"
    assert detail.json()["lead"]["raw_stage"] == "closed"
    assert detail.json()["lead"]["closed_at"] is not None
    assert detail.json()["lead"]["stage_before_closed"] == "needs_human"


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
    event_types = {
        event.event_type
        for event in PlatformEvent.list_recent(target_type="lead", target_id=lead.id, limit=10)
    }
    assert {"contadores.lead.closed", "contadores.lead.reopened"} <= event_types


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
    """Deleting an ordinary Contadores lead should remove owned child rows."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-7",
        phone="+5491666666666",
        full_name="Borrar Chat",
    )
    media_file = data_dir / "contadores" / "inbound_media" / lead.id / "foto.jpg"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(b"jpg")
    assignment = ContadoresStrategyAssignment.add(
        lead_id=lead.id,
        step="loom",
        strategy_id="text_offer_599",
        strategy_label="Text offer",
    )
    ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text="Mensaje con estrategia",
        strategy_assignment_id=assignment.id,
        media_path=f"data/contadores/inbound_media/{lead.id}/foto.jpg",
        media_type="image",
    )
    ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label="Contadores",
        alert_type="codex_fallback",
        error="fallo",
        fallback_action="manual",
        latest_inbound_text="hola",
    )
    ScheduledAgentTask.create(
        target_type="lead",
        target_id=lead.id,
        due_at=now_utc(),
        reason="delete-test",
        instruction="noop",
    )

    with TestClient(app) as client:
        detail_before = client.get(f"/api/contadores/leads/{lead.id}")
        delete_response = client.delete(f"/api/contadores/leads/{lead.id}")
        detail_after = client.get(f"/api/contadores/leads/{lead.id}")
        leads_response = client.get("/api/contadores/leads")

    with Session(database_module.engine) as session:
        messages = session.exec(select(ContadoresMessage).where(ContadoresMessage.lead_id == lead.id)).all()
        assignments = session.exec(
            select(ContadoresStrategyAssignment).where(ContadoresStrategyAssignment.lead_id == lead.id)
        ).all()
        alerts = session.exec(select(ContadoresRuntimeAlert).where(ContadoresRuntimeAlert.lead_id == lead.id)).all()
        tasks = session.exec(select(ScheduledAgentTask).where(ScheduledAgentTask.target_id == lead.id)).all()

    assert detail_before.status_code == 200
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "deleted", "lead_id": lead.id, "deleted_media_files": 1}
    assert detail_after.status_code == 404
    assert [item["id"] for item in leads_response.json()["leads"]] == []
    assert messages == []
    assert assignments == []
    assert alerts == []
    assert tasks == []
    assert not media_file.exists()


def test_contadores_delete_lead_blocks_workstation_clients(monkeypatch, tmp_path) -> None:
    """Paid Workstation work should not be hard-deleted through the CRM lead endpoint."""
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-delete-workstation",
        phone="+5491666666677",
        full_name="Cliente Workstation",
    )
    WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PAID,
    )

    with TestClient(app) as client:
        delete_response = client.delete(f"/api/contadores/leads/{lead.id}")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert delete_response.status_code == 409
    assert "Workstation client" in delete_response.json()["detail"]
    assert detail_response.status_code == 200
