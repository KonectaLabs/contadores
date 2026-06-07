"""Unit tests for client lead Delivery bot helpers."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import utils
from providers import DeliveryReceipt, WhatsAppMessageStatusEvent, WhatsAppProvider


def test_fetch_and_dispatch_client_lead_notifications(monkeypatch) -> None:
    """The bot should send Delivery alerts through the configured Meta template."""
    monkeypatch.setattr(utils, "BACKEND_BASE_URL", "http://backend")
    requests: list[tuple[str, str, dict[str, object] | None]] = []
    sent_templates: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8")) if request.content else None
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/client-lead-deliveries/pending":
            return httpx.Response(
                200,
                json={
                    "notifications": [
                        {
                            "delivery_id": "delivery-1",
                            "source_id": "source-1",
                            "source_label": "MMB Ads",
                            "recipient_phone": "+5491122223333",
                            "normalized_recipient_phone": "5491122223333",
                            "template_name": "konecta_delivery_lead_alert_context_es",
                            "template_language": "es",
                            "template_body_params": [
                                "MMB Ads",
                                "Nombre: Ana Perez; WhatsApp: 5491111111111; Email: ana@example.com; Ciudad: Quito",
                                "https://wa.me/5491111111111",
                            ],
                            "delivered_text": (
                                "Nuevo Lead: MMB Ads.\n\n"
                                "datos del Lead:\n"
                                "Nombre: Ana Perez\n"
                                "WhatsApp: 5491111111111\n"
                                "Email: ana@example.com\n"
                                "Ciudad: Quito\n\n"
                                "Para abrir el chat:\n"
                                "https://wa.me/5491111111111\n"
                                "Para abrir el chat entrar al link."
                            ),
                        }
                    ]
                },
            )
        if request.url.path == "/api/client-lead-deliveries/delivery-1/delivery":
            return httpx.Response(200, json={"id": "delivery-1", "delivery_status": "sent"})
        return httpx.Response(404, json={"detail": "not found"})

    async def fake_send_template_message(**kwargs) -> DeliveryReceipt:
        sent_templates.append(kwargs)
        return DeliveryReceipt(external_id="wamid.delivery.1", delivered_text=kwargs.get("delivered_text"))

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            pending = await utils.fetch_pending_client_lead_notifications(client)
            results = await utils.dispatch_pending_client_lead_notifications(
                client,
                pending=pending,
                whatsapp_provider=SimpleNamespace(configured=True, send_template_message=fake_send_template_message),
            )
            return results

    results = asyncio.run(run())

    assert [result.status for result in results] == ["delivered"]
    assert sent_templates == [
        {
            "to": "+5491122223333",
            "template_name": "konecta_delivery_lead_alert_context_es",
            "template_language": "es",
            "body_params": [
                "MMB Ads",
                "Nombre: Ana Perez; WhatsApp: 5491111111111; Email: ana@example.com; Ciudad: Quito",
                "https://wa.me/5491111111111",
            ],
            "delivered_text": (
                "Nuevo Lead: MMB Ads.\n\n"
                "datos del Lead:\n"
                "Nombre: Ana Perez\n"
                "WhatsApp: 5491111111111\n"
                "Email: ana@example.com\n"
                "Ciudad: Quito\n\n"
                "Para abrir el chat:\n"
                "https://wa.me/5491111111111\n"
                "Para abrir el chat entrar al link."
            ),
        }
    ]
    assert requests[-1] == (
        "PUT",
        "/api/client-lead-deliveries/delivery-1/delivery",
        {
            "status": "sent",
            "external_id": "wamid.delivery.1",
            "sent_text": (
                "Nuevo Lead: MMB Ads.\n\n"
                "datos del Lead:\n"
                "Nombre: Ana Perez\n"
                "WhatsApp: 5491111111111\n"
                "Email: ana@example.com\n"
                "Ciudad: Quito\n\n"
                "Para abrir el chat:\n"
                "https://wa.me/5491111111111\n"
                "Para abrir el chat entrar al link."
            ),
        },
    )


def test_whatsapp_template_body_params_are_meta_safe() -> None:
    """Template params should not trip Meta's newline/tab/spacing validation."""
    assert WhatsAppProvider._clean_template_body_param("Caso:\nDeuda\tcon     banco") == "Caso: Deuda con banco"


def test_whatsapp_status_falls_back_to_client_lead_delivery(monkeypatch) -> None:
    """Provider status webhooks should update Delivery rows when Contadores does not own the id."""
    monkeypatch.setattr(utils, "BACKEND_BASE_URL", "http://backend")
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/contadores/messages/delivery/by-external-id":
            return httpx.Response(404, json={"detail": "not found"})
        if request.url.path == "/api/client-lead-deliveries/delivery/by-external-id":
            return httpx.Response(
                200,
                json={"id": "delivery-1", "delivery_status": "delivered", "external_id": "wamid.delivery.1"},
            )
        return httpx.Response(404, json={"detail": "not found"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await utils.process_whatsapp_message_status_event(
                client,
                event=WhatsAppMessageStatusEvent(
                    external_id="wamid.delivery.1",
                    status="delivered",
                ),
            )

    result = asyncio.run(run())

    assert paths == [
        "/api/contadores/messages/delivery/by-external-id",
        "/api/client-lead-deliveries/delivery/by-external-id",
    ]
    assert result["route"] == "client_leads"
    assert result["delivery_status"] == "delivered"
