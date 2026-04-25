"""Regression tests for bot-only and shared auth route gating."""

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
from backend.ai.auditor_company_discovery import AuditorCandidateCompany, AuditorCandidateCompanyBatch
from backend.auth import INTERNAL_API_TOKEN_HEADER, SESSION_COOKIE_NAME, auth_manager
from backend.main import app, is_internal_bot_path, is_shared_session_or_internal_path


def configure_auth(monkeypatch, tmp_path: Path) -> TestClient:
    """Enable auth with one temp operator account and one shared internal token."""
    auth_file = tmp_path / "auth.toml"
    auth_file.write_text('[[users]]\nuser = "operator"\npassword = "secret"\n', encoding="utf-8")
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_file))
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal-token")
    db_path = tmp_path / "internal-bot-paths.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)
    auth_manager.reload_from_env()
    return TestClient(app)


def test_company_contact_message_routes_are_shared_not_internal_only() -> None:
    """Transcript routes must stay available to both operator sessions and bot runtime."""
    base_path = "/api/companies/company-1/contacts/contact-1/messages"
    assert not is_internal_bot_path(base_path)
    assert not is_internal_bot_path(f"{base_path}/inbound")
    assert not is_internal_bot_path(f"{base_path}/41")
    assert not is_internal_bot_path(f"{base_path}/41/delivery")

    assert is_shared_session_or_internal_path(base_path)
    assert is_shared_session_or_internal_path(f"{base_path}/inbound")
    assert is_shared_session_or_internal_path(f"{base_path}/41")
    assert is_shared_session_or_internal_path(f"{base_path}/41/delivery")


def test_audit_delivery_read_routes_are_shared_not_internal_only() -> None:
    """Operator-facing audit download/read routes must not be misclassified as bot-only."""
    pdf_path = "/api/companies/company-1/audit-delivery/pdf"
    ceo_email_path = "/api/companies/company-1/audit-delivery/ceo-email"
    email_content_path = "/api/companies/company-1/audit-delivery/email-content"

    assert not is_internal_bot_path(pdf_path)
    assert not is_internal_bot_path(ceo_email_path)
    assert not is_internal_bot_path(email_content_path)

    assert is_shared_session_or_internal_path(pdf_path)
    assert is_shared_session_or_internal_path(ceo_email_path)
    assert is_shared_session_or_internal_path(email_content_path)


def test_internal_bot_path_excludes_unrelated_contact_routes() -> None:
    """Non-message company/contact routes must not be treated as bot-only transport."""
    assert not is_internal_bot_path("/api/companies/company-1/contacts/contact-1/thread")
    assert not is_shared_session_or_internal_path("/api/companies/company-1/contacts/contact-1/thread")


def test_company_scan_and_discovery_routes_are_shared_not_internal_only() -> None:
    """Discovery/list/scan routes must stay available to both operators and bot runtime."""
    assert not is_internal_bot_path("/api/companies")
    assert not is_internal_bot_path("/api/companies/scan")
    assert not is_internal_bot_path("/api/companies/discover-auditor-candidates")
    assert not is_internal_bot_path("/api/companies/company-1/report-schedule")

    assert is_shared_session_or_internal_path("/api/companies")
    assert is_shared_session_or_internal_path("/api/companies/scan")
    assert is_shared_session_or_internal_path("/api/companies/discover-auditor-candidates")
    assert is_shared_session_or_internal_path("/api/companies/company-1/report-schedule")


def test_contadores_routes_are_shared_not_internal_only() -> None:
    """Contadores operator screens and bot loops should share the same backend namespace."""
    contadores_paths = [
        "/api/contadores/config",
        "/api/contadores/leads",
        "/api/contadores/leads/lead-1",
        "/api/contadores/whatsapp/inbound",
        "/api/contadores/messages/pending-delivery",
        "/api/contadores/automation/tick",
    ]

    for path in contadores_paths:
        assert not is_internal_bot_path(path)
        assert is_shared_session_or_internal_path(path)


def test_shared_contact_message_routes_accept_internal_token_without_session(monkeypatch, tmp_path: Path) -> None:
    """Shared transcript routes must still work for bot runtime via internal token."""
    client = configure_auth(monkeypatch, tmp_path)
    path = "/api/companies/company-1/contacts/contact-1/messages"

    unauthorized = client.get(path)
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.get(
        path,
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 404


def test_shared_company_list_route_accepts_internal_token_without_session(monkeypatch, tmp_path: Path) -> None:
    """The bot should be able to list companies with the internal token."""
    client = configure_auth(monkeypatch, tmp_path)

    unauthorized = client.get("/api/companies")
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.get(
        "/api/companies",
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json() == []


def test_shared_company_scan_route_accepts_internal_token_without_session(monkeypatch, tmp_path: Path) -> None:
    """The bot should be able to create scans through the normal company scan endpoint."""
    client = configure_auth(monkeypatch, tmp_path)

    async def fake_resolve_scan_leadership_recipient_email(**kwargs):
        return "ceo@example.com"

    monkeypatch.setattr(
        "backend.endpoints.companies.Company.get_most_recent_by_normalized_source_url",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.resolve_scan_leadership_recipient_email",
        fake_resolve_scan_leadership_recipient_email,
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.Company.create",
        lambda **kwargs: SimpleNamespace(id="company-1"),
    )
    monkeypatch.setattr(
        "backend.endpoints.companies.Task.run_async",
        lambda *args, **kwargs: SimpleNamespace(id="task-1", status=SimpleNamespace(value="queued")),
    )

    unauthorized = client.post("/api/companies/scan", json={"url": "https://example.com"})
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.post(
        "/api/companies/scan",
        json={"url": "https://example.com"},
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {
        "task_id": "task-1",
        "company_id": "company-1",
        "status": "queued",
        "duplicate_ignored": False,
    }


def test_shared_company_discovery_route_accepts_internal_token_without_session(monkeypatch, tmp_path: Path) -> None:
    """The bot should be able to call the company discovery endpoint with the internal token."""
    client = configure_auth(monkeypatch, tmp_path)

    async def fake_aforward(self, *, count: int, exclude_company_urls: list[str], exclude_company_names: list[str]):
        assert count == 1
        assert exclude_company_urls == []
        assert exclude_company_names == []
        return AuditorCandidateCompanyBatch(
            companies=[
                AuditorCandidateCompany(
                    company_name="Acme Logistics",
                    website_url="https://acme-logistics.example",
                    industry="logistics",
                    country_or_region=None,
                    fit_summary="Public quote requests appear important to revenue.",
                    likely_contact_owner="Sales staff",
                    leadership_recipient_name="Jane Doe",
                    leadership_recipient_role="Managing Director",
                    leadership_recipient_email="jane@acme-logistics.example",
                    leadership_recipient_evidence="Public evidence ties Jane Doe to a managing director inbox.",
                    public_contact_channels=["email"],
                    public_contact_paths=["https://acme-logistics.example/contact"],
                    lead_dependency_evidence=["The site pushes users to ask for a quote."],
                    source_urls=["https://acme-logistics.example/contact"],
                )
            ]
        )

    monkeypatch.setattr(
        "backend.endpoints.companies.AuditorCompanyDiscoveryProgram.aforward",
        fake_aforward,
    )

    unauthorized = client.post("/api/companies/discover-auditor-candidates", json={"count": 1})
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.post(
        "/api/companies/discover-auditor-candidates",
        json={"count": 1},
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 200
    assert authorized.json()["companies"][0]["company_name"] == "Acme Logistics"


def test_shared_company_report_schedule_route_accepts_internal_token(monkeypatch, tmp_path: Path) -> None:
    """The bot should be able to reschedule company delivery with the internal token."""
    client = configure_auth(monkeypatch, tmp_path)

    unauthorized = client.put(
        "/api/companies/company-1/report-schedule",
        json={"scheduled_send_at": "2026-04-06T20:00:00Z"},
    )
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.put(
        "/api/companies/company-1/report-schedule",
        json={"scheduled_send_at": "2026-04-06T20:00:00Z"},
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 404


def test_shared_contact_message_routes_accept_operator_session(monkeypatch, tmp_path: Path) -> None:
    """Operator transcript fetches must not be blocked as internal-only routes."""
    client = configure_auth(monkeypatch, tmp_path)
    client.cookies.set(SESSION_COOKIE_NAME, auth_manager.create_session("operator"))

    response = client.get("/api/companies/company-1/contacts/contact-1/messages")
    assert response.status_code == 404


def test_shared_audit_delivery_pdf_route_accepts_operator_session(monkeypatch, tmp_path: Path) -> None:
    """Operator audit download should stay available behind normal session auth."""
    client = configure_auth(monkeypatch, tmp_path)
    client.cookies.set(SESSION_COOKIE_NAME, auth_manager.create_session("operator"))

    response = client.get("/api/companies/company-1/audit-delivery/pdf")
    assert response.status_code == 404


def test_shared_audit_delivery_pdf_route_accepts_internal_token(monkeypatch, tmp_path: Path) -> None:
    """Bot/runtime may still fetch audit PDFs through the shared internal token."""
    client = configure_auth(monkeypatch, tmp_path)

    response = client.get(
        "/api/companies/company-1/audit-delivery/pdf",
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert response.status_code == 404


def test_internal_contact_message_delivery_path_accepts_internal_token(monkeypatch, tmp_path: Path) -> None:
    """Bot-facing delivery updates must keep working with shared internal auth."""
    client = configure_auth(monkeypatch, tmp_path)
    path = "/api/companies/company-1/contacts/contact-1/messages/1/delivery"

    unauthorized = client.put(path, json={"status": "sent"})
    assert unauthorized.status_code == 401
    assert unauthorized.json() == {"detail": "Authentication required."}

    authorized = client.put(
        path,
        json={"status": "sent"},
        headers={INTERNAL_API_TOKEN_HEADER: "test-internal-token"},
    )
    assert authorized.status_code == 404
