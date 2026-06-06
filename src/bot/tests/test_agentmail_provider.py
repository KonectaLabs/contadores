"""Unit tests for AgentMail provider helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from providers import AgentMailProvider, EmailInboxState, InvalidRecipientEmailError, is_valid_email_address


def test_build_inbound_event_prefers_extracted_text() -> None:
    provider = AgentMailProvider()

    event = provider.build_inbound_event(
        {
            "message": {
                "inbox_id": "inbox-1",
                "message_id": "msg-1",
                "from": "CEO <ceo@example.com>",
                "text": "raw text",
                "extracted_text": "latest reply only",
                "thread_id": "thread-1",
                "in_reply_to": "<root@example.com>",
                "references": "<root@example.com>",
                "subject": "Re: Audit",
            }
        }
    )

    assert event is not None
    assert event.inbox_id == "inbox-1"
    assert event.message_id == "msg-1"
    assert event.from_email == "ceo@example.com"
    assert event.plain_text == "latest reply only"
    assert event.thread_id == "thread-1"


def test_build_inbound_event_returns_none_without_required_fields() -> None:
    provider = AgentMailProvider()

    event = provider.build_inbound_event({"message": {"message_id": "msg-1"}})

    assert event is None


def test_build_contact_inbox_display_name_uses_local_part() -> None:
    provider = AgentMailProvider()

    display_name = provider._build_contact_inbox_display_name("jrazzler@agentmail.to")

    assert display_name == "jrazzler"


def test_resolve_shared_inbox_refs_defaults_to_known_pool(monkeypatch) -> None:
    monkeypatch.delenv("AGENTMAIL_SHARED_INBOX_IDS", raising=False)

    provider = AgentMailProvider()

    assert provider._shared_inbox_refs == (
        "maximorodriguez@agentmail.to",
        "rodrio@agentmail.to",
        "jrazzler@agentmail.to",
    )


def test_select_shared_inbox_is_stable_for_contact() -> None:
    provider = AgentMailProvider()
    inboxes = [
        EmailInboxState(inbox_id="pool-1", inbox_address="pool-1@agentmail.to"),
        EmailInboxState(inbox_id="pool-2", inbox_address="pool-2@agentmail.to"),
        EmailInboxState(inbox_id="pool-3", inbox_address="pool-3@agentmail.to"),
    ]

    first = asyncio.run(provider._select_shared_inbox(contact_id="contact-1", inboxes=inboxes))
    second = asyncio.run(provider._select_shared_inbox(contact_id="contact-1", inboxes=inboxes))

    assert first == second
    assert first in inboxes


def test_select_shared_inbox_changes_across_contact_ids() -> None:
    provider = AgentMailProvider()
    inboxes = [
        EmailInboxState(inbox_id="pool-1", inbox_address="pool-1@agentmail.to"),
        EmailInboxState(inbox_id="pool-2", inbox_address="pool-2@agentmail.to"),
        EmailInboxState(inbox_id="pool-3", inbox_address="pool-3@agentmail.to"),
    ]

    assigned = [
        asyncio.run(provider._select_shared_inbox(contact_id=f"contact-{index}", inboxes=inboxes)).inbox_id
        for index in range(1, 5)
    ]

    assert assigned == ["pool-1", "pool-2", "pool-3", "pool-1"]


def test_ensure_contact_inbox_keeps_existing_thread_on_current_inbox(monkeypatch) -> None:
    provider = AgentMailProvider()
    provider._shared_inboxes = [
        EmailInboxState(inbox_id="pool-1", inbox_address="pool-1@agentmail.to"),
        EmailInboxState(inbox_id="pool-2", inbox_address="pool-2@agentmail.to"),
        EmailInboxState(inbox_id="pool-3", inbox_address="pool-3@agentmail.to"),
    ]

    async def fake_resolve_existing_inbox(inbox_ref: str) -> EmailInboxState:
        assert inbox_ref == "legacy-thread-inbox@agentmail.to"
        return EmailInboxState(
            inbox_id="legacy-thread-inbox@agentmail.to",
            inbox_address="legacy-thread-inbox@agentmail.to",
        )

    async def fake_sync_contact_inbox_display_name(*, inbox_id: str, inbox_address: str) -> None:
        del inbox_id, inbox_address

    async def fake_ensure_webhook(inbox_ids: set[str]) -> None:
        assert inbox_ids == {"legacy-thread-inbox@agentmail.to"}

    monkeypatch.setattr(provider, "_resolve_existing_inbox", fake_resolve_existing_inbox)
    monkeypatch.setattr(provider, "_sync_contact_inbox_display_name", fake_sync_contact_inbox_display_name)
    monkeypatch.setattr(provider, "ensure_webhook", fake_ensure_webhook)

    state = asyncio.run(
        provider.ensure_contact_inbox(
            contact_id="contact-1",
            company_name="Acme",
            contact_value="one@example.com",
            current_inbox_id="legacy-thread-inbox@agentmail.to",
            current_inbox_address="legacy-thread-inbox@agentmail.to",
            current_thread_id="thread-1",
        )
    )

    assert state.inbox_id == "legacy-thread-inbox@agentmail.to"


def test_poll_inbound_events_returns_received_messages_even_if_agentmail_archives_them() -> None:
    provider = AgentMailProvider()
    labels_by_message = {
        "msg-1": ["received", "archived"],
        "msg-2": ["received", "unread"],
        "msg-3": ["sent"],
    }

    class FakeMessagesApi:
        async def list(self, inbox_id: str, limit: int):
            assert inbox_id == "inbox-1"
            assert limit == 20
            return SimpleNamespace(
                messages=[
                    SimpleNamespace(message_id=message_id, labels=labels)
                    for message_id, labels in labels_by_message.items()
                ]
            )

        async def get(self, inbox_id: str, message_id: str):
            assert inbox_id == "inbox-1"
            assert message_id in {"msg-1", "msg-2"}
            return SimpleNamespace(
                inbox_id="inbox-1",
                message_id=message_id,
                from_="CEO <ceo@example.com>",
                extracted_text="latest reply only",
                text="raw body",
                preview="raw preview",
                thread_id="thread-1",
                in_reply_to="<root@example.com>",
                references=["<root@example.com>"],
                subject="Re: Audit",
            )

        async def update(self, inbox_id: str, message_id: str, *, add_labels, remove_labels):
            next_labels = set(labels_by_message[message_id])
            next_labels.update(add_labels)
            next_labels.difference_update(remove_labels)
            labels_by_message[message_id] = sorted(next_labels)

    class FakeInboxesApi:
        def __init__(self) -> None:
            self.messages = FakeMessagesApi()

        async def list(self, *, limit: int, page_token=None):
            assert limit == 100
            assert page_token is None
            return SimpleNamespace(
                inboxes=[SimpleNamespace(inbox_id="inbox-1")],
                next_page_token=None,
            )

    provider._client = SimpleNamespace(inboxes=FakeInboxesApi())

    first_events = asyncio.run(provider.poll_inbound_events())
    asyncio.run(provider.acknowledge_message(inbox_id="inbox-1", message_id="msg-1"))
    asyncio.run(provider.acknowledge_message(inbox_id="inbox-1", message_id="msg-2"))
    second_events = asyncio.run(provider.poll_inbound_events())

    assert [event.message_id for event in first_events] == ["msg-1", "msg-2"]
    assert first_events[0].plain_text == "latest reply only"
    assert first_events[0].from_email == "ceo@example.com"
    assert first_events[0].references == "<root@example.com>"
    assert second_events == []


def test_derive_subject_prefers_explicit_subject() -> None:
    provider = AgentMailProvider()

    subject = provider._derive_subject("Hola Facundo. Te escribo para coordinar.", "  Follow up  ")

    assert subject == "Follow up"


def test_derive_subject_falls_back_to_first_sentence() -> None:
    provider = AgentMailProvider()

    subject = provider._derive_subject("Hola Facundo. Te escribo para coordinar.", None)

    assert subject == "Hola Facundo"


def test_send_message_rejects_invalid_recipient_before_provider_call() -> None:
    provider = AgentMailProvider()

    with pytest.raises(InvalidRecipientEmailError, match="Recipient email is invalid"):
        asyncio.run(
            provider.send_message(
                inbox_id="inbox-1",
                inbox_address="bot@example.com",
                recipient="info@automotoress",
                text="Hola",
                subject="Test",
                attachments=None,
                thread_id=None,
                in_reply_to=None,
                references=None,
            )
        )


def test_is_valid_email_address_rejects_invalid_domain() -> None:
    assert is_valid_email_address("info@automotoress") is False
    assert is_valid_email_address("info@example.com") is True
    assert is_valid_email_address("leadñ@gmail.com") is True
    assert is_valid_email_address("ventas@mañana.com") is True
    assert is_valid_email_address("bad space@gmail.com") is False
