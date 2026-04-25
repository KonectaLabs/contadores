"""Tests for the stateless sidebar assistant and its read-only SQLite tools."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.messages as messages_endpoints
from backend.ai.react_agent import run_readonly_sql
from backend.database import Company, Contact
from backend.main import app


@pytest.fixture()
def sidebar_client(tmp_path, monkeypatch):
    db_path = tmp_path / "sidebar-assistant.sqlite"
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


def seed_company_with_contacts() -> tuple[Company, Contact, Contact]:
    """Create one company with email and WhatsApp contacts."""
    company = Company.create(
        source_url="https://konecta.example",
        company_name="Konecta Labs",
        company_info="Industrial automation company",
        objective="Audit the lead response process.",
    )
    email_contact = Contact.create(
        company_id=company.id,
        type="email",
        value="sales@konecta.example",
    )
    whatsapp_contact = Contact.create(
        company_id=company.id,
        type="whatsapp",
        value="+5491122334455",
    )
    return company, email_contact, whatsapp_contact


def test_run_readonly_sql_returns_grouped_rows_and_blocks_writes(
    sidebar_client: TestClient,
) -> None:
    seed_company_with_contacts()

    payload = json.loads(
        run_readonly_sql(
            "SELECT type, COUNT(*) AS total FROM contacts GROUP BY type ORDER BY type"
        )
    )

    assert payload["columns"] == ["type", "total"]
    assert payload["rows"] == [
        {"type": "email", "total": 1},
        {"type": "whatsapp", "total": 1},
    ]

    with pytest.raises(ValueError, match="Only read-only SQLite statements are allowed"):
        run_readonly_sql("DELETE FROM contacts")


def test_sidebar_assistant_endpoint_returns_reply(
    sidebar_client: TestClient,
    monkeypatch,
) -> None:
    company, email_contact, _ = seed_company_with_contacts()
    captured: dict[str, str] = {}

    class FakeAssistant:
        def __init__(self, user_id: str, lm=None, seed: int = 42):
            captured["user_id"] = user_id

        async def aforward(self, conversation: str, focus_context: str = ""):
            captured["conversation"] = conversation
            captured["focus_context"] = focus_context
            return SimpleNamespace(response="## Snapshot\n- email: 1\n- whatsapp: 1")

    monkeypatch.setattr(messages_endpoints, "KonectaAuditorSidebarAssistant", FakeAssistant)

    response = sidebar_client.post(
        "/api/sidebar-assistant/reply",
        json={
            "conversation": [
                {
                    "role": "user",
                    "content": "cuantos contactos de whatsapp vs email hay?",
                }
            ],
            "company_id": company.id,
            "contact_id": email_contact.id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"] == "## Snapshot\n- email: 1\n- whatsapp: 1"

    assert captured["user_id"] == "anonymous"
    assert "User: cuantos contactos de whatsapp vs email hay?" in captured["conversation"]
    assert company.id in captured["focus_context"]
    assert email_contact.id in captured["focus_context"]
    assert "sales@konecta.example" in captured["focus_context"]
