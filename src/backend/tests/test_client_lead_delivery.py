"""Regression tests for client lead Delivery sources."""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine

import backend.client_lead_config as client_lead_config
import backend.database as database_module
import backend.endpoints.client_leads as client_leads_endpoints
from backend.database import ClientLeadDelivery, ClientLeadDeliveryStatus, ContadoresLead
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
        "sheet_tab_name": "Leads",
        "sheet_poll_seconds": 30,
        "recipient_name": "Cliente MMB",
        "recipient_phone": "+5491122223333",
        "template_name": "konecta_client_lead_alert_es_v2",
        "template_language": "es",
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
        assert source.sheet_tab_name == "Leads"
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
        assert by_email["ana@example.com"]["wa_link"] == "https://wa.me/5491111111111"
        assert by_email["bad@example.com"]["delivery_status"] == "blocked"
        assert by_email["bad@example.com"]["block_reason"] == "lead_phone_invalid"

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_client_lead_alert_es_v2"
        assert pending[0]["template_body_params"][0] == "MMB Ads"
        assert pending[0]["template_body_params"][1] == "Ana Perez"
        assert pending[0]["template_body_params"][4] == "https://wa.me/5491111111111"

        sent = client.put(
            f"/api/client-lead-deliveries/{pending[0]['delivery_id']}/delivery",
            json={
                "status": "sent",
                "external_id": "wamid.delivery.1",
                "sent_text": "Snapshot enviado a Guido",
            },
        )
        assert sent.status_code == 200
        assert sent.json()["delivery_status"] == "sent"
        assert sent.json()["sent_text"] == "Snapshot enviado a Guido"

        delivered = client.put(
            "/api/client-lead-deliveries/delivery/by-external-id",
            json={"external_id": "wamid.delivery.1", "status": "delivered"},
        )
        assert delivered.status_code == 200
        assert delivered.json()["delivery_status"] == "delivered"

        ContadoresLead.upsert(
            funnel_id="general",
            external_lead_id="guido-chat",
            phone="+5491122223333",
            full_name="Cliente MMB",
        )
        recipient_chat = client.get(f"/api/client-lead-sources/{source_id}/recipient-chat")
        assert recipient_chat.status_code == 200
        recipient_payload = recipient_chat.json()
        assert recipient_payload["recipient_phone"] == "+5491122223333"
        assert recipient_payload["crm_leads"][0]["id"]
        assert recipient_payload["crm_leads"][0]["funnel_id"] == "general"
        assert len(recipient_payload["messages"]) == 1
        assert recipient_payload["messages"][0]["delivery_id"] == pending[0]["delivery_id"]
        assert recipient_payload["messages"][0]["delivery_status"] == "delivered"
        assert recipient_payload["messages"][0]["external_id"] == "wamid.delivery.1"
        assert recipient_payload["messages"][0]["text"] == "Snapshot enviado a Guido"


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
    assert client_leads_endpoints.public_csv_url("abc123", None, "simple form setup").endswith(
        "/gviz/tq?tqx=out:csv&sheet=simple%20form%20setup"
    )
    assert client_leads_endpoints.public_csv_url("abc123", None, "simple setup 22/5/26").endswith(
        "/gviz/tq?tqx=out:csv&sheet=simple%20setup%2022%2F5%2F26"
    )
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


def test_client_lead_private_sheet_without_service_account_marks_sync_failed(monkeypatch, tmp_path) -> None:
    """Private public exports should fail visibly when no service account is configured."""
    configure_delivery_db(monkeypatch, tmp_path)

    class PrivateSheetResponse:
        status_code = 401
        text = ""
        content = b""
        request = httpx.Request("GET", "https://docs.google.com/private")

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("private", request=self.request, response=self)

    class PrivateSheetClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            del exc_type, exc, traceback

        async def get(self, url: str) -> PrivateSheetResponse:
            del url
            return PrivateSheetResponse()

    monkeypatch.setattr(client_leads_endpoints.httpx, "AsyncClient", PrivateSheetClient)
    monkeypatch.setattr(client_leads_endpoints, "service_account_file", lambda: None)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert sync.status_code == 502
        assert "no hay service account configurada" in sync.json()["detail"]

        sources = client.get("/api/client-lead-sources").json()["sources"]
        failed_source = next(source for source in sources if source["id"] == source_id)
        assert failed_source["last_sync_status"] == "failed"
        assert "public CSV returned HTTP 401" in failed_source["last_sync_note"]


def test_client_lead_sources_load_from_config_file(monkeypatch, tmp_path) -> None:
    """File-backed Delivery sources are expanded per recipient and upserted."""
    configure_delivery_db(monkeypatch, tmp_path)
    seed_path = tmp_path / "seed-client-lead-sources.json"
    config_path = tmp_path / "client-lead-sources.json"
    seed_path.write_text('{"version": 1, "sources": []}', encoding="utf-8")
    config_path.write_text(
        """
        {
          "version": 1,
          "sources": [
            {
              "id": "mmb-ads",
              "label": "MMB Ads",
              "enabled": true,
              "sheet_poll_seconds": 45,
              "sheets": [
                {
                  "id": "deuda",
                  "label": "Deuda",
                  "sheet_url": "https://docs.google.com/spreadsheets/d/deuda-sheet/edit",
                  "sheet_tab_name": "deuda"
                },
                {
                  "id": "simple",
                  "label": "Simple Form Setup",
                  "sheet_url": "https://docs.google.com/spreadsheets/d/simple-sheet/edit",
                  "sheet_tab_name": "simple form setup 2026-05-25"
                }
              ],
              "recipients": [
                {"id": "ana", "name": "Ana", "phone": "+5491111111111"},
                {"id": "luis", "name": "Luis", "phone": "+5492222222222"}
              ],
              "column_mapping": {
                "source_id": "id",
                "created_time": "timestamp",
                "full_name": "name",
                "phone_number": "phone",
                "email": "email"
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH", str(seed_path))
    monkeypatch.setenv("CLIENT_LEAD_SOURCES_CONFIG_PATH", str(config_path))

    result = client_lead_config.sync_client_lead_sources_from_config()

    assert result.configured == 4
    assert result.upserted == ["mmb-ads-deuda-ana", "mmb-ads-deuda-luis", "mmb-ads-simple-ana", "mmb-ads-simple-luis"]
    assert result.errors == []

    with TestClient(app) as client:
        payload = client.get("/api/client-lead-sources").json()

    sources = {source["id"]: source for source in payload["sources"]}
    assert set(sources) == {"mmb-ads-deuda-ana", "mmb-ads-deuda-luis", "mmb-ads-simple-ana", "mmb-ads-simple-luis"}
    assert sources["mmb-ads-deuda-ana"]["label"] == "MMB Ads · Deuda · Ana"
    assert sources["mmb-ads-simple-luis"]["sheet_tab_name"] == "simple form setup 2026-05-25"
    assert sources["mmb-ads-simple-luis"]["sheet_poll_seconds"] == 45
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["created_time"] == "timestamp"
