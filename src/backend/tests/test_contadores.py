"""Regression tests for the dedicated Contadores flow."""

from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import zipfile

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.contadores as contadores_endpoints
from backend.contadores_strategies import get_contadores_strategy
from backend.database import (
    ContadoresConfig,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    MessageDeliveryStatus,
    WorkstationClient,
)
from backend.main import app


def now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp for test fixtures."""
    return datetime.now(timezone.utc)


def configure_contadores_db(monkeypatch, tmp_path) -> None:
    """Point database and Contadores router state at a temporary SQLite file."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
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


def force_loom_strategy(monkeypatch, strategy_id: str = "loom_mp4") -> None:
    """Force one Loom strategy in automation tests."""
    strategy = get_contadores_strategy("loom", strategy_id)
    assert strategy is not None
    monkeypatch.setattr(contadores_endpoints, "choose_contadores_strategy", lambda **kwargs: strategy)


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
        "opener_text": "Hola, completaste el formulario para abogados. Es correcto?",
        "opener_template_name": "abogados_intro_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "manual_ping_text": "Hola, queria saber si queres que retomemos la conversacion",
        "manual_ping_template_name": None,
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/konecta/abogados",
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


def test_runtime_endpoint_reports_sheet_readiness(monkeypatch, tmp_path) -> None:
    """Runtime status should expose non-secret sheet readiness."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTADORES_SHEET_URL", "https://docs.google.com/spreadsheets/d/example")
    monkeypatch.setenv("CONTADORES_LOOM_URL", "https://www.loom.com/share/example")
    monkeypatch.setenv("CONTADORES_CALENDLY_BASE_URL", "https://calendly.com/example")

    with TestClient(app) as client:
        response = client.get("/api/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sheet_configured"] is True
    assert payload["ready"] is True


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


def test_contadores_pending_delivery_keeps_full_mp4_sequence(monkeypatch, tmp_path) -> None:
    """Loom intro and WhatsApp MP4 must both remain visible to the bot outbox."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-1",
        phone="+5491111111111",
        full_name="Ana Perez",
    )

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
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-mp4",
        phone="+5491111111112",
        full_name="Media Lead",
    )

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_mp4")

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert [item["sequence_step"] for item in payload["messages"]] == ["loom_intro", "loom_video"]
    assert payload["messages"][1]["media_type"] == "video"
    assert payload["messages"][1]["media_path"] == "data/contadores/videos/loom_60_seconds_captions.mp4"
    assert [item["strategy_id"] for item in payload["messages"]] == ["loom_mp4", "loom_mp4"]


def test_contadores_zero_weight_strategy_is_not_auto_assigned() -> None:
    """A configured zero-weight strategy should stay available without receiving automatic traffic."""
    chosen_ids = {
        contadores_endpoints.choose_contadores_strategy(step="loom", lead_id=f"lead-{index}").id
        for index in range(50)
    }

    assert chosen_ids == {"loom_mp4"}


def test_contadores_strategy_weights_are_configurable(monkeypatch, tmp_path) -> None:
    """Config weights should drive automatic strategy assignment and stats display."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(
        enabled=True,
        strategy_weights={"loom": {"loom_mp4": 100}},
    )
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-config-weight",
        phone="+5491111111199",
        full_name="Weight Lead",
    )

    contadores_endpoints.send_loom_sequence(lead=lead, config=config)

    with TestClient(app) as client:
        config_response = client.get("/api/contadores/config")
        stats_response = client.get("/api/contadores/strategy-stats")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert config_response.status_code == 200
    assert config_response.json()["strategy_weights"] == {
        "loom": {"loom_mp4": 100}
    }

    assert stats_response.status_code == 200
    items = {item["strategy_id"]: item for item in stats_response.json()["items"]}
    assert items["loom_mp4"]["weight"] == 100

    assert pending_response.status_code == 200
    assert [item["strategy_id"] for item in pending_response.json()["messages"]] == [
        "loom_mp4",
        "loom_mp4",
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

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_mp4")
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
    assert items["loom_mp4"]["assigned"] == 1
    assert items["loom_mp4"]["sent"] == 1
    assert items["loom_mp4"]["delivered"] == 1
    assert items["loom_mp4"]["reached_calendly"] == 1
    assert items["loom_mp4"]["booked"] == 1
    assert items["loom_mp4"]["calendly_rate"] == 1


def test_contadores_pending_delivery_exposes_new_opener_template_without_params(monkeypatch, tmp_path) -> None:
    """The opener should stay template-backed even after moving to a fixed copy."""
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
            "text": "Hola, llenaste el formulario para contadores sobre como conseguir clientes a tu whatsapp. Es correcto?",
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
            "contact_has_inbound": False,
            "whatsapp_template_name": "contadores_intro_es_v2",
            "whatsapp_template_language": "es",
            "whatsapp_template_body_params": [],
        }
    ]


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


def test_manual_booked_action_marks_booked_without_queueing_template(monkeypatch, tmp_path) -> None:
    """Operators can move a lead straight to Booked without sending WhatsApp."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-manual-booked",
        phone="+5491888888877",
        full_name="Booked Manual",
    )

    with TestClient(app) as client:
        action_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-booked")
        pending_response = client.get("/api/contadores/messages/pending-delivery")
        detail_response = client.get(f"/api/contadores/leads/{lead.id}")

    assert action_response.status_code == 200
    assert pending_response.status_code == 200
    messages = pending_response.json()["messages"]
    assert messages == []

    assert detail_response.status_code == 200
    lead_payload = detail_response.json()["lead"]
    assert lead_payload["stage"] == "booked"
    assert lead_payload["booked_at"] is not None
    assert lead_payload["automation_paused"] is True
    assert lead_payload["automation_paused_reason"] == "manual_booked"


def test_booked_leads_do_not_expose_pending_manual_ping(monkeypatch, tmp_path) -> None:
    """Booked leads must stay out of WhatsApp dispatch even if a ping was queued earlier."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    configure_contadores_db(monkeypatch, tmp_path)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-booked-with-ping",
        phone="+5491888888878",
        full_name="Booked With Ping",
    )

    with TestClient(app) as client:
        ping_response = client.post(f"/api/contadores/leads/{lead.id}/actions/send-manual-ping")
        booked_response = client.post(f"/api/contadores/leads/{lead.id}/actions/mark-booked")
        pending_response = client.get("/api/contadores/messages/pending-delivery")

    assert ping_response.status_code == 200
    assert booked_response.status_code == 200
    assert pending_response.status_code == 200
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


def test_contadores_config_normalizes_generic_calendly_base_url(monkeypatch, tmp_path) -> None:
    """A generic Calendly host should collapse to the configured meeting URL."""
    configure_contadores_db(monkeypatch, tmp_path)

    ContadoresConfig.update(calendly_base_url="https://calendly.com")
    config = ContadoresConfig.get()

    assert config.calendly_base_url == "https://calendly.com/yoelkravchuk/konecta-meet"


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


def test_contadores_automation_tick_classifies_affirmative_reply_and_sends_calendly(monkeypatch, tmp_path) -> None:
    """A clear affirmative post-Loom reply should advance straight to Calendly."""
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

    class FakeClassifier:
        async def aforward(self, *, loom_context: str, reply_batch: str):
            assert "quiere avanzar" in loom_context.lower()
            assert "quiero avanzar" in reply_batch.lower()
            return SimpleNamespace(label="wants_to_proceed", reasoning="clear affirmative")

    monkeypatch.setattr(contadores_endpoints, "PostLoomReplyClassifierProgram", FakeClassifier)

    with TestClient(app) as client:
        response = client.post("/api/contadores/automation/tick")
        detail = client.get(f"/api/contadores/leads/{lead.id}")
        pending = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    assert response.json()["classified_wants_to_proceed"] == 1
    assert response.json()["calendly_sent"] == 1
    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "calendly_sent"
    assert detail.json()["lead"]["last_classification_label"] == "wants_to_proceed"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_intro", "calendly_url"]
    assert pending.json()["messages"][1]["text"] == "https://calendly.com/yoelkravchuk/konecta-meet"
    assert "utm_" not in pending.json()["messages"][1]["text"]
    assert pending.json()["messages"][0]["text"] == (
        "Para avanzar solo falta -> Reunion, nos conocemos -> definimos medio de pago -> "
        "pagas 300 USD -> empezamos a trabajar para vos a las 24 horas.\n\n"
        "Elige el horario que mejor te quede:"
    )


def test_contadores_reply_after_24h_followup_still_advances_to_loom(monkeypatch, tmp_path) -> None:
    """A reply after the 24-hour reminder should use the usual next stage and Loom copy."""
    configure_contadores_db(monkeypatch, tmp_path)
    force_loom_strategy(monkeypatch, "loom_mp4")
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
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["loom_intro", "loom_video"]
    assert pending.json()["messages"][0]["text"] == contadores_endpoints.build_loom_intro_text()
    assert pending.json()["messages"][1]["media_type"] == "video"


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
    assert detail.json()["events"][0]["payload"]["profile_name"] == "Ana WhatsApp"


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
    assert detail.json()["events"][0]["payload"]["profile_name"] == "Nombre WhatsApp"


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
        "opener_text": "Hola, completaste el formulario para abogados. Es correcto?",
        "opener_template_name": "abogados_intro_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "manual_ping_text": "Hola, queria saber si queres que retomemos la conversacion",
        "manual_ping_template_name": None,
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/konecta/abogados",
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
    ctwa_events = [
        event for event in detail.json()["events"]
        if event["event_type"] == "ctwa_inbound_created"
    ]
    assert len(ctwa_events) == 1
    assert ctwa_events[0]["payload"]["profile_name"] == "Rocio WhatsApp"
    assert ctwa_events[0]["payload"]["referral"]["source_id"] == "120244283740930010"

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
    prefilled_events = [
        event for event in detail.json()["events"]
        if event["event_type"] == "prefilled_whatsapp_inbound_created"
    ]
    assert len(prefilled_events) == 1
    assert (
        prefilled_events[0]["payload"]["prefilled_message_route"]
        == "abogados_prefilled_proposal"
    )
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
    assert detail.json()["events"][0]["payload"]["profile_name"] == "Camila WhatsApp"
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
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5b",
        phone="+5491444444400",
        full_name="Lara Calendly",
    )
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
    assert payload["queued_message_ids"] == [1, 2]

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["calendly_url"] == "https://calendly.com/yoelkravchuk/konecta-meet"
    assert "calendly_tracking_token" not in detail.json()["lead"]
    assert detail.json()["lead"]["automation_paused"] is True
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_intro", "calendly_url"]
    assert pending.json()["messages"][1]["text"] == "https://calendly.com/yoelkravchuk/konecta-meet"


def test_contadores_send_calendly_link_only_marks_calendly_sent(monkeypatch, tmp_path) -> None:
    """Operators can send only the Calendly URL without the intro text."""
    configure_contadores_db(monkeypatch, tmp_path)
    ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-5b-link",
        phone="+5491444444402",
        full_name="Lara Calendly Link",
    )
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
    assert payload["queued_message_ids"] == [1]

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["calendly_url"] == "https://calendly.com/yoelkravchuk/konecta-meet"
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_url"]
    assert pending.json()["messages"][0]["text"] == "https://calendly.com/yoelkravchuk/konecta-meet"


def test_contadores_post_calendly_inbound_returns_to_needs_human(monkeypatch, tmp_path) -> None:
    """Any new inbound after Calendly should hand the lead back to a human."""
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
    assert detail.json()["lead"]["stage"] == "needs_human"
    assert detail.json()["lead"]["raw_stage"] == "needs_human"
    assert detail.json()["lead"]["automation_paused"] is True
    assert detail.json()["lead"]["automation_paused_reason"] == "post_calendly_inbound"
    assert detail.json()["lead"]["last_classification_label"] == "needs_human"
    assert detail.json()["lead"]["last_classification_reason"] == "Inbound reply received after Calendly sequence."
    assert any(event["event_type"] == "post_calendly_inbound_handoff" for event in detail.json()["events"])

    assert alerts.status_code == 200
    assert [item["lead_id"] for item in alerts.json()["items"]] == [lead.id]


def test_contadores_inbound_audio_payload_is_persisted_and_playable(monkeypatch, tmp_path) -> None:
    """Audio sent by leads should be stored on the message and exposed through the media endpoint."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    media_file = data_dir / "contadores" / "inbound_media" / "lead-audio.ogg"
    media_file.parent.mkdir(parents=True)
    media_file.write_bytes(b"audio-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(contadores_endpoints, "DATA_DIR", data_dir)
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
        message = detail.json()["messages"][0]
        media = client.get(message["media_url"])

    assert response.status_code == 200
    assert response.json()["route"] == "contadores"

    assert detail.status_code == 200
    assert message["text"] == "[audio]"
    assert message["media_type"] == "audio"
    assert message["media_path"] == "data/contadores/inbound_media/lead-audio.ogg"
    assert message["media_mime_type"] == "audio/ogg"
    assert message["media_filename"] == "lead-audio.ogg"
    assert message["media_id"] == "media-audio-1"
    assert message["media_url"].startswith("/api/contadores/media/")
    assert media.status_code == 200
    assert media.content == b"audio-bytes"
    assert media.headers["content-type"] == "audio/ogg"


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
    assert any(
        event["event_type"] == "manual_reply_marked_answered"
        for event in detail_after.json()["events"]
    )
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
    assert response.json()["counts"] == {"contadores": 1, "general": 1}


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
        needs_human_response = client.get("/api/contadores/leads?needs_human=true")
        alerts_response = client.get("/api/contadores/alerts/pending")

    assert booked_response.status_code == 200
    assert booked_response.json()["metrics"]["booked"] == 1
    assert [item["id"] for item in booked_response.json()["leads"]] == [lead.id]
    assert booked_response.json()["leads"][0]["stage"] == "booked"
    assert booked_response.json()["leads"][0]["raw_stage"] == "needs_human"

    assert needs_human_response.status_code == 200
    assert needs_human_response.json()["metrics"]["needs_human"] == 0
    assert needs_human_response.json()["leads"] == []

    assert alerts_response.status_code == 200
    assert alerts_response.json()["items"] == []


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
    assert [item["id"] for item in calendly_response.json()["leads"]] == [lead.id]
    assert calendly_response.json()["leads"][0]["stage"] == "needs_human"
    assert calendly_response.json()["leads"][0]["raw_stage"] == "needs_human"

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

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["leads"]] == [calendly_lead.id]
    assert payload["metrics"]["total"] == 3
    assert payload["metrics"]["awaiting_initial_reply"] == 1
    assert payload["metrics"]["awaiting_video_reply"] == 1
    assert payload["metrics"]["calendly_sent"] == 1


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


def test_contadores_leads_filter_by_prior_loom_strategy_inside_calendly(monkeypatch, tmp_path) -> None:
    """Operators should filter Calendly leads by the Loom strategy assigned earlier."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(enabled=True)
    unassigned_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-loom-link-filter",
        phone="+5491555555563",
        full_name="Unassigned Lead",
    )
    mp4_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-loom-mp4-filter",
        phone="+5491555555564",
        full_name="MP4 Lead",
    )
    contadores_endpoints.send_loom_sequence(lead=mp4_lead, config=config, strategy_id="loom_mp4")
    ContadoresLead.update_flow_state(
        unassigned_lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )
    ContadoresLead.update_flow_state(
        mp4_lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=now_utc(),
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/contadores/leads?stage=calendly_sent&strategy_step=loom&strategy_id=loom_mp4"
        )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["leads"]] == [mp4_lead.id]
    assert payload["metrics"]["total"] == 1
    assert payload["metrics"]["calendly_sent"] == 1
    assert payload["leads"][0]["strategy_assignments"][0]["strategy_id"] == "loom_mp4"


def test_contadores_delete_lead_removes_timeline(monkeypatch, tmp_path) -> None:
    """Deleting a Contadores lead should remove the lead and its stored timeline."""
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
    assert crm_detail.json()["lead"]["workstation_status"] == "paid"
    assert crm_detail.json()["lead"]["stage"] == "booked"
    assert WorkstationClient.get_by_lead_id(lead.id) is not None


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
        copy_response = client.get(f"/api/workstation/clients/{client_id}/copy-all")
        zip_response = client.get(f"/api/workstation/clients/{client_id}/zip")

    assert notes_response.status_code == 200
    assert upload_response.status_code == 200
    assert upload_response.json()["title"] == "Logo actual"
    assert upload_response.json()["stored_path"].startswith("data/workstation/clients/")
    assert "Notas de reunion" in copy_response.json()["text"]
    assert "Necesito una web seria" in copy_response.json()["text"]

    folder = data_dir / "workstation" / "clients" / created["client"]["folder_name"]
    assert (folder / "notes.txt").read_text(encoding="utf-8") == "Notas de reunion\nQuiere landing premium."
    assert "Necesito una web seria" in (folder / "conversation.txt").read_text(encoding="utf-8")
    assert (folder / "media" / upload_response.json()["stored_filename"]).read_bytes() == b"image-bytes"

    assert zip_response.status_code == 200
    with zipfile.ZipFile(BytesIO(zip_response.content)) as archive:
        names = set(archive.namelist())
        assert {"profile.json", "notes.txt", "conversation.txt"}.issubset(names)
        assert f"media/{upload_response.json()['stored_filename']}" in names
