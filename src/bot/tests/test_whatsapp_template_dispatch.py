"""Unit tests for WhatsApp template-first dispatch behavior."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import utils
from providers import DeliveryReceipt, WhatsAppMessageStatusEvent
from utils import (
    PendingDeliveryMessage,
    dispatch_one_message,
    dispatch_pending_messages,
    mark_backend_message_sent,
    process_whatsapp_message_status_event,
)


def test_dispatch_one_message_uses_intro_template_before_first_inbound() -> None:
    calls: list[tuple[str, str, str, str, str | None]] = []

    async def fake_send_intro_template(
        *,
        to: str,
        template_name: str | None,
        template_language: str | None,
        client_name: str | None,
        company_url: str | None,
    ):
        calls.append(
            (
                to,
                template_name or "",
                template_language or "",
                client_name or "",
                company_url,
            )
        )
        return DeliveryReceipt(external_id="wa-template-1", delivered_text="template-text")

    async def fake_send_message(to: str, text: str):
        raise AssertionError("send_message should not be used before first inbound")

    item = PendingDeliveryMessage(
        message_id=101,
        company_id="company-1",
        company_name="Acme",
        company_source_url="https://acme.com",
        company_language="es",
        contact_id="contact-wa-1",
        contact_has_inbound=False,
        contact_type="whatsapp",
        contact_value="+5491111111111",
        text="ignored outbound text",
        dispatch_after="2026-02-25T10:00:00Z",
        timestamp="2026-02-25T10:00:00Z",
        whatsapp_template_name="konecta_intro_es_v2",
        whatsapp_template_language="es",
        whatsapp_template_client_name="Sofia",
        whatsapp_template_company_url="https://acme.com",
    )

    receipt = asyncio.run(
        dispatch_one_message(
            item=item,
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(
                send_intro_template=fake_send_intro_template,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-template-1"
    assert calls == [
        (
            "+5491111111111",
            "konecta_intro_es_v2",
            "es",
            "Sofia",
            "https://acme.com",
        )
    ]


def test_dispatch_one_message_uses_text_after_first_inbound() -> None:
    calls: list[tuple[str, str]] = []

    async def fake_send_intro_template(
        *,
        to: str,
        template_name: str | None,
        template_language: str | None,
        client_name: str | None,
        company_url: str | None,
    ):
        raise AssertionError("send_intro_template should not be used after inbound exists")

    async def fake_send_message(to: str, text: str):
        calls.append((to, text))
        return DeliveryReceipt(external_id="wa-text-1", delivered_text=text)

    item = PendingDeliveryMessage(
        message_id=102,
        company_id="company-1",
        company_name="Acme",
        company_source_url="https://acme.com",
        company_language="es",
        contact_id="contact-wa-2",
        contact_has_inbound=True,
        contact_type="whatsapp",
        contact_value="+5491222222222",
        text="respuesta libre",
        dispatch_after="2026-02-25T10:00:00Z",
        timestamp="2026-02-25T10:00:00Z",
    )

    receipt = asyncio.run(
        dispatch_one_message(
            item=item,
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(
                send_intro_template=fake_send_intro_template,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-text-1"
    assert calls == [("+5491222222222", "respuesta libre")]


def test_dispatch_one_message_falls_back_to_text_when_template_payload_is_missing() -> None:
    calls: list[tuple[str, str]] = []

    async def fake_send_intro_template(
        *,
        to: str,
        template_name: str | None,
        template_language: str | None,
        client_name: str | None,
        company_url: str | None,
    ):
        raise AssertionError("send_intro_template should not be used when payload is missing")

    async def fake_send_message(to: str, text: str):
        calls.append((to, text))
        return DeliveryReceipt(external_id="wa-text-2", delivered_text=text)

    item = PendingDeliveryMessage(
        message_id=120,
        company_id="company-1",
        company_name="Acme",
        company_source_url="https://acme.com",
        company_language="es",
        contact_id="contact-wa-legacy",
        contact_has_inbound=False,
        contact_type="whatsapp",
        contact_value="+5491444444444",
        text="legacy first outbound text",
        dispatch_after="2026-02-25T10:00:00Z",
        timestamp="2026-02-25T10:00:00Z",
    )

    receipt = asyncio.run(
        dispatch_one_message(
            item=item,
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(
                send_intro_template=fake_send_intro_template,
                send_message=fake_send_message,
            ),
        )
    )

    assert receipt.external_id == "wa-text-2"
    assert calls == [("+5491444444444", "legacy first outbound text")]


def test_dispatch_pending_messages_syncs_delivered_text_to_backend(monkeypatch) -> None:
    update_calls: list[str] = []
    delivery_calls: list[str] = []

    async def fake_dispatch_one_message(**kwargs):
        return DeliveryReceipt(external_id="wa-template-2", delivered_text="template enviado")

    async def fake_update_backend_message_text(*args, **kwargs):
        update_calls.append(kwargs["text"])

    async def fake_mark_backend_message_sent(*args, **kwargs):
        delivery_calls.append(kwargs["receipt"].external_id)

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        return 0.0

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "update_backend_message_text", fake_update_backend_message_text)
    monkeypatch.setattr(utils, "mark_backend_message_sent", fake_mark_backend_message_sent)

    pending = [
        PendingDeliveryMessage(
            message_id=103,
            company_id="company-1",
            company_name="Acme",
            company_source_url="https://acme.com",
            company_language="es",
            contact_id="contact-wa-3",
            contact_has_inbound=False,
            contact_type="whatsapp",
            contact_value="+5491333333333",
            text="texto original distinto",
            dispatch_after="2026-02-25T10:00:00Z",
            timestamp="2026-02-25T10:00:00Z",
        )
    ]

    results = asyncio.run(
        dispatch_pending_messages(
            SimpleNamespace(),
            pending=pending,
            email_provider=SimpleNamespace(configured=True),
            whatsapp_provider=SimpleNamespace(configured=True),
        )
    )

    assert [item.status for item in results] == ["delivered"]
    assert update_calls == ["template enviado"]
    assert delivery_calls == ["wa-template-2"]


def test_dispatch_pending_messages_defers_whatsapp_until_delay_elapsed(monkeypatch) -> None:
    delay_keys: list[str] = []
    dispatch_calls: list[int] = []

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        delay_keys.append(delay_key)
        return 42.0

    async def fake_dispatch_one_message(**kwargs):
        dispatch_calls.append(kwargs["item"].message_id)
        return DeliveryReceipt(external_id="wa-should-not-send")

    async def fake_mark_backend_message_sent(*args, **kwargs):
        return None

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "mark_backend_message_sent", fake_mark_backend_message_sent)

    pending = [
        PendingDeliveryMessage(
            message_id=104,
            company_id="company-1",
            company_name="Acme",
            company_source_url="https://acme.com",
            company_language="es",
            contact_id="contact-wa-delay",
            contact_has_inbound=False,
            contact_type="whatsapp",
            contact_value="+5491333333999",
            text="mensaje con delay",
            dispatch_after="2026-02-25T10:00:00Z",
            timestamp="2026-02-25T10:00:00Z",
        )
    ]

    results = asyncio.run(
        dispatch_pending_messages(
            SimpleNamespace(),
            pending=pending,
            email_provider=SimpleNamespace(configured=True),
            whatsapp_provider=SimpleNamespace(configured=True),
        )
    )

    assert delay_keys == ["wa-message:104"]
    assert dispatch_calls == []
    assert [item.status for item in results] == ["deferred"]
    assert [item.error for item in results] == ["whatsapp_delay_not_elapsed"]
    assert [item.wait_seconds for item in results] == [42.0]


def test_dispatch_pending_messages_applies_delay_to_intro_template_and_text(monkeypatch) -> None:
    delay_keys: list[str] = []
    dispatched_message_ids: list[int] = []

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        delay_keys.append(delay_key)
        return 0.0

    async def fake_dispatch_one_message(**kwargs):
        item = kwargs["item"]
        dispatched_message_ids.append(item.message_id)
        return DeliveryReceipt(external_id=f"wa-{item.message_id}", delivered_text=item.text)

    async def fake_mark_backend_message_sent(*args, **kwargs):
        return None

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "mark_backend_message_sent", fake_mark_backend_message_sent)

    pending = [
        PendingDeliveryMessage(
            message_id=201,
            company_id="company-1",
            company_name="Acme",
            company_source_url="https://acme.com",
            company_language="es",
            contact_id="contact-wa-template",
            contact_has_inbound=False,
            contact_type="whatsapp",
            contact_value="+5491333333001",
            text="texto fallback template",
            dispatch_after="2026-02-25T10:00:00Z",
            timestamp="2026-02-25T10:00:00Z",
            whatsapp_template_name="konecta_intro_es_v2",
            whatsapp_template_language="es",
            whatsapp_template_client_name="Sofia",
            whatsapp_template_company_url="https://acme.com",
        ),
        PendingDeliveryMessage(
            message_id=202,
            company_id="company-1",
            company_name="Acme",
            company_source_url="https://acme.com",
            company_language="es",
            contact_id="contact-wa-text",
            contact_has_inbound=True,
            contact_type="whatsapp",
            contact_value="+5491333333002",
            text="texto libre",
            dispatch_after="2026-02-25T10:00:00Z",
            timestamp="2026-02-25T10:00:00Z",
        ),
    ]

    results = asyncio.run(
        dispatch_pending_messages(
            SimpleNamespace(),
            pending=pending,
            email_provider=SimpleNamespace(configured=True),
            whatsapp_provider=SimpleNamespace(configured=True),
        )
    )

    assert delay_keys == ["wa-message:201", "wa-message:202"]
    assert dispatched_message_ids == [201, 202]
    assert [item.status for item in results] == ["delivered", "delivered"]


def test_mark_backend_message_sent_persists_sent_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/api/companies/company-1/contacts/contact-1/messages/7/delivery"
        assert json.loads(request.content.decode("utf-8")) == {
            "status": "sent",
            "external_id": "wamid.outbound.7",
            "inbox_id": None,
            "inbox_address": None,
            "thread_id": None,
            "rfc_message_id": None,
        }
        return httpx.Response(200, json={"id": 7, "delivery_status": "sent"})

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await mark_backend_message_sent(
                client,
                company_id="company-1",
                contact_id="contact-1",
                message_id=7,
                receipt=DeliveryReceipt(external_id="wamid.outbound.7"),
            )

    asyncio.run(run())


def test_process_whatsapp_message_status_event_preserves_sent_status() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        observed_paths.append(request.url.path)
        if request.url.path == "/api/contadores/messages/delivery/by-external-id":
            assert json.loads(request.content.decode("utf-8")) == {
                "external_id": "wamid.outbound.7",
                "status": "sent",
            }
            return httpx.Response(404, json={"detail": "Outbound Contadores message not found"})
        assert request.url.path == "/api/messages/delivery/by-external-id"
        assert json.loads(request.content.decode("utf-8")) == {
            "external_id": "wamid.outbound.7",
            "status": "sent",
        }
        return httpx.Response(200, json={"id": 7, "delivery_status": "sent"})

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await process_whatsapp_message_status_event(
                client,
                event=WhatsAppMessageStatusEvent(
                    external_id="wamid.outbound.7",
                    status="sent",
                ),
            )

    result = asyncio.run(run())

    assert observed_paths == [
        "/api/contadores/messages/delivery/by-external-id",
        "/api/messages/delivery/by-external-id",
    ]
    assert result == {"id": 7, "delivery_status": "sent", "provider_status": "sent", "route": "auditor"}


def test_process_whatsapp_message_status_event_maps_read_to_delivered_without_duplicate_delivery_label() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        observed_paths.append(request.url.path)
        if request.url.path == "/api/contadores/messages/delivery/by-external-id":
            assert json.loads(request.content.decode("utf-8")) == {
                "external_id": "wamid.outbound.8",
                "status": "delivered",
            }
            return httpx.Response(404, json={"detail": "Outbound Contadores message not found"})
        assert request.url.path == "/api/messages/delivery/by-external-id"
        assert json.loads(request.content.decode("utf-8")) == {
            "external_id": "wamid.outbound.8",
            "status": "delivered",
        }
        return httpx.Response(200, json={"id": 8, "delivery_status": "delivered"})

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await process_whatsapp_message_status_event(
                client,
                event=WhatsAppMessageStatusEvent(
                    external_id="wamid.outbound.8",
                    status="read",
                ),
            )

    result = asyncio.run(run())

    assert observed_paths == [
        "/api/contadores/messages/delivery/by-external-id",
        "/api/messages/delivery/by-external-id",
    ]
    assert result == {"id": 8, "delivery_status": "delivered", "provider_status": "read", "route": "auditor"}


def test_process_whatsapp_message_status_event_ignores_missing_backend_message() -> None:
    observed_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        observed_paths.append(request.url.path)
        assert request.url.path in {
            "/api/contadores/messages/delivery/by-external-id",
            "/api/messages/delivery/by-external-id",
        }
        return httpx.Response(404, json={"detail": "Outbound message not found for external_id"})

    async def run() -> dict[str, object]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await process_whatsapp_message_status_event(
                client,
                event=WhatsAppMessageStatusEvent(
                    external_id="wamid.missing.1",
                    status="delivered",
                ),
            )

    result = asyncio.run(run())

    assert observed_paths == [
        "/api/contadores/messages/delivery/by-external-id",
        "/api/messages/delivery/by-external-id",
    ]
    assert result == {
        "status": "ignored",
        "reason": "external_id_not_found",
        "external_id": "wamid.missing.1",
        "provider_status": "delivered",
    }
