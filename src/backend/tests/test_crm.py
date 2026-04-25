"""Tests for CRM inbox endpoints and persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.companies as companies_endpoints
from backend.database import (
    Company,
    Contact,
    CrmEmailMessage,
    CrmMessageStatus,
    CrmThread,
    Message,
    MessageDeliveryStatus,
    Task,
)
from backend.main import app


@pytest.fixture()
def crm_client(tmp_path, monkeypatch):
    db_path = tmp_path / "crm-test.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    with TestClient(app) as client:
        yield client


def create_company(*, source_url: str = "https://example.com", company_name: str = "Example Co") -> Company:
    """Create one company row for CRM endpoint tests."""
    return Company.create(
        source_url=source_url,
        company_name=company_name,
        company_info="Company info",
        ceo_email="ceo@example.com",
        ceo_delivery_enabled=True,
        conversation_automation_enabled=True,
    )


def seed_report_delivery(
    client: TestClient,
    *,
    company_id: str,
    participant_email: str = "ceo@example.com",
    gmail_thread_id: str = "gmail-thread-1",
    gmail_message_id: str = "gmail-message-1",
    rfc_message_id: str = "<gmail-message-1@example.com>",
    sent_at: str | None = "2026-03-08T10:00:00Z",
) -> dict:
    """Create the first CRM report-delivery message through the API."""
    response = client.post(
        "/api/crm/report-delivery/sent",
        json={
            "company_id": company_id,
            "participant_email": participant_email,
            "subject": "Quick analysis of your website contacts",
            "body": "Attached is your audit report.",
            "gmail_thread_id": gmail_thread_id,
            "gmail_message_id": gmail_message_id,
            "rfc_message_id": rfc_message_id,
            "from_email": "operator@konectalabs.com",
            "sent_at": sent_at,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_report_delivery_sent_creates_thread_message_and_updates_company(crm_client: TestClient) -> None:
    company = create_company()

    response = crm_client.post(
        "/api/crm/report-delivery/sent",
        json={
            "company_id": company.id,
            "participant_email": "ceo@example.com",
            "subject": "Quick analysis of your website contacts",
            "body": "Attached is your audit report.",
            "gmail_thread_id": "gmail-thread-1",
            "gmail_message_id": "gmail-message-1",
            "rfc_message_id": "<gmail-message-1@example.com>",
            "from_email": "operator@konectalabs.com",
            "sent_at": "2026-03-08T10:00:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["company_id"] == company.id
    assert payload["duplicate_ignored"] is False

    thread = CrmThread.get_by_id(payload["thread_id"])
    assert thread is not None
    assert thread.company_id == company.id
    assert thread.participant_email == "ceo@example.com"
    assert thread.gmail_thread_id == "gmail-thread-1"

    messages = CrmEmailMessage.list_by_thread(thread.id)
    assert len(messages) == 1
    assert messages[0].kind.value == "report_delivery"
    assert messages[0].status == CrmMessageStatus.SENT
    assert messages[0].gmail_message_id == "gmail-message-1"

    updated_company = Company.get_by_id(company.id)
    assert updated_company is not None
    assert updated_company.ceo_delivery_sent_at is not None
    assert updated_company.ceo_delivery_thread_id == "gmail-thread-1"
    assert updated_company.ceo_delivery_external_id == "gmail-message-1"
    assert updated_company.ceo_delivery_rfc_message_id == "<gmail-message-1@example.com>"


def test_audit_delivery_pdf_download_uses_company_name_filename(
    crm_client: TestClient,
    monkeypatch,
) -> None:
    company = create_company(company_name="Compañía Ñandú / CEO")

    monkeypatch.setattr(companies_endpoints.Company, "get_report_pdf_model", lambda company_id: object())
    monkeypatch.setattr(
        companies_endpoints,
        "build_vector_pdf",
        lambda pdf_model, strict_layout_fit=False: b"%PDF-1.4",
    )

    response = crm_client.get(f"/api/companies/{company.id}/audit-delivery/pdf")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4"
    assert 'filename="audit-compania-nandu-ceo.pdf"' in response.headers["Content-Disposition"]
    assert "filename*=UTF-8''audit-compania-nandu-ceo.pdf" in response.headers["Content-Disposition"]


def test_delete_company_clears_crm_rows_and_recreated_audit_gets_new_subject(crm_client: TestClient) -> None:
    company = create_company(source_url="https://konectalabs.com", company_name="Konecta Labs")
    task = Task.create(task_type="run_company_scan_task", resource_id=company.id)

    first_content = crm_client.get(f"/api/companies/{company.id}/audit-delivery/email-content")
    assert first_content.status_code == 200
    first_subject = first_content.json()["subject"]
    assert first_subject.startswith("Quick analysis of your website contacts [Ref ")

    seeded = seed_report_delivery(
        crm_client,
        company_id=company.id,
        participant_email="facu@konectalabs.com",
        gmail_thread_id="gmail-thread-konecta",
        gmail_message_id="gmail-message-konecta",
        rfc_message_id="<gmail-message-konecta@example.com>",
    )

    delete_response = crm_client.delete(f"/api/companies/{company.id}")
    assert delete_response.status_code == 200
    assert Company.get_by_id(company.id) is None
    assert CrmThread.get_by_gmail_thread_id("gmail-thread-konecta") is None
    assert CrmEmailMessage.list_by_thread(seeded["thread_id"]) == []
    assert Task.get_by_id(task.id) is None

    recreated = create_company(source_url="https://konectalabs.com", company_name="Konecta Labs")
    recreated_content = crm_client.get(f"/api/companies/{recreated.id}/audit-delivery/email-content")
    assert recreated_content.status_code == 200
    recreated_subject = recreated_content.json()["subject"]

    assert recreated_subject.startswith("Quick analysis of your website contacts [Ref ")
    assert recreated_subject != first_subject


def test_audit_delivery_email_content_lists_reportable_objectives(crm_client: TestClient) -> None:
    company = create_company()
    contact = Contact.create(
        company_id=company.id,
        type="email",
        value="sales@example.com",
        objective="Ask whether they have a Toyota T-Cross, the price, and which option they recommend",
    )
    Message.add(
        contact_id=contact.id,
        from_me=True,
        text="Hola, queria consultar por una Toyota T-Cross.",
        delivery_status=MessageDeliveryStatus.DELIVERED,
        external_id="email-delivered-objective-1",
    )

    response = crm_client.get(f"/api/companies/{company.id}/audit-delivery/email-content")

    assert response.status_code == 200
    payload = response.json()
    assert "these objectives" in payload["body"]
    assert (
        "- sales@example.com: Ask whether they have a Toyota T-Cross, the price, and which option they recommend"
        in payload["body"]
    )


def test_messages_inbound_dedupes_by_gmail_message_id_and_updates_unread_counts(
    crm_client: TestClient,
) -> None:
    company = create_company()
    seeded = seed_report_delivery(crm_client, company_id=company.id)

    first = crm_client.post(
        "/api/crm/messages/inbound",
        json={
            "gmail_message_id": "gmail-inbound-1",
            "gmail_thread_id": "gmail-thread-1",
            "from_email": "ceo@example.com",
            "subject": "Re: Quick analysis of your website contacts",
            "body": "Thanks, I read it.",
            "in_reply_to": "<gmail-message-1@example.com>",
            "references": "<gmail-message-1@example.com>",
            "received_at": "2026-03-08T11:00:00Z",
        },
    )
    duplicate = crm_client.post(
        "/api/crm/messages/inbound",
        json={
            "gmail_message_id": "gmail-inbound-1",
            "gmail_thread_id": "gmail-thread-1",
            "from_email": "ceo@example.com",
            "subject": "Re: Quick analysis of your website contacts",
            "body": "Thanks, I read it.",
            "received_at": "2026-03-08T11:00:00Z",
        },
    )

    assert first.status_code == 200
    assert first.json()["status"] == "stored"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["company_id"] == company.id

    detail = crm_client.get(f"/api/crm/threads/{seeded['thread_id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert len(detail_payload["messages"]) == 2
    assert detail_payload["thread"]["unread_message_count"] == 1

    threads = crm_client.get("/api/crm/threads")
    assert threads.status_code == 200
    threads_payload = threads.json()
    assert threads_payload["unread_thread_count"] == 1
    assert threads_payload["unread_message_count"] == 1
    assert threads_payload["threads"][0]["id"] == seeded["thread_id"]


def test_mark_read_clears_unread_counts_without_reordering_by_read_timestamp(crm_client: TestClient) -> None:
    older_company = create_company(source_url="https://older.example.com", company_name="Older Co")
    newer_company = create_company(source_url="https://newer.example.com", company_name="Newer Co")

    seed_report_delivery(
        crm_client,
        company_id=older_company.id,
        gmail_thread_id="gmail-thread-older",
        gmail_message_id="gmail-message-older",
        rfc_message_id="<older@example.com>",
        sent_at="2026-03-08T08:00:00Z",
    )
    older_thread = CrmThread.get_by_gmail_thread_id("gmail-thread-older")
    assert older_thread is not None
    CrmEmailMessage.add(
        thread_id=older_thread.id,
        direction="inbound",
        kind="ceo_reply",
        body="I have a question.",
        subject="Re: Quick analysis of your website contacts",
        from_email="ceo@example.com",
        gmail_message_id="gmail-inbound-older",
        status="received",
        received_at=datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc),
        created_at=datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc),
    )

    seed_report_delivery(
        crm_client,
        company_id=newer_company.id,
        participant_email="newer@example.com",
        gmail_thread_id="gmail-thread-newer",
        gmail_message_id="gmail-message-newer",
        rfc_message_id="<newer@example.com>",
        sent_at="2026-03-08T09:00:00Z",
    )
    newer_thread = CrmThread.get_by_gmail_thread_id("gmail-thread-newer")
    assert newer_thread is not None

    response = crm_client.post(f"/api/crm/threads/{older_thread.id}/mark-read")
    assert response.status_code == 200
    assert response.json()["unread_message_count"] == 0

    detail = crm_client.get(f"/api/crm/threads/{older_thread.id}")
    assert detail.status_code == 200
    assert detail.json()["thread"]["unread_message_count"] == 0

    threads = crm_client.get("/api/crm/threads")
    assert threads.status_code == 200
    payload = threads.json()
    assert payload["unread_thread_count"] == 0
    assert payload["unread_message_count"] == 0
    assert [item["id"] for item in payload["threads"][:2]] == [newer_thread.id, older_thread.id]


def test_thread_reply_creates_pending_message_and_pending_outbound_lists_it(crm_client: TestClient) -> None:
    company = create_company()
    seeded = seed_report_delivery(crm_client, company_id=company.id)

    response = crm_client.post(
        f"/api/crm/threads/{seeded['thread_id']}/reply",
        json={"body": "Following up on the report."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["direction"] == "outbound"
    assert payload["kind"] == "manual_reply"
    assert payload["status"] == "pending"
    assert payload["subject"] == "Quick analysis of your website contacts"

    pending = crm_client.get("/api/crm/outbound/pending")
    assert pending.status_code == 200
    pending_payload = pending.json()
    assert len(pending_payload["messages"]) == 1
    assert pending_payload["messages"][0]["message_id"] == payload["id"]
    assert pending_payload["messages"][0]["thread_id"] == seeded["thread_id"]
    assert pending_payload["messages"][0]["gmail_thread_id"] == "gmail-thread-1"
