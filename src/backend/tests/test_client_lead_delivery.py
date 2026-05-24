"""Regression tests for client lead Delivery sources."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.database as database_module
import backend.endpoints.client_leads as client_leads_endpoints
from backend.database import ClientLeadDelivery, ClientLeadDeliveryStatus
from backend.main import app


def configure_delivery_db(monkeypatch, tmp_path) -> None:
    """Point Delivery persistence at a temporary SQLite file."""
    db_path = tmp_path / "delivery.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    SQLModel.metadata.create_all(engine)


def source_payload(**overrides):
    """Build a valid Delivery source payload."""
    payload = {
        "id": "mmb-ads",
        "label": "MMB Ads",
        "enabled": True,
        "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        "sheet_gid": "123",
        "sheet_poll_seconds": 30,
        "recipient_name": "Cliente MMB",
        "recipient_phone": "+5491122223333",
        "template_name": "konecta_client_lead_alert_es_v1",
        "template_language": "es",
        "prefilled_reply_text": "Hola {name}, vi tu consulta. Te escribo para entender mejor que necesitas.",
        "column_mapping": {
            "source_id": "id",
            "created_time": "created_time",
            "full_name": "full_name",
            "phone_number": "phone_number",
            "email": "email",
        },
    }
    payload.update(overrides)
    return payload


def test_client_lead_source_sync_queues_existing_valid_rows(monkeypatch, tmp_path) -> None:
    """First sync imports existing rows, queues valid leads, and keeps invalid leads visible."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        assert source.sheet_gid == "123"
        return [
            {
                "id": "lead-1",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Ana Perez",
                "phone_number": "+5491111111111",
                "email": "ana@example.com",
            },
            {
                "id": "lead-2",
                "created_time": "2026-05-24T10:05:00Z",
                "full_name": "Telefono Malo",
                "phone_number": "sin telefono",
                "email": "bad@example.com",
            },
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        created = client.post("/api/client-lead-sources", json=source_payload()).json()
        source_id = created["id"]

        sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert sync.status_code == 200
        sync_payload = sync.json()
        assert sync_payload["imported"] == 2
        assert sync_payload["blocked"] == 1
        assert sync_payload["queued"] == 1
        assert sync_payload["source"]["counts"] == {"pending": 1, "blocked": 1, "total": 2}

        repeat_sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert repeat_sync.status_code == 200
        repeat_payload = repeat_sync.json()
        assert repeat_payload["imported"] == 0
        assert repeat_payload["updated"] == 2
        assert repeat_payload["queued"] == 0

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        by_email = {lead["email"]: lead for lead in leads}
        assert by_email["ana@example.com"]["delivery_status"] == "pending"
        assert by_email["ana@example.com"]["wa_link"].startswith("https://wa.me/549")
        assert by_email["bad@example.com"]["delivery_status"] == "blocked"
        assert by_email["bad@example.com"]["block_reason"] == "lead_phone_invalid"

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_client_lead_alert_es_v1"
        assert pending[0]["template_body_params"][0] == "MMB Ads"
        assert pending[0]["template_body_params"][1] == "Ana Perez"
        assert pending[0]["template_body_params"][4].startswith("https://wa.me/549")

        sent = client.put(
            f"/api/client-lead-deliveries/{pending[0]['delivery_id']}/delivery",
            json={"status": "sent", "external_id": "wamid.delivery.1"},
        )
        assert sent.status_code == 200
        assert sent.json()["delivery_status"] == "sent"

        delivered = client.put(
            "/api/client-lead-deliveries/delivery/by-external-id",
            json={"external_id": "wamid.delivery.1", "status": "delivered"},
        )
        assert delivered.status_code == 200
        assert delivered.json()["delivery_status"] == "delivered"


def test_client_lead_failure_and_retry(monkeypatch, tmp_path) -> None:
    """Delivery failures are visible and can be requeued by the operator."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-1",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Ana Perez",
                "phone_number": "+5491111111111",
                "email": "ana@example.com",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        client.post(f"/api/client-lead-sources/{source_id}/sync")
        delivery_id = client.get("/api/client-lead-deliveries/pending").json()["notifications"][0]["delivery_id"]

        failed = client.post(
            f"/api/client-lead-deliveries/{delivery_id}/delivery-failure",
            json={"error": "template paused", "max_attempts": 1},
        )
        assert failed.status_code == 200
        assert failed.json()["delivery_status"] == "failed"
        assert failed.json()["last_delivery_error"] == "template paused"

        retried = client.post(f"/api/client-leads/{delivery_id}/retry")
        assert retried.status_code == 200
        assert retried.json()["delivery_status"] == "pending"
        assert retried.json()["delivery_attempts"] == 0
        assert retried.json()["last_delivery_error"] is None

        row = ClientLeadDelivery.get_by_id(delivery_id)
        assert row is not None
        assert row.delivery_status == ClientLeadDeliveryStatus.PENDING


def test_client_lead_sheet_helpers_parse_common_targets() -> None:
    """Sheet URL helpers should support public export URLs and raw spreadsheet IDs."""
    spreadsheet_id, gid = client_leads_endpoints.parse_sheet_target(
        "https://docs.google.com/spreadsheets/d/abc123/edit#gid=456",
        None,
    )
    assert spreadsheet_id == "abc123"
    assert gid == "456"
    assert client_leads_endpoints.public_csv_url("abc123", "789").endswith("/export?format=csv&gid=789")
    assert client_leads_endpoints.rows_to_records([["Name", "phone"], ["Ana", "+5491111111111"]]) == [
        {"Name": "Ana", "phone": "+5491111111111"}
    ]
    assert client_leads_endpoints.records_have_mappable_headers(
        [{"Nombre": "Ana", "Telefono": "+5491111111111"}],
        {"full_name": "Nombre", "phone_number": "Telefono"},
    )
    assert not client_leads_endpoints.records_have_mappable_headers(
        [{"<html><body>Sign in</body></html>": ""}],
        {"full_name": "Nombre", "phone_number": "Telefono"},
    )
