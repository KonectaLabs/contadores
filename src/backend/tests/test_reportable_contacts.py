"""Tests for reportable contact filtering based on confirmed delivery."""

from __future__ import annotations

import asyncio
import importlib.util
import os
from pathlib import Path
from tempfile import mkdtemp
import sys
import types
import unittest

from sqlmodel import SQLModel, Session, create_engine

TEST_DB_PATH = Path(mkdtemp()) / "reportable_contacts.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

backend_ai_module = types.ModuleType("backend.ai")
backend_ai_module.__path__ = []  # type: ignore[attr-defined]
stage2_module = types.ModuleType("backend.ai.stage2_contact_to_conversation")


class _DummyContactConversationProgram:
    """Minimal stub so messages endpoint can import without Stage 2 runtime."""


class _DummyConversationTurnResult:
    """Minimal structured turn output stub for isolated import tests."""


stage2_module.ContactConversationProgram = _DummyContactConversationProgram
stage2_module.ConversationTurnResult = _DummyConversationTurnResult
sys.modules.setdefault("backend.ai", backend_ai_module)
sys.modules["backend.ai.stage2_contact_to_conversation"] = stage2_module

MESSAGES_MODULE_PATH = REPO_ROOT / "backend" / "endpoints" / "messages.py"
MESSAGES_SPEC = importlib.util.spec_from_file_location(
    "isolated_backend_messages_endpoint",
    MESSAGES_MODULE_PATH,
)
if MESSAGES_SPEC is None or MESSAGES_SPEC.loader is None:
    raise RuntimeError(f"Failed loading messages endpoint module from {MESSAGES_MODULE_PATH}")
MESSAGES_MODULE = importlib.util.module_from_spec(MESSAGES_SPEC)
MESSAGES_SPEC.loader.exec_module(MESSAGES_MODULE)

import backend.database as database_module
from backend.database import Company, Contact, ContactStatus, Message, MessageDeliveryStatus, normalize_contact_value

SetMessageDeliveryCommand = MESSAGES_MODULE.SetMessageDeliveryCommand
resolve_whatsapp_contact = MESSAGES_MODULE.resolve_whatsapp_contact
set_contact_message_delivery_status = MESSAGES_MODULE.set_contact_message_delivery_status

TEST_ENGINE = create_engine(
    f"sqlite:///{TEST_DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)
database_module.engine = TEST_ENGINE
database_module.DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"
SQLModel.metadata.create_all(TEST_ENGINE)
database_module.ensure_company_tags_column()


class ReportableContactsTests(unittest.TestCase):
    """Validate report and audit-contact filtering by delivery evidence."""

    def test_company_to_llm_info_excludes_contacts_without_delivered_outbound(self) -> None:
        company = Company.create(
            source_url="https://example.com",
            company_name="Example",
            company_info="Test company",
        )
        delivered_contact = Contact.create(
            company_id=company.id,
            type="whatsapp",
            value="+1 202 555 0101",
        )
        sent_only_contact = Contact.create(
            company_id=company.id,
            type="email",
            value="sales@example.com",
        )
        Message.add(
            contact_id=delivered_contact.id,
            from_me=True,
            text="Hola",
            delivery_status=MessageDeliveryStatus.DELIVERED,
            external_id="wamid-delivered-1",
        )
        Message.add(
            contact_id=sent_only_contact.id,
            from_me=True,
            text="Hi",
            delivery_status=MessageDeliveryStatus.SENT,
            external_id="wamid-sent-1",
        )

        company_info = Company.get_by_id(company.id).to_llm_info()

        self.assertEqual(
            [item.contact_value for item in company_info.contacts],
            ["+1 202 555 0101"],
        )

    def test_build_reportable_contact_lines_only_lists_delivered_contacts(self) -> None:
        company = Company.create(
            source_url="https://example.org",
            company_name="Example Org",
            company_info="Another test company",
        )
        delivered_contact = Contact.create(
            company_id=company.id,
            type="email",
            value="founder@example.org",
        )
        undelivered_contact = Contact.create(
            company_id=company.id,
            type="whatsapp",
            value="+1 202 555 0199",
        )
        Message.add(
            contact_id=delivered_contact.id,
            from_me=True,
            text="Hello",
            delivery_status=MessageDeliveryStatus.DELIVERED,
            external_id="email-delivered-1",
        )
        Message.add(
            contact_id=undelivered_contact.id,
            from_me=True,
            text="Hola",
            delivery_status=MessageDeliveryStatus.UNDELIVERED,
        )

        lines = Company.get_by_id(company.id).build_reportable_contact_lines()

        self.assertEqual(lines, "- email: founder@example.org")

    def test_build_reportable_objective_lines_only_lists_delivered_contacts(self) -> None:
        company = Company.create(
            source_url="https://example.org/objectives",
            company_name="Objective Org",
            company_info="Another test company",
            objective="Fallback objective",
        )
        delivered_contact = Contact.create(
            company_id=company.id,
            type="email",
            value="founder@example.org",
            objective="Ask about pricing and recommendation",
        )
        undelivered_contact = Contact.create(
            company_id=company.id,
            type="whatsapp",
            value="+1 202 555 0199",
            objective="Ask if they can share a catalog",
        )
        Message.add(
            contact_id=delivered_contact.id,
            from_me=True,
            text="Hello",
            delivery_status=MessageDeliveryStatus.DELIVERED,
            external_id="email-delivered-2",
        )
        Message.add(
            contact_id=undelivered_contact.id,
            from_me=True,
            text="Hola",
            delivery_status=MessageDeliveryStatus.UNDELIVERED,
        )

        lines = Company.get_by_id(company.id).build_reportable_objective_lines()

        self.assertEqual(lines, "- founder@example.org: Ask about pricing and recommendation")

    def test_whatsapp_can_be_marked_delivered(self) -> None:
        company = Company.create(
            source_url="https://example.net",
            company_name="Example Net",
            company_info="WhatsApp delivery test",
        )
        contact = Contact.create(
            company_id=company.id,
            type="whatsapp",
            value="+1 202 555 0144",
        )
        outbound = Message.add(
            contact_id=contact.id,
            from_me=True,
            text="Hola",
            delivery_status=MessageDeliveryStatus.SENT,
            external_id="wamid-sent-2",
        )

        updated = asyncio.run(
            set_contact_message_delivery_status(
                company.id,
                contact.id,
                outbound.id,
                SetMessageDeliveryCommand(delivered=True),
            )
        )

        self.assertEqual(updated.delivery_status, MessageDeliveryStatus.DELIVERED)

    def test_whatsapp_normalization_canonicalizes_argentina_local_mobile(self) -> None:
        self.assertEqual(
            normalize_contact_value("whatsapp", "(011) 15 5702-2416"),
            "5491157022416",
        )

    def test_whatsapp_resolution_matches_legacy_local_normalized_value(self) -> None:
        company = Company.create(
            source_url="https://example.com.ar",
            company_name="Example AR",
            company_info="Legacy whatsapp normalization test",
            conversation_automation_enabled=True,
        )
        legacy_contact = Contact(
            company_id=company.id,
            type="whatsapp",
            value="(011) 15 5702-2416",
            normalized_value="0111557022416",
            status=ContactStatus.ACTIVE,
        )
        with Session(TEST_ENGINE) as session:
            session.add(legacy_contact)
            session.commit()
            session.refresh(legacy_contact)
            session.expunge(legacy_contact)

        resolved = resolve_whatsapp_contact("5491157022416")

        self.assertEqual(resolved.id, legacy_contact.id)


if __name__ == "__main__":
    unittest.main()
