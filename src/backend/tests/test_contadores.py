"""Regression tests for the dedicated Contadores flow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
)
from backend.main import app


def now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp for test fixtures."""
    return datetime.now(timezone.utc)


def configure_contadores_db(monkeypatch, tmp_path) -> None:
    """Point database and Contadores router state at a temporary SQLite file."""
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


def force_loom_strategy(monkeypatch, strategy_id: str = "loom_link") -> None:
    """Force one Loom strategy in automation tests."""
    strategy = get_contadores_strategy("loom", strategy_id)
    assert strategy is not None
    monkeypatch.setattr(contadores_endpoints, "choose_contadores_strategy", lambda **kwargs: strategy)


def test_runtime_endpoint_reports_source_mode(monkeypatch, tmp_path) -> None:
    """Runtime status must expose the canonical environment source mode."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTADORES_SOURCE_MODE", "testing")
    monkeypatch.setenv("CONTADORES_TEST_PHONE", "+5491111111111")
    monkeypatch.setenv("CONTADORES_LOOM_URL", "https://www.loom.com/share/example")
    monkeypatch.setenv("CONTADORES_CALENDLY_BASE_URL", "https://calendly.com/example")

    with TestClient(app) as client:
        response = client.get("/api/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_mode"] == "testing"
    assert payload["testing_phone_configured"] is True
    assert payload["ready"] is True


def test_contadores_pending_delivery_keeps_full_sequence(monkeypatch, tmp_path) -> None:
    """Loom intro and Loom URL must both remain visible to the bot outbox."""
    configure_contadores_db(monkeypatch, tmp_path)
    config = ContadoresConfig.update(enabled=True)
    lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-1",
        phone="+5491111111111",
        full_name="Ana Perez",
    )

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_link")

    with TestClient(app) as client:
        response = client.get("/api/contadores/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert [item["sequence_step"] for item in payload["messages"]] == ["loom_intro", "loom_url"]
    assert [item["strategy_id"] for item in payload["messages"]] == ["loom_link", "loom_link"]


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
        strategy_weights={"loom": {"loom_link": 100, "loom_mp4": 0}},
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
        "loom": {"loom_link": 100, "loom_mp4": 0}
    }

    assert stats_response.status_code == 200
    items = {item["strategy_id"]: item for item in stats_response.json()["items"]}
    assert items["loom_link"]["weight"] == 100
    assert items["loom_mp4"]["weight"] == 0

    assert pending_response.status_code == 200
    assert [item["strategy_id"] for item in pending_response.json()["messages"]] == [
        "loom_link",
        "loom_link",
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

    contadores_endpoints.send_loom_sequence(lead=lead, config=config, strategy_id="loom_link")
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
    assert items["loom_link"]["assigned"] == 1
    assert items["loom_link"]["sent"] == 1
    assert items["loom_link"]["delivered"] == 1
    assert items["loom_link"]["reached_calendly"] == 1
    assert items["loom_link"]["booked"] == 1
    assert items["loom_link"]["calendly_rate"] == 1
    assert items["loom_mp4"]["assigned"] == 0


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
    force_loom_strategy(monkeypatch, "loom_link")
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
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["loom_intro", "loom_url"]
    assert pending.json()["messages"][0]["text"] == contadores_endpoints.build_loom_intro_text()
    assert pending.json()["messages"][1]["text"] == config.loom_url


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


def test_contadores_detail_uses_effective_stage_over_raw_needs_human(monkeypatch, tmp_path) -> None:
    """Calendly/booked milestones must win over a stale raw needs_human stage."""
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
    assert response.json()["lead"]["stage"] == "calendly_sent"
    assert response.json()["lead"]["raw_stage"] == "needs_human"


def test_contadores_send_calendly_clears_manual_pause(monkeypatch, tmp_path) -> None:
    """Manual Calendly send should restore the lead to the Calendly-sent lane."""
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
    assert payload["lead"]["stage"] == "calendly_sent"
    assert payload["lead"]["raw_stage"] == "calendly_sent"
    assert payload["lead"]["automation_paused"] is False
    assert payload["lead"]["automation_paused_reason"] is None
    assert payload["lead"]["needs_human_notified_at"] is None
    assert payload["queued_message_ids"] == [1, 2]

    assert detail.status_code == 200
    assert detail.json()["lead"]["stage"] == "calendly_sent"
    assert detail.json()["lead"]["calendly_url"] == "https://calendly.com/yoelkravchuk/konecta-meet"
    assert "calendly_tracking_token" not in detail.json()["lead"]
    assert detail.json()["lead"]["automation_paused"] is False
    assert [item["sequence_step"] for item in pending.json()["messages"]] == ["calendly_intro", "calendly_url"]
    assert pending.json()["messages"][1]["text"] == "https://calendly.com/yoelkravchuk/konecta-meet"


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
    link_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-loom-link-filter",
        phone="+5491555555563",
        full_name="Loom Link Lead",
    )
    mp4_lead = ContadoresLead.upsert(
        external_lead_id="sheet-row-loom-mp4-filter",
        phone="+5491555555564",
        full_name="MP4 Lead",
    )
    contadores_endpoints.send_loom_sequence(lead=link_lead, config=config, strategy_id="loom_link")
    contadores_endpoints.send_loom_sequence(lead=mp4_lead, config=config, strategy_id="loom_mp4")
    ContadoresLead.update_flow_state(
        link_lead.id,
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
