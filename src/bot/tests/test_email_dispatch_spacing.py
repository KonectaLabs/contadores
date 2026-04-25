"""Unit tests for outbound email/WhatsApp random delay scheduling."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import utils
from providers import DeliveryReceipt, InvalidRecipientEmailError
from utils import (
    EmailDispatchDelayState,
    PendingDeliveryMessage,
    WhatsAppDispatchDelayState,
    dispatch_pending_messages,
    enforce_email_dispatch_spacing,
    enforce_whatsapp_dispatch_spacing,
)


def test_enforce_email_dispatch_spacing_requires_elapsed_delay(monkeypatch) -> None:
    monkeypatch.setattr(utils, "EMAIL_DISPATCH_DELAY_MIN_SECONDS", 20.0)
    monkeypatch.setattr(utils, "EMAIL_DISPATCH_DELAY_MAX_SECONDS", 20.0)
    monkeypatch.setattr(utils, "_email_dispatch_delay_state", EmailDispatchDelayState())
    monkeypatch.setattr(utils, "sample_email_dispatch_delay_seconds", lambda: 20.0)

    timeline = iter([100.0, 121.0])
    monkeypatch.setattr(utils, "monotonic", lambda: next(timeline))
    first_allowed = asyncio.run(enforce_email_dispatch_spacing(delay_key="message:1"))
    second_allowed = asyncio.run(enforce_email_dispatch_spacing(delay_key="message:1"))

    assert first_allowed is False
    assert second_allowed is True


def test_enforce_whatsapp_dispatch_spacing_requires_elapsed_delay(monkeypatch) -> None:
    monkeypatch.setattr(utils, "WHATSAPP_DISPATCH_DELAY_MIN_SECONDS", 20.0)
    monkeypatch.setattr(utils, "WHATSAPP_DISPATCH_DELAY_MAX_SECONDS", 20.0)
    monkeypatch.setattr(utils, "_whatsapp_dispatch_delay_state", WhatsAppDispatchDelayState())
    monkeypatch.setattr(utils, "sample_whatsapp_dispatch_delay_seconds", lambda: 20.0)

    timeline = iter([100.0, 121.0])
    monkeypatch.setattr(utils, "monotonic", lambda: next(timeline))
    first_allowed = asyncio.run(enforce_whatsapp_dispatch_spacing(delay_key="wa-message:1"))
    second_allowed = asyncio.run(enforce_whatsapp_dispatch_spacing(delay_key="wa-message:1"))

    assert first_allowed is False
    assert second_allowed is True


def test_dispatch_pending_messages_defers_email_until_delay_elapsed(monkeypatch) -> None:
    email_delay_keys: list[str] = []
    whatsapp_delay_keys: list[str] = []

    async def fake_get_email_dispatch_wait_seconds(delay_key: str) -> float:
        email_delay_keys.append(delay_key)
        return 30.0

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        whatsapp_delay_keys.append(delay_key)
        return 0.0

    async def fake_dispatch_one_message(**kwargs) -> DeliveryReceipt:
        return DeliveryReceipt(external_id="provider-1", thread_id="thread-1", rfc_message_id="<msg-1@id>")

    async def fake_mark_backend_message_sent(*args, **kwargs) -> None:
        return None

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    monkeypatch.setattr(utils, "get_email_dispatch_wait_seconds", fake_get_email_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "mark_backend_message_sent", fake_mark_backend_message_sent)

    pending = [
        PendingDeliveryMessage(
            message_id=1,
            company_id="company-1",
            company_name="Example Co",
            contact_id="contact-email",
            contact_type="email",
            contact_value="test@example.com",
            text="Hola por email",
            dispatch_after="2026-02-19T19:00:00Z",
            timestamp="2026-02-19T19:00:00Z",
        ),
        PendingDeliveryMessage(
            message_id=2,
            company_id="company-1",
            company_name="Example Co",
            contact_id="contact-wa",
            contact_type="whatsapp",
            contact_value="+5491111111111",
            text="Hola por WhatsApp",
            dispatch_after="2026-02-19T19:00:00Z",
            timestamp="2026-02-19T19:00:00Z",
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

    assert email_delay_keys == ["message:1"]
    assert whatsapp_delay_keys == ["wa-message:2"]
    assert [item.status for item in results] == ["deferred", "delivered"]
    assert results[0].wait_seconds == 30.0


def test_dispatch_pending_messages_marks_invalid_email_as_failed(monkeypatch) -> None:
    failed_marks: list[tuple[str, str, int]] = []

    async def fake_get_email_dispatch_wait_seconds(delay_key: str) -> float:
        return 0.0

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        return 0.0

    async def fake_dispatch_one_message(**kwargs) -> DeliveryReceipt:
        raise InvalidRecipientEmailError("Recipient email is invalid: info@automotoress")

    async def fake_mark_backend_message_failed(client, *, company_id: str, contact_id: str, message_id: int) -> None:
        failed_marks.append((company_id, contact_id, message_id))

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    async def fake_clear_email_dispatch_delay_key(delay_key: str) -> None:
        return None

    monkeypatch.setattr(utils, "get_email_dispatch_wait_seconds", fake_get_email_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "mark_backend_message_failed", fake_mark_backend_message_failed)
    monkeypatch.setattr(utils, "clear_email_dispatch_delay_key", fake_clear_email_dispatch_delay_key)

    pending = [
        PendingDeliveryMessage(
            message_id=58,
            company_id="company-1",
            company_name="Example Co",
            contact_id="contact-1",
            contact_type="email",
            contact_value="info@automotoress",
            text="Hola por email",
            dispatch_after="2026-02-19T19:00:00Z",
            timestamp="2026-02-19T19:00:00Z",
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

    assert failed_marks == [("company-1", "contact-1", 58)]
    assert [item.status for item in results] == ["failed"]
    assert "Recipient email is invalid" in (results[0].error or "")


def test_dispatch_pending_messages_sends_reply_emails_without_random_delay(monkeypatch) -> None:
    sent_calls: list[dict[str, object]] = []
    marked_sent: list[tuple[str, str, int]] = []

    async def fail_if_called(delay_key: str) -> float:
        raise AssertionError(f"email delay should not run for active reply threads: {delay_key}")

    async def fake_get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
        return 0.0

    async def fake_dispatch_one_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        return DeliveryReceipt(
            external_id="provider-2",
            thread_id="thread-2",
            rfc_message_id="<msg-2@id>",
        )

    async def fake_mark_backend_message_sent(client, *, company_id: str, contact_id: str, message_id: int, receipt):
        marked_sent.append((company_id, contact_id, message_id))

    async def fake_prune_email_dispatch_delay_keys(*, prefix: str, active_keys: set[str]) -> None:
        return None

    async def fake_prune_whatsapp_dispatch_delay_keys(*, active_keys: set[str]) -> None:
        return None

    async def fake_clear_email_dispatch_delay_key(delay_key: str) -> None:
        return None

    monkeypatch.setattr(utils, "get_email_dispatch_wait_seconds", fail_if_called)
    monkeypatch.setattr(utils, "get_whatsapp_dispatch_wait_seconds", fake_get_whatsapp_dispatch_wait_seconds)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fake_prune_email_dispatch_delay_keys)
    monkeypatch.setattr(utils, "prune_whatsapp_dispatch_delay_keys", fake_prune_whatsapp_dispatch_delay_keys)
    monkeypatch.setattr(utils, "clear_email_dispatch_delay_key", fake_clear_email_dispatch_delay_key)
    monkeypatch.setattr(utils, "dispatch_one_message", fake_dispatch_one_message)
    monkeypatch.setattr(utils, "mark_backend_message_sent", fake_mark_backend_message_sent)

    pending = [
        PendingDeliveryMessage(
            message_id=77,
            company_id="company-1",
            company_name="Example Co",
            contact_id="contact-email",
            contact_has_inbound=True,
            contact_type="email",
            contact_value="test@example.com",
            text="Replying right away",
            dispatch_after="2026-02-19T19:00:00Z",
            timestamp="2026-02-19T19:00:00Z",
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

    assert len(sent_calls) == 1
    assert marked_sent == [("company-1", "contact-email", 77)]
    assert [item.status for item in results] == ["sent"]


def test_dispatch_pending_messages_prunes_superseded_email_delay_key(monkeypatch) -> None:
    state = EmailDispatchDelayState()
    state.due_by_key["message:41"] = 999.0

    monkeypatch.setattr(utils, "EMAIL_DISPATCH_DELAY_MIN_SECONDS", 20.0)
    monkeypatch.setattr(utils, "EMAIL_DISPATCH_DELAY_MAX_SECONDS", 20.0)
    monkeypatch.setattr(utils, "_email_dispatch_delay_state", state)
    monkeypatch.setattr(utils, "sample_email_dispatch_delay_seconds", lambda: 20.0)
    monkeypatch.setattr(utils, "monotonic", lambda: 100.0)

    pending = [
        PendingDeliveryMessage(
            message_id=42,
            company_id="company-1",
            company_name="Example Co",
            contact_id="contact-email",
            contact_type="email",
            contact_value="test@example.com",
            text="Newest draft after backoff reset",
            dispatch_after="2026-02-19T19:00:00Z",
            timestamp="2026-02-19T19:00:00Z",
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

    assert [item.status for item in results] == ["deferred"]
    assert [item.wait_seconds for item in results] == [20.0]
    assert "message:41" not in state.due_by_key
    assert state.due_by_key["message:42"] == 120.0
