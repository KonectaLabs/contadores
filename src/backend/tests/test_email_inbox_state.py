"""Tests for preserving email inbox state across inbound updates."""

from __future__ import annotations

import pytest
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.messages as messages_endpoints
from backend.database import Company, Contact


@pytest.fixture()
def inbox_state_db(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "email-inbox-state.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)


def test_sync_email_thread_from_inbound_preserves_existing_inbox_address(inbox_state_db) -> None:
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
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id="shared@agentmail.to",
        email_inbox_address="shared@agentmail.to",
        email_thread_id="thread-1",
    )

    messages_endpoints.sync_email_thread_from_inbound(
        contact,
        inbox_id="shared@agentmail.to",
        inbox_address=None,
        thread_id="thread-2",
    )

    updated_contact = Contact.get_by_id(contact.id)

    assert updated_contact is not None
    assert updated_contact.email_inbox_id == "shared@agentmail.to"
    assert updated_contact.email_inbox_address == "shared@agentmail.to"
    assert updated_contact.email_thread_id == "thread-2"
