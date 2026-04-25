"""Tests for inbound-triggered draft replacement and current pending delivery selection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.messages as messages_endpoints
from backend.ai.stage2_contact_to_conversation import ConversationTurnResult
from backend.database import Company, Contact, Message, MessageDeliveryStatus
from backend.main import app


@pytest.fixture()
def messages_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "messages-backoff.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)


def create_company_and_contact() -> tuple[Company, Contact]:
    """Create one active company/contact pair for transcript tests."""
    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Company info",
        objective="Audit lead handling",
        conversation_automation_enabled=True,
    )
    contact = Contact.create(
        company_id=company.id,
        type="email",
        value="hello@example.com",
        objective="Ask for price and recommendation",
    )
    return company, contact


def test_register_inbound_replaces_existing_undelivered_draft(messages_db, monkeypatch) -> None:
    company, contact = create_company_and_contact()
    old_draft = Message.add(
        contact_id=contact.id,
        from_me=True,
        text="Old pending draft",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        dispatch_after=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    observed_conversations: list[list[tuple[bool, str]]] = []

    class FakeConversationProgram:
        async def aforward(
            self,
            *,
            conversation,
            objective,
            company_context,
            industry=None,
            channel=None,
            target_language=None,
        ) -> ConversationTurnResult:
            del company_context, target_language
            observed_conversations.append([(item.from_me, item.text) for item in conversation])
            assert objective == "Ask for price and recommendation"
            assert industry == "unknown"
            assert channel == "email"
            return ConversationTurnResult(reply="Fresh reply after latest inbound", done=False)

    monkeypatch.setattr(messages_endpoints, "ContactConversationProgram", FakeConversationProgram)

    with TestClient(app) as client:
        response = client.post(
            f"/api/companies/{company.id}/contacts/{contact.id}/messages/inbound",
            json={"message": "Newest inbound"},
        )

    assert response.status_code == 200
    assert observed_conversations == [[(False, "Newest inbound")]]

    rows = Message.list_by_contact(contact.id)
    assert [(row.from_me, row.text) for row in rows] == [
        (False, "Newest inbound"),
        (True, "Fresh reply after latest inbound"),
    ]
    assert all(row.id != old_draft.id for row in rows)

    pending = Message.list_pending_delivery(limit=10)
    assert [(row.contact_id, row.text) for row in pending] == [
        (contact.id, "Fresh reply after latest inbound"),
    ]


def test_register_contact_inbound_core_skips_stale_reply_when_newer_inbound_arrives(
    messages_db,
    monkeypatch,
) -> None:
    company, contact = create_company_and_contact()

    class FakeConversationProgram:
        async def aforward(
            self,
            *,
            conversation,
            objective,
            company_context,
            industry=None,
            channel=None,
            target_language=None,
        ) -> ConversationTurnResult:
            del conversation, objective, company_context, industry, channel, target_language
            Message.add(
                contact_id=contact.id,
                from_me=False,
                text="Newer inbound landed while reply was generating",
            )
            return ConversationTurnResult(reply="Stale reply that must not persist", done=False)

    monkeypatch.setattr(messages_endpoints, "ContactConversationProgram", FakeConversationProgram)

    result = asyncio.run(
        messages_endpoints.register_contact_inbound_core(
            contact.id,
            "Original inbound",
        )
    )

    assert result.inbound_message_id is not None
    assert result.outbound_message_id is None
    assert result.reply is None

    rows = Message.list_by_contact(contact.id)
    assert [(row.from_me, row.text) for row in rows] == [
        (False, "Original inbound"),
        (False, "Newer inbound landed while reply was generating"),
    ]


def test_pending_delivery_endpoint_only_returns_current_draft(messages_db) -> None:
    company, _ = create_company_and_contact()
    stale_contact = Contact.create(
        company_id=company.id,
        type="email",
        value="stale@example.com",
    )
    fresh_contact = Contact.create(
        company_id=company.id,
        type="email",
        value="fresh@example.com",
    )
    ready_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    Message.add(
        contact_id=stale_contact.id,
        from_me=True,
        text="Stale draft hidden from bot",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        dispatch_after=ready_at,
    )
    Message.add(
        contact_id=stale_contact.id,
        from_me=False,
        text="Human follow-up after stale draft",
    )

    Message.add(
        contact_id=fresh_contact.id,
        from_me=True,
        text="Older discarded draft",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        dispatch_after=ready_at,
    )
    Message.add(
        contact_id=fresh_contact.id,
        from_me=False,
        text="Human follow-up before regeneration",
    )
    fresh_draft = Message.add(
        contact_id=fresh_contact.id,
        from_me=True,
        text="Current draft visible to bot",
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        dispatch_after=ready_at,
    )

    with TestClient(app) as client:
        response = client.get("/api/messages/pending-delivery")

    assert response.status_code == 200
    payload = response.json()
    assert [item["message_id"] for item in payload["messages"]] == [fresh_draft.id]
    assert [item["text"] for item in payload["messages"]] == ["Current draft visible to bot"]


def test_register_contact_inbound_marks_conversation_done_and_stops_future_replies(
    messages_db,
    monkeypatch,
) -> None:
    company, contact = create_company_and_contact()
    generated_objectives: list[str | None] = []

    class FakeConversationProgram:
        async def aforward(
            self,
            *,
            conversation,
            objective,
            company_context,
            industry=None,
            channel=None,
            target_language=None,
        ) -> ConversationTurnResult:
            del conversation, company_context, industry, channel, target_language
            generated_objectives.append(objective)
            return ConversationTurnResult(reply="Gracias, con eso ya me alcanza.", done=True)

    monkeypatch.setattr(messages_endpoints, "ContactConversationProgram", FakeConversationProgram)

    first_result = asyncio.run(
        messages_endpoints.register_contact_inbound_core(
            contact.id,
            "Te paso precio y te recomiendo la T-Cross.",
        )
    )

    updated_contact = Contact.get_by_id(contact.id)
    assert first_result.reply == "Gracias, con eso ya me alcanza."
    assert generated_objectives == ["Ask for price and recommendation"]
    assert updated_contact is not None
    assert updated_contact.conversation_done is True

    second_result = asyncio.run(
        messages_endpoints.register_contact_inbound_core(
            contact.id,
            "Si queres despues te mando mas info.",
        )
    )

    rows = Message.list_by_contact(contact.id)
    assert second_result.inbound_message_id is not None
    assert second_result.outbound_message_id is None
    assert second_result.reply is None
    assert [(row.from_me, row.text) for row in rows] == [
        (False, "Te paso precio y te recomiendo la T-Cross."),
        (True, "Gracias, con eso ya me alcanza."),
        (False, "Si queres despues te mando mas info."),
    ]


def test_resolve_email_contact_does_not_reuse_tracked_inbox_for_unrelated_sender(messages_db) -> None:
    company, contact = create_company_and_contact()
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id="shared@agentmail.to",
        email_inbox_address="shared@agentmail.to",
        email_thread_id="tracked-thread-1",
    )

    with pytest.raises(messages_endpoints.HTTPException) as exc_info:
        messages_endpoints.resolve_email_contact(
            value="other@example.com",
            thread_id="different-thread",
            in_reply_to=None,
            inbox_id="shared@agentmail.to",
        )

    assert exc_info.value.status_code == 404


def test_resolve_email_contact_can_fallback_to_unclaimed_inbox_before_thread_exists(messages_db) -> None:
    company, contact = create_company_and_contact()
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id="shared@agentmail.to",
        email_inbox_address="shared@agentmail.to",
        email_thread_id=None,
    )

    resolved = messages_endpoints.resolve_email_contact(
        value="other@example.com",
        thread_id=None,
        in_reply_to=None,
        inbox_id="shared@agentmail.to",
    )

    assert resolved.id == contact.id


def test_resolve_email_contact_does_not_move_existing_sender_to_different_inbox(messages_db) -> None:
    company, contact = create_company_and_contact()
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id="primary@agentmail.to",
        email_inbox_address="primary@agentmail.to",
        email_thread_id="tracked-thread-1",
    )

    with pytest.raises(messages_endpoints.HTTPException) as exc_info:
        messages_endpoints.resolve_email_contact(
            value="hello@example.com",
            thread_id="different-thread",
            in_reply_to=None,
            inbox_id="secondary@agentmail.to",
        )

    assert exc_info.value.status_code == 404


def test_register_contact_inbound_core_preserves_existing_inbox_address(messages_db, monkeypatch) -> None:
    company, contact = create_company_and_contact()
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id="shared@agentmail.to",
        email_inbox_address="shared@agentmail.to",
        email_thread_id="tracked-thread-1",
    )

    class FakeConversationProgram:
        async def aforward(
            self,
            *,
            conversation,
            objective,
            company_context,
            industry=None,
            channel=None,
            target_language=None,
        ) -> ConversationTurnResult:
            del conversation, objective, company_context, industry, channel, target_language
            return ConversationTurnResult(reply="Fresh reply after inbound", done=False)

    monkeypatch.setattr(messages_endpoints, "ContactConversationProgram", FakeConversationProgram)

    result = asyncio.run(
        messages_endpoints.register_contact_inbound_core(
            contact.id,
            "Newest inbound",
            inbox_id="shared@agentmail.to",
            thread_id="thread-2",
        )
    )

    updated_contact = Contact.get_by_id(contact.id)

    assert result.outbound_message_id is not None
    assert updated_contact is not None
    assert updated_contact.email_inbox_id == "shared@agentmail.to"
    assert updated_contact.email_inbox_address == "shared@agentmail.to"
    assert updated_contact.email_thread_id == "thread-2"
