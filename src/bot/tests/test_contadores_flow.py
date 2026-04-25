"""Unit tests for Contadores-specific bot helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import utils
from providers import DeliveryReceipt, WhatsAppMessageStatusEvent
from utils import (
    PendingContadoresAlertItem,
    PendingContadoresDeliveryMessage,
    dispatch_one_contadores_message,
    dispatch_pending_contadores_messages,
    process_whatsapp_message_status_event,
    send_contadores_pending_alerts,
)


def test_run_contadores_sheet_sync_iteration_imports_only_uncontacted_rows(monkeypatch) -> None:
    """The sheet poller should ignore contacted rows before hitting the backend."""
    imported_batches: list[list[dict[str, str | None]]] = []

    async def fake_fetch_contadores_config(client):
        del client
        return SimpleNamespace(enabled=True, sheet_url="https://sheet", sheet_gid="0")

    async def fake_fetch_contadores_sheet_rows(*, config):
        del config
        return [
            {
                "id": "lead-1",
                "created_time": "2026-04-21T10:00:00Z",
                "platform": "meta",
                "email": "lead-1@example.com",
                "full_name": "Lead One",
                "phone_number": "p:+5491111111111",
                "lead_status": "new",
                "is_contactado": "FALSE",
            },
            {
                "id": "lead-2",
                "created_time": "2026-04-21T10:05:00Z",
                "platform": "meta",
                "email": "lead-2@example.com",
                "full_name": "Lead Two",
                "phone_number": "p:+5491222222222",
                "lead_status": "new",
                "is_contactado": "TRUE",
            },
            {
                "id": "",
                "phone_number": "",
                "is_contactado": "FALSE",
            },
        ]

    async def fake_import_contadores_sheet_rows(client, *, rows):
        del client
        imported_batches.append(rows)
        return {"imported": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(utils, "fetch_contadores_config", fake_fetch_contadores_config)
    monkeypatch.setattr(utils, "fetch_contadores_sheet_rows", fake_fetch_contadores_sheet_rows)
    monkeypatch.setattr(utils, "import_contadores_sheet_rows", fake_import_contadores_sheet_rows)
    monkeypatch.setattr(utils, "CONTADORES_SOURCE_MODE", "live")

    result = asyncio.run(utils.run_contadores_sheet_sync_iteration(SimpleNamespace()))

    assert result["status"] == "ok"
    assert result["fetched"] == 3
    assert result["submitted"] == 1
    assert imported_batches == [[
        {
            "id": "lead-1",
            "created_time": "2026-04-21T10:00:00Z",
            "platform": "meta",
            "email": "lead-1@example.com",
            "full_name": "Lead One",
            "phone_number": "p:+5491111111111",
            "lead_status": "new",
            "is_contactado": "FALSE",
        }
    ]]


def test_run_contadores_sheet_sync_iteration_uses_testing_phone(monkeypatch) -> None:
    """Testing mode must not read the live sheet and should import the configured test lead."""
    imported_batches: list[list[dict[str, str | None]]] = []

    async def fake_fetch_contadores_config(client):
        del client
        return SimpleNamespace(enabled=True, sheet_url="https://sheet", sheet_gid="0")

    async def fail_if_sheet_is_fetched(*, config):
        raise AssertionError(f"testing mode should not fetch sheet rows: {config}")

    async def fake_import_contadores_sheet_rows(client, *, rows):
        del client
        imported_batches.append(rows)
        return {"imported": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(utils, "fetch_contadores_config", fake_fetch_contadores_config)
    monkeypatch.setattr(utils, "fetch_contadores_sheet_rows", fail_if_sheet_is_fetched)
    monkeypatch.setattr(utils, "import_contadores_sheet_rows", fake_import_contadores_sheet_rows)
    monkeypatch.setattr(utils, "CONTADORES_SOURCE_MODE", "testing")
    monkeypatch.setattr(utils, "CONTADORES_TEST_PHONE", "+5491111111111")
    monkeypatch.setattr(utils, "CONTADORES_TEST_NAME", "Lead Test")

    result = asyncio.run(utils.run_contadores_sheet_sync_iteration(SimpleNamespace()))

    assert result["status"] == "ok"
    assert result["source_mode"] == "testing"
    assert result["submitted"] == 1
    assert imported_batches[0][0]["id"] == "testing-5491111111111"
    assert imported_batches[0][0]["phone_number"] == "+5491111111111"
    assert imported_batches[0][0]["full_name"] == "Lead Test"


def test_dispatch_pending_contadores_messages_sends_immediately_without_random_delay(monkeypatch) -> None:
    """Contadores sequences should use backend timing only, not extra WhatsApp jitter."""
    update_calls: list[str] = []
    sent_calls: list[tuple[int, str]] = []

    async def fail_if_delay_called(delay_key: str) -> float:
        raise AssertionError(f"unexpected WhatsApp delay for Contadores: {delay_key}")

    async def fake_dispatch_one_contadores_message(*, item, whatsapp_provider):
        del whatsapp_provider
        return DeliveryReceipt(external_id=f"wa-{item.message_id}", delivered_text=f"{item.text} (rendered)")

    async def fake_update_backend_contadores_message_text(client, *, message_id: int, text: str):
        del client
        update_calls.append(f"{message_id}:{text}")

    async def fake_mark_backend_contadores_message_sent(client, *, message_id: int, receipt: DeliveryReceipt):
        del client
        sent_calls.append((message_id, receipt.external_id))

    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fail_if_delay_called)
    monkeypatch.setattr(utils, "dispatch_one_contadores_message", fake_dispatch_one_contadores_message)
    monkeypatch.setattr(utils, "update_backend_contadores_message_text", fake_update_backend_contadores_message_text)
    monkeypatch.setattr(utils, "mark_backend_contadores_message_sent", fake_mark_backend_contadores_message_sent)

    pending = [
        PendingContadoresDeliveryMessage(
            message_id=11,
            lead_id="lead-1",
            external_lead_id="sheet-1",
            phone="+5491111111111",
            normalized_phone="5491111111111",
            full_name="Lead One",
            text="Hola",
            dispatch_after="2026-04-21T10:00:00Z",
            created_at="2026-04-21T10:00:00Z",
            sequence_step="opener",
            whatsapp_template_name="contadores_intro_es_v2",
            whatsapp_template_language="es",
            whatsapp_template_body_params=[],
        ),
        PendingContadoresDeliveryMessage(
            message_id=12,
            lead_id="lead-1",
            external_lead_id="sheet-1",
            phone="+5491111111111",
            normalized_phone="5491111111111",
            full_name="Lead One",
            text="https://www.loom.com/share/example",
            dispatch_after="2026-04-21T10:00:01Z",
            created_at="2026-04-21T10:00:01Z",
            sequence_step="loom_url",
        ),
    ]

    results = asyncio.run(
        dispatch_pending_contadores_messages(
            SimpleNamespace(),
            pending=pending,
            whatsapp_provider=SimpleNamespace(configured=True),
        )
    )

    assert [item.status for item in results] == ["delivered", "delivered"]
    assert update_calls == [
        "11:Hola (rendered)",
        "12:https://www.loom.com/share/example (rendered)",
    ]
    assert sent_calls == [(11, "wa-11"), (12, "wa-12")]


def test_dispatch_one_contadores_message_uses_template_without_body_params() -> None:
    """Contadores template-backed steps should use approved templates with no variables."""
    template_calls: list[tuple[str, str, str, list[str], str | None]] = []

    async def fake_send_template_message(
        *,
        to: str,
        template_name: str,
        template_language: str,
        body_params: list[str],
        delivered_text: str | None = None,
    ) -> DeliveryReceipt:
        template_calls.append((to, template_name, template_language, body_params, delivered_text))
        return DeliveryReceipt(external_id="wa-template-1", delivered_text=delivered_text)

    async def fake_send_message(to: str, text: str) -> DeliveryReceipt:
        raise AssertionError(f"send_message should not be used for template opener: {to} {text}")

    item = PendingContadoresDeliveryMessage(
        message_id=21,
        lead_id="lead-2",
        external_lead_id="sheet-2",
        phone="+5491222222222",
        normalized_phone="5491222222222",
        full_name="Lead Two",
        text="Hola, llenaste el formulario para contadores sobre como conseguir clientes a tu whatsapp. Es correcto?",
        dispatch_after="2026-04-21T10:00:00Z",
        created_at="2026-04-21T10:00:00Z",
        sequence_step="opener",
        whatsapp_template_name="contadores_intro_es_v2",
        whatsapp_template_language="es",
        whatsapp_template_body_params=[],
    )

    receipt = asyncio.run(
        dispatch_one_contadores_message(
            item=item,
            whatsapp_provider=SimpleNamespace(
                send_template_message=fake_send_template_message,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-template-1"
    assert template_calls == [
        (
            "+5491222222222",
            "contadores_intro_es_v2",
            "es",
            [],
            "Hola, llenaste el formulario para contadores sobre como conseguir clientes a tu whatsapp. Es correcto?",
        )
    ]

    item.sequence_step = "opener_followup_24h"
    item.text = "Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable"
    item.whatsapp_template_name = "contadores_opener_followup_24h_es_v1"

    receipt = asyncio.run(
        dispatch_one_contadores_message(
            item=item,
            whatsapp_provider=SimpleNamespace(
                send_template_message=fake_send_template_message,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-template-1"
    assert template_calls[-1] == (
        "+5491222222222",
        "contadores_opener_followup_24h_es_v1",
        "es",
        [],
        "Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable",
    )


def test_dispatch_one_contadores_message_sends_video_media() -> None:
    """Media strategy rows should use WhatsApp video dispatch."""
    video_calls: list[tuple[str, str, str | None, str | None]] = []

    async def fake_send_video(
        *,
        to: str,
        video_path: str,
        caption: str | None = None,
        delivered_text: str | None = None,
    ) -> DeliveryReceipt:
        video_calls.append((to, video_path, caption, delivered_text))
        return DeliveryReceipt(external_id="wa-video-1", delivered_text=delivered_text)

    async def fake_send_message(to: str, text: str) -> DeliveryReceipt:
        raise AssertionError(f"send_message should not be used for video media: {to} {text}")

    item = PendingContadoresDeliveryMessage(
        message_id=22,
        lead_id="lead-2",
        external_lead_id="sheet-2",
        phone="+5491222222222",
        normalized_phone="5491222222222",
        full_name="Lead Two",
        text="Video de explicación enviado por WhatsApp.",
        dispatch_after="2026-04-21T10:00:00Z",
        created_at="2026-04-21T10:00:00Z",
        sequence_step="loom_video",
        strategy_step="loom",
        strategy_id="loom_mp4",
        strategy_label="WhatsApp MP4",
        media_type="video",
        media_path="data/contadores/videos/loom_60_seconds_captions.mp4",
    )

    receipt = asyncio.run(
        dispatch_one_contadores_message(
            item=item,
            whatsapp_provider=SimpleNamespace(
                send_video=fake_send_video,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-video-1"
    assert video_calls == [
        (
            "+5491222222222",
            "data/contadores/videos/loom_60_seconds_captions.mp4",
            None,
            "Video de explicación enviado por WhatsApp.",
        )
    ]


def test_send_contadores_pending_alerts_includes_direct_lead_link(monkeypatch) -> None:
    """Human-review alert emails should link straight to the lead detail view."""
    sent_calls: list[dict[str, str | None]] = []
    marked_leads: list[str] = []

    async def fake_fetch_pending_contadores_alerts(client):
        del client
        return [
            PendingContadoresAlertItem(
                lead_id="7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe",
                full_name="Facu",
                phone="+5491153484587",
                email=None,
                stage="needs_human",
                latest_inbound_text="Ok ya lo vi, pero tengo dudas",
                reason="Tiene dudas, pregunta si sirve para consultoras y si hacen página.",
                alert_emails=["ops@example.com"],
            )
        ]

    async def fake_ensure_alert_inbox():
        return SimpleNamespace(inbox_id="alerts-inbox-1", inbox_address="alerts@example.com")

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        return DeliveryReceipt(external_id="agentmail-alert-1")

    async def fake_mark_backend_contadores_alert_sent(client, *, lead_id: str):
        del client
        marked_leads.append(lead_id)

    monkeypatch.setattr(utils, "fetch_pending_contadores_alerts", fake_fetch_pending_contadores_alerts)
    monkeypatch.setattr(utils, "mark_backend_contadores_alert_sent", fake_mark_backend_contadores_alert_sent)

    outcomes = asyncio.run(
        send_contadores_pending_alerts(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_alert_inbox=fake_ensure_alert_inbox,
                send_message=fake_send_message,
            ),
        )
    )

    assert [item["status"] for item in outcomes] == ["sent"]
    assert marked_leads == ["7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe"]
    assert len(sent_calls) == 1
    assert (
        "Lead link: "
        "https://chatterface.fgoiriz.com/?section=contadores&contadores_lead=7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe"
    ) in sent_calls[0]["text"]


def test_process_whatsapp_message_status_event_ignores_missing_contadores_message(monkeypatch) -> None:
    """Unknown WhatsApp delivery ids should be ignored after the app split."""

    async def fake_mark_backend_contadores_message_status(client, *, external_id: str, status: str):
        del client, external_id, status
        request = httpx.Request("PUT", "http://backend/api/contadores/messages/delivery/by-external-id")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(utils, "mark_backend_contadores_message_status", fake_mark_backend_contadores_message_status)

    result = asyncio.run(
        process_whatsapp_message_status_event(
            SimpleNamespace(),
            event=WhatsAppMessageStatusEvent(
                external_id="wamid.123",
                status="sent",
            ),
        )
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "external_id_not_found"
    assert result["provider_status"] == "sent"
