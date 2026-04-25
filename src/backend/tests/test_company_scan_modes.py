"""Tests for company scan mode helpers."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
from backend.ai.auditor_company_discovery import AuditorCandidateCompany, AuditorCandidateCompanyBatch
from backend.ai.stage1_url_to_contacts import ContactType, DiscoveredContact
from backend.database import (
    Company,
    CompanyStatus,
    Contact,
    normalize_company_source_url,
    normalize_company_source_url_key,
)
from backend.endpoints.companies import (
    DEV_TEXT_SOURCE_LABEL_FALLBACK,
    build_dev_text_source_label,
    create_contacts_for_company,
    discover_company_contacts,
    generate_first_message_for_contact,
)
from backend.main import app


def test_build_dev_text_source_label_prefers_explicit_label() -> None:
    result = build_dev_text_source_label(
        "Ignored body",
        source_label="Manual dev fixture",
    )

    assert result == "Manual dev fixture"


def test_build_dev_text_source_label_falls_back_for_blank_text() -> None:
    result = build_dev_text_source_label("   ")

    assert result == DEV_TEXT_SOURCE_LABEL_FALLBACK


def test_normalize_company_source_url_canonicalizes_company_urls() -> None:
    assert normalize_company_source_url(" Example.com///?utm_source=test#fragment ") == "https://example.com"
    assert normalize_company_source_url("https://www.example.com/about/") == "https://example.com/about"
    assert normalize_company_source_url_key("http://www.example.com/about/?utm=1") == "example.com/about"


def test_discover_company_contacts_uses_dev_text_path() -> None:
    class FakeStage1:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def dev_aforward(self, text: str):
            self.calls.append(("text", text))
            return "dev-result"

        async def aforward(self, url: str):
            self.calls.append(("url", url))
            return "url-result"

    stage1 = FakeStage1()

    result = asyncio.run(
        discover_company_contacts(
            stage1,
            url="https://example.com",
            text="Company text fixture",
        )
    )

    assert result == "dev-result"
    assert stage1.calls == [("text", "Company text fixture")]


def test_discover_company_contacts_uses_url_path_when_text_missing() -> None:
    class FakeStage1:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def dev_aforward(self, text: str):
            self.calls.append(("text", text))
            return "dev-result"

        async def aforward(self, url: str):
            self.calls.append(("url", url))
            return "url-result"

    stage1 = FakeStage1()

    result = asyncio.run(
        discover_company_contacts(
            stage1,
            url="https://example.com",
            text="",
        )
    )

    assert result == "url-result"
    assert stage1.calls == [("url", "https://example.com")]


def test_create_contacts_for_company_skips_invalid_emails(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "scan-modes.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
    )

    created = asyncio.run(
        create_contacts_for_company(
            company.id,
            [
                DiscoveredContact(type=ContactType.EMAIL, value="info@automotoress"),
                DiscoveredContact(type=ContactType.WHATSAPP, value="+54 9 11 1111 1111"),
            ],
        )
    )

    refreshed = Company.get_by_id(company.id)

    assert created == 1
    assert refreshed is not None
    assert [item.value for item in refreshed.get_contacts()] == ["+54 9 11 1111 1111"]


def test_create_contacts_for_company_persists_contact_objective(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "scan-objectives.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
        objective="Company fallback objective",
    )

    created = asyncio.run(
        create_contacts_for_company(
            company.id,
            [
                DiscoveredContact(
                    type=ContactType.EMAIL,
                    value="info@example.com",
                    objective="Ask for pricing and recommendation",
                ),
            ],
        )
    )

    refreshed = Company.get_by_id(company.id)

    assert created == 1
    assert refreshed is not None
    assert refreshed.get_contacts()[0].objective == "Ask for pricing and recommendation"


def test_create_contacts_for_company_skips_generic_phone_contacts(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "scan-phone-filter.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
    )

    created = asyncio.run(
        create_contacts_for_company(
            company.id,
            [
                DiscoveredContact(type=ContactType.PHONE, value="+1 800 555 0100", notes="main office phone"),
                DiscoveredContact(type=ContactType.WHATSAPP, value="+54 9 11 1111 1111", notes="wa.me button"),
            ],
        )
    )

    refreshed = Company.get_by_id(company.id)

    assert created == 1
    assert refreshed is not None
    assert [(item.type, item.value) for item in refreshed.get_contacts()] == [
        ("whatsapp", "+54 9 11 1111 1111"),
    ]


def test_generate_first_message_for_contact_stays_compatible_with_old_program_signature(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "scan-first-message.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
        industry="warehousing_transport_support",
    )
    contact = Contact.create(
        company_id=company.id,
        type="email",
        value="sales@example.com",
        objective="Ask for pricing",
    )

    class FakeFirstMessageProgram:
        async def aforward(
            self,
            *,
            objective: str,
            contact_type: ContactType,
            company_context: str | None = None,
            target_language: str | None = None,
        ):
            assert objective == "Ask for pricing"
            assert contact_type == ContactType.EMAIL
            assert company_context == "Info"
            assert target_language is None
            return SimpleNamespace(
                first_message="hola, me pasas una referencia de precio?",
                subject="consulta rapida",
            )

    message_id, reason, failed = asyncio.run(
        generate_first_message_for_contact(
            company,
            contact,
            first_message_program=FakeFirstMessageProgram(),
        )
    )

    refreshed_contact = Contact.get_by_id(contact.id)

    assert failed is False
    assert reason is None
    assert message_id is not None
    assert refreshed_contact is not None
    assert refreshed_contact.email_subject == "consulta rapida"


def test_scan_company_accepts_tags_payload(monkeypatch) -> None:
    created_company_kwargs: dict[str, object] = {}

    def fake_company_create(**kwargs):
        created_company_kwargs.update(kwargs)
        return SimpleNamespace(id="company-1")

    def fake_run_async(background_tasks, fn, **kwargs):
        assert fn.__name__ == "run_company_scan_task"
        assert kwargs["company_id"] == "company-1"
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        return "ceo@example.com"

    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan",
        json={
            "url": "https://example.com",
            "objective": "Audit lead handling",
            "tags": ["vip", "argentina", "vip"],
            "report_window_minutes": 30,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-1",
        "company_id": "company-1",
        "status": "queued",
        "duplicate_ignored": False,
    }
    assert created_company_kwargs["source_url"] == "https://example.com"
    assert created_company_kwargs["objective"] == "Audit lead handling"
    assert created_company_kwargs["tags"] == ["vip", "argentina", "vip"]
    assert created_company_kwargs["ceo_email"] == "ceo@example.com"
    assert created_company_kwargs["report_window_minutes"] == 30


def test_scan_company_rejects_when_leadership_recipient_missing(monkeypatch) -> None:
    create_called = False

    def fake_company_create(**kwargs):
        nonlocal create_called
        create_called = True
        return SimpleNamespace(id="company-1")

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        raise HTTPException(status_code=422, detail="No leadership recipient email was found for this company.")

    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan",
        json={"url": "https://example.com"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "No leadership recipient email was found for this company."}
    assert create_called is False


def test_discover_auditor_companies_passes_count_and_exclusions(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_aforward(self, *, count: int, exclude_company_urls: list[str], exclude_company_names: list[str]):
        captured["count"] = count
        captured["exclude_company_urls"] = exclude_company_urls
        captured["exclude_company_names"] = exclude_company_names
        return AuditorCandidateCompanyBatch(
            companies=[
                AuditorCandidateCompany(
                    company_name="Acme Logistics",
                    website_url="https://acme-logistics.example",
                    industry="logistics",
                    country_or_region="Argentina",
                    fit_summary="Inbound quote requests appear central to the commercial motion.",
                    likely_contact_owner="Sales coordinators and branch staff",
                    leadership_recipient_name="Jane Doe",
                    leadership_recipient_role="Managing Director",
                    leadership_recipient_email="jane@acme-logistics.example",
                    leadership_recipient_evidence="A public leadership page ties Jane Doe to the managing director role and company email.",
                    public_contact_channels=["email", "quote form"],
                    public_contact_paths=["https://acme-logistics.example/contact"],
                    lead_dependency_evidence=["The site pushes users toward quote requests."],
                    source_urls=["https://acme-logistics.example/contact"],
                )
            ]
        )

    monkeypatch.setattr(
        "backend.endpoints.companies.AuditorCompanyDiscoveryProgram.aforward",
        fake_aforward,
    )

    client = TestClient(app)
    response = client.post(
        "/api/companies/discover-auditor-candidates",
        json={
            "count": 2,
            "exclude_company_urls": ["https://known.example"],
            "exclude_company_names": ["Known Co"],
        },
    )

    assert response.status_code == 200
    assert captured == {
        "count": 2,
        "exclude_company_urls": ["https://known.example"],
        "exclude_company_names": ["Known Co"],
    }
    assert response.json() == {
        "companies": [
            {
                "company_name": "Acme Logistics",
                "website_url": "https://acme-logistics.example",
                "industry": "logistics",
                "country_or_region": "Argentina",
                "fit_summary": "Inbound quote requests appear central to the commercial motion.",
                "likely_contact_owner": "Sales coordinators and branch staff",
                "leadership_recipient_name": "Jane Doe",
                "leadership_recipient_role": "Managing Director",
                "leadership_recipient_email": "jane@acme-logistics.example",
                "leadership_recipient_evidence": "A public leadership page ties Jane Doe to the managing director role and company email.",
                "public_contact_channels": ["email", "quote form"],
                "public_contact_paths": ["https://acme-logistics.example/contact"],
                "lead_dependency_evidence": ["The site pushes users toward quote requests."],
                "source_urls": ["https://acme-logistics.example/contact"],
            }
        ]
    }


def test_create_manual_contact_requires_objective(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "manual-contact-objective.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
    )

    client = TestClient(app)
    response = client.post(
        f"/api/companies/{company.id}/contacts",
        json={
            "type": "email",
            "value": "sales@example.com",
        },
    )

    assert response.status_code == 422


def test_get_company_detail_exposes_contact_objective_and_conversation_done(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "company-detail-objective.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
        objective="Fallback objective",
    )
    contact = Contact.create(
        company_id=company.id,
        type="email",
        value="sales@example.com",
        objective="Ask about pricing and recommendation",
        conversation_done=True,
    )

    client = TestClient(app)
    response = client.get(f"/api/companies/{company.id}")

    assert response.status_code == 200
    payload = response.json()
    contact_payload = next(item for item in payload["contacts"] if item["id"] == contact.id)
    assert contact_payload["objective"] == "Ask about pricing and recommendation"
    assert contact_payload["conversation_done"] is True


def test_dev_scan_company_accepts_tags_payload(monkeypatch) -> None:
    created_company_kwargs: dict[str, object] = {}

    def fake_company_create(**kwargs):
        created_company_kwargs.update(kwargs)
        return SimpleNamespace(id="company-1")

    def fake_run_async(background_tasks, fn, **kwargs):
        assert fn.__name__ == "run_company_scan_task"
        assert kwargs["company_id"] == "company-1"
        assert kwargs["text"] == "Raw company text"
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        assert kwargs == {
            "source_value": "https://manual.example",
            "request_ceo_email": None,
        }
        return "ceo@example.com"

    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/dev/companies/scan",
        json={
            "text": "Raw company text",
            "source_label": "https://manual.example",
            "tags": ["vip", "beta"],
            "report_window_minutes": 15,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-1",
        "company_id": "company-1",
        "status": "queued",
        "duplicate_ignored": False,
    }
    assert created_company_kwargs["source_url"] == "https://manual.example"
    assert created_company_kwargs["tags"] == ["vip", "beta"]
    assert created_company_kwargs["ceo_email"] == "ceo@example.com"
    assert created_company_kwargs["report_window_minutes"] == 15


def test_dev_scan_company_rejects_non_url_text_without_ceo_email(monkeypatch) -> None:
    create_called = False

    def fake_company_create(**kwargs):
        nonlocal create_called
        create_called = True
        return SimpleNamespace(id="company-1")

    monkeypatch.setattr("backend.endpoints.companies.Company.create", fake_company_create)

    client = TestClient(app)
    response = client.post(
        "/api/dev/companies/scan",
        json={
            "text": "Raw company text",
            "source_label": "Manual dev fixture",
        },
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "Dev text scans require ceo_email unless source_label is a company website URL."
    }
    assert create_called is False


def test_scan_company_skips_duplicate_normalized_url(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "duplicate-company-scan.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    existing = Company.create(
        source_url="https://www.example.com/?utm=campaign",
        company_name="Example Co",
        company_info="Info",
    )
    run_async_calls: list[dict[str, object]] = []

    def fake_run_async(background_tasks, fn, **kwargs):
        run_async_calls.append(kwargs)
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(
        "/api/companies/scan",
        json={
            "url": "example.com/",
            "objective": "Audit lead handling",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "task_id": None,
        "company_id": existing.id,
        "status": "duplicate",
        "duplicate_ignored": True,
    }
    assert run_async_calls == []


def test_rescan_company_queues_new_scan_for_company_with_zero_contacts(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "rescan-company.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="example.com",
        company_name="Example Co",
        company_info="Info",
        status=CompanyStatus.FAILED,
    )
    run_async_calls: list[dict[str, object]] = []

    def fake_run_async(background_tasks, fn, *, resource_id=None, timeout_seconds=None, **kwargs):
        run_async_calls.append(
            {
                "fn_name": fn.__name__,
                "resource_id": resource_id,
                "timeout_seconds": timeout_seconds,
                **kwargs,
            }
        )
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        assert kwargs == {
            "source_value": "https://example.com",
            "request_ceo_email": None,
        }
        return "ceo@example.com"

    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(f"/api/companies/{company.id}/rescan")

    refreshed = Company.get_by_id(company.id)

    assert response.status_code == 200
    assert response.json() == {
        "task_id": "task-1",
        "company_id": company.id,
        "status": "queued",
        "duplicate_ignored": False,
    }
    assert refreshed is not None
    assert refreshed.status == CompanyStatus.INITIALIZING
    assert run_async_calls == [
        {
            "fn_name": "run_company_scan_task",
            "resource_id": company.id,
            "timeout_seconds": 3000,
            "company_id": company.id,
            "source_value": "https://example.com",
            "request_ceo_email": "ceo@example.com",
        }
    ]


def test_rescan_company_rejects_company_with_contacts(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "rescan-company-with-contacts.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
    )
    Contact.create(
        company_id=company.id,
        type=ContactType.EMAIL.value,
        value="info@example.com",
    )

    run_async_calls: list[dict[str, object]] = []

    def fake_run_async(background_tasks, fn, *, resource_id=None, timeout_seconds=None, **kwargs):
        run_async_calls.append(kwargs)
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(f"/api/companies/{company.id}/rescan")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Re-scan is only available for companies with 0 active contacts"
    }
    assert run_async_calls == []


def test_rescan_company_rejects_non_url_source(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "rescan-company-non-url.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="Manual dev fixture",
        company_name="Example Co",
        company_info="Info",
    )

    run_async_calls: list[dict[str, object]] = []

    def fake_run_async(background_tasks, fn, *, resource_id=None, timeout_seconds=None, **kwargs):
        run_async_calls.append(kwargs)
        return SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued"))

    monkeypatch.setattr("backend.endpoints.companies.Task.run_async", fake_run_async)

    client = TestClient(app)
    response = client.post(f"/api/companies/{company.id}/rescan")

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Re-scan is only available for companies created from a URL source"
    }
    assert run_async_calls == []


def test_list_companies_exposes_has_ceo_email_flag(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "list-companies-ceo-email.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    with_email = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
        ceo_email="ceo@example.com",
    )
    without_email = Company.create(
        source_url="https://example.org",
        company_name="Example Org",
        company_info="Info",
    )

    client = TestClient(app)
    response = client.get("/api/companies")

    assert response.status_code == 200
    payload_by_id = {item["id"]: item for item in response.json()}
    assert payload_by_id[with_email.id]["has_ceo_email"] is True
    assert payload_by_id[without_email.id]["has_ceo_email"] is False


def test_ensure_company_tags_column_bootstraps_existing_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy-company-schema.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE companies (
            id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            company_name TEXT NOT NULL,
            company_info TEXT NOT NULL DEFAULT '',
            website_markdown TEXT NOT NULL DEFAULT '',
            ceo_email TEXT,
            company_size TEXT NOT NULL DEFAULT 'unknown',
            industry TEXT NOT NULL DEFAULT 'unknown',
            language TEXT,
            objective TEXT,
            conversation_automation_enabled INTEGER NOT NULL DEFAULT 0,
            ceo_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            report_window_hours INTEGER NOT NULL DEFAULT 24,
            report_scheduled_send_at TEXT,
            ceo_delivery_sent_at TEXT,
            ceo_delivery_thread_id TEXT,
            ceo_delivery_external_id TEXT,
            ceo_delivery_rfc_message_id TEXT,
            ceo_delivery_blocked_reason TEXT,
            ceo_delivery_blocked_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            report_snapshot_json TEXT,
            report_pdf_model_json TEXT,
            report_html TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")

    database_module.ensure_company_tags_column()
    database_module.ensure_company_tags_column()

    check_connection = sqlite3.connect(db_path)
    column_names = [
        row[1]
        for row in check_connection.execute("PRAGMA table_info(companies)").fetchall()
    ]
    check_connection.close()

    assert "tags_json" in column_names


def test_ensure_company_normalized_source_url_column_bootstraps_existing_database(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy-company-normalized-url.sqlite"
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        CREATE TABLE companies (
            id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            company_name TEXT NOT NULL,
            company_info TEXT NOT NULL DEFAULT '',
            website_markdown TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            ceo_email TEXT,
            company_size TEXT NOT NULL DEFAULT 'unknown',
            industry TEXT NOT NULL DEFAULT 'unknown',
            language TEXT,
            objective TEXT,
            conversation_automation_enabled INTEGER NOT NULL DEFAULT 0,
            ceo_delivery_enabled INTEGER NOT NULL DEFAULT 0,
            report_window_hours INTEGER NOT NULL DEFAULT 24,
            report_scheduled_send_at TEXT,
            ceo_delivery_sent_at TEXT,
            ceo_delivery_thread_id TEXT,
            ceo_delivery_external_id TEXT,
            ceo_delivery_rfc_message_id TEXT,
            ceo_delivery_blocked_reason TEXT,
            ceo_delivery_blocked_at TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            report_snapshot_json TEXT,
            report_pdf_model_json TEXT,
            report_html TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO companies (
            id,
            source_url,
            company_name,
            company_info,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "company-1",
            "https://www.example.com/path/?utm=1",
            "Example Co",
            "Info",
            "2026-03-11T12:00:00Z",
            "2026-03-11T12:00:00Z",
        ),
    )
    connection.commit()
    connection.close()

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")

    database_module.ensure_company_normalized_source_url_column()
    database_module.ensure_company_normalized_source_url_column()

    check_connection = sqlite3.connect(db_path)
    column_names = {
        row[1]
        for row in check_connection.execute("PRAGMA table_info(companies)").fetchall()
    }
    normalized_value = check_connection.execute(
        "SELECT normalized_source_url FROM companies WHERE id = 'company-1'"
    ).fetchone()[0]
    check_connection.close()

    assert "normalized_source_url" in column_names
    assert normalized_value == "example.com/path"
def test_get_report_snapshot_parses_legacy_snapshot_without_contact_assessments(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "legacy-report-snapshot.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)

    company = Company.create(
        source_url="https://example.com",
        company_name="Example Co",
        company_info="Info",
    )
    legacy_snapshot = {
        "company_info": {
            "company_name": "Example Co",
            "source_url": "https://example.com",
            "company_info": "Info",
            "ceo_email": None,
            "objective": None,
            "contacts": [],
        },
        "language": "es",
        "experts_knowledge": "Knowledge",
        "report_text": "Report body",
    }
    Company.update_report_snapshot(company.id, json.dumps(legacy_snapshot))

    report = Company.get_report_snapshot(company.id)

    assert report is not None
    assert report.report_text == "Report body"
    assert report.contact_assessments == []
