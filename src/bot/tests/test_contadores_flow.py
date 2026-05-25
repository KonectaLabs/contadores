"""Unit tests for Contadores-specific bot helpers."""

from __future__ import annotations

import asyncio
import json
from io import BytesIO
from types import SimpleNamespace

import httpx
import main as bot_main
import openpyxl
import utils
from providers import DeliveryReceipt, EmailInboundEvent, WhatsAppInboundEvent, WhatsAppMessageStatusEvent
from utils import (
    PendingContadoresAlertItem,
    PendingContadoresDeliveryMessage,
    dispatch_one_contadores_message,
    dispatch_pending_contadores_messages,
    process_whatsapp_message_status_event,
    read_xlsx_sheet_rows,
    send_contadores_pending_alerts,
)
from webhook_inbox import WhatsAppInboundInbox


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

    async def fake_import_contadores_sheet_rows(client, *, funnel_id="contadores", rows):
        del client
        del funnel_id
        imported_batches.append(rows)
        return {"imported": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(utils, "fetch_contadores_config", fake_fetch_contadores_config)
    monkeypatch.setattr(utils, "fetch_contadores_sheet_rows", fake_fetch_contadores_sheet_rows)
    monkeypatch.setattr(utils, "import_contadores_sheet_rows", fake_import_contadores_sheet_rows)
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


def test_read_xlsx_sheet_rows_uses_first_importable_worksheet() -> None:
    """Google Sheets exports can include an empty first tab before the lead rows."""
    workbook = openpyxl.Workbook()
    empty_sheet = workbook.active
    empty_sheet.title = "Sheet1"

    leads_sheet = workbook.create_sheet("Formulario sin titulo")
    leads_sheet.append(["id", "created_time", "platform", "email", "full_name", "phone_number", "lead_status"])
    leads_sheet.append(["lead-1", "2026-04-27T10:00:00Z", "ig", "one@example.com", "Lead One", "p:+5491111111111", "CREATED"])
    leads_sheet.append(["lead-2", "2026-04-27T10:05:00Z", "fb", "two@example.com", "Lead Two", "p:+5491222222222", "CREATED"])

    output = BytesIO()
    workbook.save(output)
    workbook.close()

    rows = read_xlsx_sheet_rows(output.getvalue())

    assert [row["id"] for row in rows] == ["lead-1", "lead-2"]
    assert rows[0]["full_name"] == "Lead One"
    assert rows[1]["phone_number"] == "p:+5491222222222"


def test_run_contadores_sheet_sync_iteration_uses_configured_sheet(monkeypatch) -> None:
    """The poller should always import from the configured sheet."""
    imported_batches: list[list[dict[str, str | None]]] = []

    async def fake_fetch_contadores_config(client):
        del client
        return SimpleNamespace(enabled=True, sheet_url="https://sheet", sheet_gid="0")

    async def fake_fetch_contadores_sheet_rows(*, config):
        del config
        return [
            {
                "id": "lead-1",
                "phone_number": "+5491111111111",
                "full_name": "Lead One",
                "is_contactado": "FALSE",
            }
        ]

    async def fake_import_contadores_sheet_rows(client, *, funnel_id="contadores", rows):
        del client
        del funnel_id
        imported_batches.append(rows)
        return {"imported": 1, "updated": 0, "skipped": 0}

    monkeypatch.setattr(utils, "fetch_contadores_config", fake_fetch_contadores_config)
    monkeypatch.setattr(utils, "fetch_contadores_sheet_rows", fake_fetch_contadores_sheet_rows)
    monkeypatch.setattr(utils, "import_contadores_sheet_rows", fake_import_contadores_sheet_rows)

    result = asyncio.run(utils.run_contadores_sheet_sync_iteration(SimpleNamespace()))

    assert result["status"] == "ok"
    assert result["submitted"] == 1
    assert imported_batches[0][0]["id"] == "lead-1"
    assert imported_batches[0][0]["phone_number"] == "+5491111111111"
    assert imported_batches[0][0]["full_name"] == "Lead One"


def test_process_whatsapp_inbound_event_forwards_profile_name(monkeypatch) -> None:
    """The bot should preserve the WhatsApp profile name when it calls the backend."""
    seen_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(utils, "BACKEND_BASE_URL", "http://backend")

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={"status": "processed", "route": "general", "lead_id": "lead-1"},
        )

    event = WhatsAppInboundEvent(
        phone="5491111111111",
        text="Hola",
        profile_name="Ana WhatsApp",
        external_id="wamid.profile.1",
    )

    async def run() -> dict[str, object]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await utils.process_whatsapp_inbound_event(client, event=event)

    result = asyncio.run(run())

    assert seen_payloads == [
        {
            "phone": "5491111111111",
            "text": "Hola",
            "profile_name": "Ana WhatsApp",
            "external_id": "wamid.profile.1",
            "in_reply_to": None,
            "referral": None,
            "media_type": None,
            "media_path": None,
            "media_caption": None,
            "media_mime_type": None,
            "media_filename": None,
            "media_sha256": None,
            "media_id": None,
        }
    ]
    assert result["profile_name"] == "Ana WhatsApp"


def test_whatsapp_inbound_is_queued_when_backend_delivery_fails(monkeypatch, tmp_path) -> None:
    """Inbound webhooks should survive backend outages for later replay."""
    monkeypatch.setattr(utils, "BACKEND_BASE_URL", "http://backend")
    inbox = WhatsAppInboundInbox(tmp_path / "inbox.sqlite")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/contadores/whatsapp/inbound"
        if calls == 1:
            return httpx.Response(500, json={"detail": "backend down"})
        return httpx.Response(
            200,
            json={"status": "processed", "route": "contadores", "lead_id": "lead-1"},
        )

    event = WhatsAppInboundEvent(
        phone="5491111111111",
        text="Hola",
        profile_name="Ana WhatsApp",
        external_id="wamid.queue.1",
    )

    async def run() -> tuple[dict[str, object], dict[str, int]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            queued = await bot_main.handle_whatsapp_inbound(
                backend_client=client,
                event=event,
                inbox=inbox,
            )
            replayed = await bot_main.replay_pending_whatsapp_inbound_events(
                backend_client=client,
                inbox=inbox,
            )
        return queued, replayed

    queued_result, replay_result = asyncio.run(run())

    assert queued_result["status"] == "queued"
    assert replay_result["delivered"] == 1
    assert inbox.pending_count() == 0
    assert calls == 2


def test_whatsapp_inbound_duplicate_after_delivery_is_not_reposted(monkeypatch, tmp_path) -> None:
    """Meta retries after a delivered event should be absorbed by the bot inbox."""
    monkeypatch.setattr(utils, "BACKEND_BASE_URL", "http://backend")
    inbox = WhatsAppInboundInbox(tmp_path / "inbox.sqlite")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"status": "processed", "route": "contadores", "lead_id": "lead-1"},
        )

    event = WhatsAppInboundEvent(
        phone="5491111111111",
        text="Hola",
        external_id="wamid.once.1",
    )

    async def run() -> tuple[dict[str, object], dict[str, object]]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            first = await bot_main.handle_whatsapp_inbound(
                backend_client=client,
                event=event,
                inbox=inbox,
            )
            second = await bot_main.handle_whatsapp_inbound(
                backend_client=client,
                event=event,
                inbox=inbox,
            )
        return first, second

    first_result, second_result = asyncio.run(run())

    assert first_result["status"] == "processed"
    assert second_result["status"] == "duplicate"
    assert inbox.pending_count() == 0
    assert calls == 1


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
            whatsapp_template_name="contadores_intro_nombre_pais_es_v1",
            whatsapp_template_language="es",
            whatsapp_template_body_params=["Lead", "Argentina"],
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


def test_dispatch_pending_contadores_messages_persists_send_failure(monkeypatch) -> None:
    """Failed sends should be reported back to the backend for retry/alerting."""
    failure_calls: list[tuple[int, str]] = []

    async def fake_dispatch_one_contadores_message(*, item, whatsapp_provider):
        del item
        del whatsapp_provider
        raise RuntimeError("invalid recipient phone number")

    async def fake_record_backend_contadores_message_failure(client, *, message_id: int, error: str, **kwargs):
        del client
        del kwargs
        failure_calls.append((message_id, error))

    monkeypatch.setattr(utils, "dispatch_one_contadores_message", fake_dispatch_one_contadores_message)
    monkeypatch.setattr(
        utils,
        "record_backend_contadores_message_failure",
        fake_record_backend_contadores_message_failure,
    )

    pending = [
        PendingContadoresDeliveryMessage(
            message_id=31,
            lead_id="lead-3",
            external_lead_id="sheet-3",
            phone="+5491333333333",
            normalized_phone="5491333333333",
            full_name="Lead Three",
            text="Hola",
            dispatch_after="2026-04-21T10:00:00Z",
            created_at="2026-04-21T10:00:00Z",
            sequence_step="opener",
        )
    ]

    results = asyncio.run(
        dispatch_pending_contadores_messages(
            SimpleNamespace(),
            pending=pending,
            whatsapp_provider=SimpleNamespace(configured=True),
        )
    )

    assert [item.status for item in results] == ["failed"]
    assert failure_calls == [(31, "invalid recipient phone number")]


def test_dispatch_one_contadores_message_uses_template_body_params() -> None:
    """Contadores template-backed steps should pass approved template variables."""
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
        text=(
            "Hola Eva, llenaste el formulario para contadores de Argentina sobre como conseguir "
            "clientes a tu whatsapp. es correcto?"
        ),
        dispatch_after="2026-04-21T10:00:00Z",
        created_at="2026-04-21T10:00:00Z",
        sequence_step="opener",
        whatsapp_template_name="contadores_intro_nombre_pais_es_v1",
        whatsapp_template_language="es",
        whatsapp_template_body_params=["Eva", "Argentina"],
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
            "contadores_intro_nombre_pais_es_v1",
            "es",
            ["Eva", "Argentina"],
            (
                "Hola Eva, llenaste el formulario para contadores de Argentina sobre como conseguir "
                "clientes a tu whatsapp. es correcto?"
            ),
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


def test_dispatch_one_contadores_message_uses_template_body_params() -> None:
    """Campaign templates should pass positional params through to WhatsApp."""
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
        return DeliveryReceipt(external_id="wa-template-promo", delivered_text=delivered_text)

    item = PendingContadoresDeliveryMessage(
        message_id=22,
        lead_id="lead-promo",
        external_lead_id="sheet-promo",
        phone="+5491333333333",
        normalized_phone="5491333333333",
        full_name="Karen Acosta",
        text="Hola Karen, promo para contadores de Ecuador:",
        dispatch_after="2026-05-05T10:00:00Z",
        created_at="2026-05-05T10:00:00Z",
        sequence_step="promo_web_profesional_20260505",
        whatsapp_template_name="konecta_promo_web_profesional_es_v1",
        whatsapp_template_language="es",
        whatsapp_template_body_params=["Karen", "contadores", "Ecuador", "29"],
    )

    receipt = asyncio.run(
        dispatch_one_contadores_message(
            item=item,
            whatsapp_provider=SimpleNamespace(send_template_message=fake_send_template_message),
        )
    )

    assert receipt.external_id == "wa-template-promo"
    assert template_calls == [
        (
            "+5491333333333",
            "konecta_promo_web_profesional_es_v1",
            "es",
            ["Karen", "contadores", "Ecuador", "29"],
            "Hola Karen, promo para contadores de Ecuador:",
        )
    ]


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


def test_dispatch_one_contadores_message_sends_document_media() -> None:
    """Manual file rows should use WhatsApp generic media dispatch."""
    media_calls: list[dict[str, str | None]] = []

    async def fake_send_media(**kwargs) -> DeliveryReceipt:
        media_calls.append(kwargs)
        return DeliveryReceipt(external_id="wa-document-1", delivered_text=kwargs.get("delivered_text"))

    async def fake_send_message(to: str, text: str) -> DeliveryReceipt:
        raise AssertionError(f"send_message should not be used for document media: {to} {text}")

    item = PendingContadoresDeliveryMessage(
        message_id=23,
        lead_id="lead-3",
        external_lead_id="sheet-3",
        phone="+5491333333333",
        normalized_phone="5491333333333",
        full_name="Lead Three",
        text="Te mando el presupuesto",
        dispatch_after="2026-04-21T10:00:00Z",
        created_at="2026-04-21T10:00:00Z",
        sequence_step="manual",
        media_type="document",
        media_path="data/contadores/outbound_media/lead-3/presupuesto.pdf",
        media_caption="Te mando el presupuesto",
        media_mime_type="application/pdf",
        media_filename="presupuesto.pdf",
    )

    receipt = asyncio.run(
        dispatch_one_contadores_message(
            item=item,
            whatsapp_provider=SimpleNamespace(
                send_media=fake_send_media,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-document-1"
    assert media_calls == [
        {
            "to": "+5491333333333",
            "media_type": "document",
            "media_path": "data/contadores/outbound_media/lead-3/presupuesto.pdf",
            "caption": "Te mando el presupuesto",
            "filename": "presupuesto.pdf",
            "mime_type": "application/pdf",
            "delivered_text": "Te mando el presupuesto",
        }
    ]


def test_send_contadores_pending_alerts_includes_direct_lead_link(monkeypatch) -> None:
    """Human-review alert emails should link straight to the lead detail view."""
    sent_calls: list[dict[str, str | None]] = []
    marked_leads: list[str] = []

    async def fake_fetch_pending_contadores_alerts(client, *, funnel_id="contadores"):
        del client
        del funnel_id
        return [
            PendingContadoresAlertItem(
                lead_id="7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe",
                full_name="Facu",
                phone="+5491153484587",
                email=None,
                stage="needs_human",
                latest_inbound_text="Ok ya lo vi, pero tengo dudas",
                conversation_transcript=(
                    "2026-05-06T12:50:00Z - Konecta: Te paso el video\n"
                    "2026-05-06T13:04:00Z - Lead: Ok ya lo vi, pero tengo dudas"
                ),
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
        "https://crm.fgoiriz.com/?section=contadores&contadores_lead=7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe"
    ) in sent_calls[0]["text"]
    assert "Conversacion reciente:" in sent_calls[0]["text"]
    assert "2026-05-06T12:50:00Z - Konecta: Te paso el video" in sent_calls[0]["text"]
    assert "2026-05-06T13:04:00Z - Lead: Ok ya lo vi, pero tengo dudas" in sent_calls[0]["text"]


def test_send_contadores_pending_alerts_handles_provider_rejections(monkeypatch) -> None:
    """One blocked alert recipient should not crash the worker or block other recipients."""
    sent_calls: list[dict[str, str | None]] = []
    marked_leads: list[str] = []

    async def fake_fetch_pending_contadores_alerts(client, *, funnel_id="contadores"):
        del client
        del funnel_id
        return [
            PendingContadoresAlertItem(
                lead_id="7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe",
                full_name="Facu",
                phone="+5491153484587",
                email=None,
                stage="needs_human",
                latest_inbound_text="Tengo dudas",
                conversation_transcript="Lead: Tengo dudas",
                reason="Pidio revision humana.",
                alert_emails=["blocked@example.com", "ops@example.com"],
            )
        ]

    async def fake_ensure_alert_inbox():
        return SimpleNamespace(inbox_id="alerts-inbox-1", inbox_address="alerts@example.com")

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        if kwargs["recipient"] == "blocked@example.com":
            raise RuntimeError("Message rejected: recipient blocked")
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

    assert outcomes == [
        {
            "lead_id": "7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe",
            "status": "sent",
            "recipients": ["blocked@example.com", "ops@example.com"],
            "failed_recipients": ["blocked@example.com"],
        }
    ]
    assert marked_leads == ["7bc8899e-f7ed-4c0b-90f4-ce9739b9b4fe"]
    assert [call["recipient"] for call in sent_calls] == ["blocked@example.com", "ops@example.com"]


def test_send_contadores_pending_alerts_handles_runtime_fallback_alert(monkeypatch) -> None:
    """Runtime Codex fallback alerts should email the error and mark the runtime alert row."""
    sent_calls: list[dict[str, str | None]] = []
    marked_runtime_alerts: list[int] = []
    marked_leads: list[str] = []

    async def fake_fetch_pending_contadores_alerts(client, *, funnel_id="contadores"):
        del client
        del funnel_id
        return [
            PendingContadoresAlertItem(
                lead_id="runtime-lead-1",
                full_name="Facu",
                phone="+5491153484587",
                email=None,
                stage="runtime_alert",
                automation_paused_reason="codex_fallback",
                latest_inbound_text="Gracias pero no estoy interesado en una pagina web",
                reason="Codex fallo y se uso fallback.",
                alert_emails=["ops@example.com"],
                alert_kind="runtime",
                runtime_alert_id=123,
                funnel_label="Abogados",
                codex_error="Codex failed: timeout",
                fallback_action="close_lead",
            )
        ]

    async def fake_ensure_alert_inbox():
        return SimpleNamespace(inbox_id="alerts-inbox-1", inbox_address="alerts@example.com")

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        return DeliveryReceipt(external_id="agentmail-runtime-alert-1")

    async def fake_mark_backend_contadores_runtime_alert_sent(client, *, runtime_alert_id: int, receipt=None):
        del client
        del receipt
        marked_runtime_alerts.append(runtime_alert_id)

    async def fake_mark_backend_contadores_alert_sent(client, *, lead_id: str):
        del client
        marked_leads.append(lead_id)

    monkeypatch.setattr(utils, "fetch_pending_contadores_alerts", fake_fetch_pending_contadores_alerts)
    monkeypatch.setattr(
        utils,
        "mark_backend_contadores_runtime_alert_sent",
        fake_mark_backend_contadores_runtime_alert_sent,
    )
    monkeypatch.setattr(utils, "mark_backend_contadores_alert_sent", fake_mark_backend_contadores_alert_sent)

    outcomes = asyncio.run(
        send_contadores_pending_alerts(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_alert_inbox=fake_ensure_alert_inbox,
                send_message=fake_send_message,
            ),
            funnel_label="Contadores",
        )
    )

    assert [item["status"] for item in outcomes] == ["sent"]
    assert marked_runtime_alerts == [123]
    assert marked_leads == []
    assert sent_calls[0]["subject"] == "[Abogados] codex_fallback +5491153484587"
    assert "Resumen operativo:" in sent_calls[0]["text"]
    assert "ChatGPT Codex se desconecto, pero el bot uso el fallback configurado." in sent_calls[0]["text"]
    assert "Impacto en el lead:" in sent_calls[0]["text"]
    assert "No se pauso solo por el error de Codex." in sent_calls[0]["text"]
    assert "El fallback cerro el lead porque detecto rechazo o desinteres." in sent_calls[0]["text"]
    assert "Accion aplicada: close_lead" in sent_calls[0]["text"]
    assert "Que hacer ahora:" in sent_calls[0]["text"]
    assert "Reautenticacion ChatGPT Codex:" in sent_calls[0]["text"]
    assert "Detalle tecnico:" in sent_calls[0]["text"]
    assert "Error Codex: Codex failed: timeout" in sent_calls[0]["text"]
    assert "Link: https://auth.openai.com/codex/device" in sent_calls[0]["text"]
    assert "codex login --device-auth" in sent_calls[0]["text"]
    assert "Lead link: https://crm.fgoiriz.com/?section=contadores&contadores_lead=runtime-lead-1" in sent_calls[0]["text"]


def test_agentmail_webhook_forwards_operator_reply_and_acknowledges(monkeypatch) -> None:
    """AgentMail replies should be passed to the backend runtime-alert resolver."""
    forwarded_events: list[EmailInboundEvent] = []
    acknowledged: list[dict[str, str]] = []

    event = EmailInboundEvent(
        inbox_id="alerts-inbox",
        message_id="email-reply-1",
        from_email="facu@example.com",
        plain_text="Respuesta: Hasta el viernes",
        thread_id="thread-1",
    )

    class FakeEmailProvider:
        def verify_webhook_payload(self, *, payload: str, headers: dict[str, str]) -> dict[str, object]:
            assert json.loads(payload) == {"type": "message.received"}
            assert headers["x-test"] == "1"
            return {"type": "message.received", "message": {"message_id": "email-reply-1"}}

        def build_inbound_event(self, payload: dict[str, object]) -> EmailInboundEvent:
            assert payload["type"] == "message.received"
            return event

        async def acknowledge_message(self, *, inbox_id: str, message_id: str) -> None:
            acknowledged.append({"inbox_id": inbox_id, "message_id": message_id})

    async def fake_process_contadores_alert_email_reply(client, *, event: EmailInboundEvent):
        del client
        forwarded_events.append(event)
        return {"status": "processed", "queued_message_ids": [7]}

    monkeypatch.setattr(bot_main, "process_contadores_alert_email_reply", fake_process_contadores_alert_email_reply)

    result = asyncio.run(
        bot_main.handle_agentmail_webhook(
            backend_client=SimpleNamespace(),
            email_provider=FakeEmailProvider(),
            raw_body=b'{"type": "message.received"}',
            headers={"x-test": "1"},
        )
    )

    assert result == {"status": "processed", "queued_message_ids": [7]}
    assert forwarded_events == [event]
    assert acknowledged == [{"inbox_id": "alerts-inbox", "message_id": "email-reply-1"}]


def test_process_whatsapp_message_status_event_ignores_missing_contadores_message(monkeypatch) -> None:
    """Unknown WhatsApp delivery ids should be ignored after the app split."""

    async def fake_mark_backend_contadores_message_status(client, *, external_id: str, status: str, **kwargs):
        del client, external_id, status, kwargs
        request = httpx.Request("PUT", "http://backend/api/contadores/messages/delivery/by-external-id")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    async def fake_mark_backend_client_lead_delivery_status(client, *, external_id: str, status: str, **kwargs):
        del client, external_id, status, kwargs
        request = httpx.Request("PUT", "http://backend/api/client-lead-deliveries/delivery/by-external-id")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr(utils, "mark_backend_contadores_message_status", fake_mark_backend_contadores_message_status)
    monkeypatch.setattr(
        utils,
        "mark_backend_client_lead_delivery_status",
        fake_mark_backend_client_lead_delivery_status,
    )

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
