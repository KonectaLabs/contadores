"""Regression tests for client lead Delivery sources."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Session, create_engine

import backend.client_lead_config as client_lead_config
import backend.database as database_module
import backend.endpoints.client_leads as client_leads_endpoints
import backend.endpoints.meta_leads as meta_leads_endpoints
from backend.meta_lead_ads import DEFAULT_META_LEAD_FIELDS, MetaFormLeadFetchResult, fetch_meta_form_leads_with_paging
from backend.ai.codex_agent_tools import call_tool
from backend.database import ClientLeadDelivery, ClientLeadDeliveryStatus, ClientLeadSource, ContadoresLead, PlatformEvent
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
        "template_name": "konecta_delivery_lead_alert_es",
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


def signed_meta_webhook_body(payload: dict, secret: str = "meta-secret") -> tuple[bytes, dict[str, str]]:
    """Return a raw body plus Meta's appsecret signature header."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"content-type": "application/json", "x-hub-signature-256": f"sha256={signature}"}


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
        assert list(by_email["ana@example.com"]["raw_row"].keys()) == [
            "id",
            "created_time",
            "full_name",
            "phone_number",
            "email",
        ]
        assert by_email["ana@example.com"]["delivery_status"] == "pending"
        assert by_email["ana@example.com"]["wa_link"] == "https://wa.me/5491111111111"
        assert by_email["bad@example.com"]["delivery_status"] == "blocked"
        assert by_email["bad@example.com"]["block_reason"] == "lead_phone_invalid"

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_delivery_lead_alert_es"
        assert pending[0]["template_body_params"] == [
            "MMB Ads",
            "Nombre: Ana Perez; WhatsApp: 5491111111111; Email: ana@example.com",
            "https://wa.me/5491111111111",
        ]
        assert pending[0]["delivered_text"] == (
            "Nuevo Lead: MMB Ads.\n\n"
            "datos del Lead:\n"
            "Nombre: Ana Perez\n"
            "WhatsApp: 5491111111111\n"
            "Email: ana@example.com\n\n"
            "Para abrir el chat:\n"
            "https://wa.me/5491111111111\n"
            "Para abrir el chat entrar al link."
        )

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


def test_client_lead_source_sync_without_source_id_uses_stable_row_identity(monkeypatch, tmp_path) -> None:
    """Rows without source ids should not duplicate when mutable fields change."""
    configure_delivery_db(monkeypatch, tmp_path)
    rows = [
        {
            "created_time": "2026-05-24T10:00:00Z",
            "full_name": "Ana Perez",
            "phone_number": "+5491111111111",
            "email": "ana@example.com",
            "notes": "first note",
        }
    ]

    async def fake_fetch_sheet_records(source):
        del source
        return rows

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

        first_sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert first_sync.status_code == 200
        assert first_sync.json()["imported"] == 1
        first_leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert len(first_leads) == 1
        first_key = first_leads[0]["source_row_key"]

        rows[0]["full_name"] = "Ana Maria Perez"
        rows[0]["email"] = "ana.new@example.com"
        rows[0]["notes"] = "changed note"
        second_sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert second_sync.status_code == 200
        assert second_sync.json()["imported"] == 0
        assert second_sync.json()["updated"] == 1

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert len(leads) == 1
        assert leads[0]["source_row_key"] == first_key
        assert leads[0]["full_name"] == "Ana Maria Perez"
        assert leads[0]["email"] == "ana.new@example.com"
        assert len(client.get("/api/client-lead-deliveries/pending").json()["notifications"]) == 1


def test_client_lead_source_sync_blocks_ambiguous_local_phone_digits(monkeypatch, tmp_path) -> None:
    """Delivery imports should not queue local-looking digits without a sendable country code."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-local-phone",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Telefono Local",
                "phone_number": "22223333",
                "email": "local@example.com",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert sync.status_code == 200
        assert sync.json()["blocked"] == 1
        assert sync.json()["queued"] == 0

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert leads[0]["delivery_status"] == "blocked"
        assert leads[0]["block_reason"] == "lead_phone_invalid"
        assert leads[0]["wa_link"] == ""


def test_client_lead_source_sync_blocks_unsendable_recipient_phone(monkeypatch, tmp_path) -> None:
    """A valid lead should stay blocked when the Delivery recipient cannot be sent to."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-valid-phone",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Ana Perez",
                "phone_number": "+5491111111111",
                "email": "ana@example.com",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post(
            "/api/client-lead-sources",
            json=source_payload(recipient_phone="22223333"),
        ).json()["id"]
        sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert sync.status_code == 200
        assert sync.json()["blocked"] == 1
        assert sync.json()["queued"] == 0

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert leads[0]["delivery_status"] == "blocked"
        assert leads[0]["block_reason"] == "recipient_phone_invalid"


def test_client_lead_context_fields_are_added_to_pending_template(monkeypatch, tmp_path) -> None:
    """Configured sheet context fields should be rendered as one WhatsApp param."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-context-1",
                "created_time": "2026-05-26T10:00:00Z",
                "full_name": "Graciela Medina",
                "phone_number": "+595972490441",
                "email": "migramed.27@hotmail.com",
                "¿qué_tipo_de_deuda_tiene_pendiente?": "Tarjeta de credito",
                "breve_descripción_de_su_caso": "Me estafaron con una compra online",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        created = client.post(
            "/api/client-lead-sources",
            json=source_payload(
                id="rodrigo-deuda",
                label="Rodrigo Monges Luces · Deuda",
                context_field_mapping={
                    "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
                    "Caso": "breve_descripción_de_su_caso",
                },
            ),
        )
        assert created.status_code == 200
        source = created.json()
        assert source["template_name"] == "konecta_delivery_lead_alert_context_es"
        assert source["context_field_mapping"] == {
            "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
            "Caso": "breve_descripción_de_su_caso",
        }

        sync = client.post(f"/api/client-lead-sources/{source['id']}/sync")
        assert sync.status_code == 200

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_delivery_lead_alert_context_es"
        assert pending[0]["template_body_params"] == [
            "Rodrigo Monges Luces · Deuda",
            (
                "Nombre: Graciela Medina; WhatsApp: 595972490441; Email: migramed.27@hotmail.com; "
                "Tipo de deuda: Tarjeta de credito; Caso: Me estafaron con una compra online"
            ),
            "https://wa.me/595972490441",
        ]
        assert "Contexto:" not in pending[0]["delivered_text"]
        assert "Tipo de deuda: Tarjeta de credito" in pending[0]["delivered_text"]
        assert "Caso: Me estafaron con una compra online" in pending[0]["delivered_text"]

        delivery_id = pending[0]["delivery_id"]
        copy_all = client.get(f"/api/client-leads/{delivery_id}/copy-all")
        assert copy_all.status_code == 200
        assert "Caso: Me estafaron con una compra online" in copy_all.json()["text"]


def test_client_lead_context_template_keeps_three_params_when_values_are_blank(monkeypatch, tmp_path) -> None:
    """The context template sends lead data as one body param."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-context-blank",
                "created_time": "2026-05-26T11:00:00Z",
                "full_name": "Carlos Lopez",
                "phone_number": "+595981111222",
                "email": "",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        created = client.post(
            "/api/client-lead-sources",
            json=source_payload(
                id="rodrigo-deuda-blank",
                label="Rodrigo Monges Luces · Deuda",
                context_field_mapping={
                    "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
                    "Caso": "breve_descripción_de_su_caso",
                },
            ),
        )
        assert created.status_code == 200
        source = created.json()
        assert source["template_name"] == "konecta_delivery_lead_alert_context_es"

        sync = client.post(f"/api/client-lead-sources/{source['id']}/sync")
        assert sync.status_code == 200

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_delivery_lead_alert_context_es"
        assert pending[0]["template_body_params"] == [
            "Rodrigo Monges Luces · Deuda",
            "Nombre: Carlos Lopez; WhatsApp: 595981111222; Email: -",
            "https://wa.me/595981111222",
        ]


def test_meta_lead_form_import_queues_delivery_and_dedupes(monkeypatch, tmp_path) -> None:
    """Meta instant-form payloads should enter the same Delivery queue as Sheets."""
    configure_delivery_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/client-lead-sources",
            json=source_payload(
                id="meta-instant-forms",
                label="MMB Meta Instant Forms",
                context_field_mapping={
                    "Campaña": "campaign_name",
                    "Servicio": "service",
                },
            ),
        )
        assert created.status_code == 200
        source_id = created.json()["id"]

        command = {
            "leadgen_id": "meta-lead-1",
            "created_time": "2026-05-30T12:34:56+00:00",
            "form_id": "form_123",
            "campaign_id": "campaign_123",
            "campaign_name": "Abogados laborales",
            "ad_id": "ad_123",
            "ad_name": "Consulta laboral",
            "platform": "fb",
            "field_data": [
                {"name": "full_name", "values": ["Ana Perez"]},
                {"name": "phone_number", "values": ["+5491111111111"]},
                {"name": "email", "values": ["ana@example.com"]},
                {"name": "service", "values": ["Despido laboral"]},
            ],
        }

        imported = client.post(f"/api/client-lead-sources/{source_id}/meta-lead", json=command)
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["imported"] == 1
        assert payload["queued"] == 1
        assert payload["source"]["counts"] == {"pending": 1, "total": 1}

        repeated = client.post(f"/api/client-lead-sources/{source_id}/meta-lead", json=command)
        assert repeated.status_code == 200
        assert repeated.json()["imported"] == 0
        assert repeated.json()["updated"] == 1
        assert repeated.json()["queued"] == 0

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert len(leads) == 1
        assert leads[0]["source_row_key"] == "meta-lead-1"
        assert leads[0]["raw_row"]["leadgen_id"] == "meta-lead-1"
        assert leads[0]["raw_row"]["campaign_name"] == "Abogados laborales"
        assert leads[0]["raw_row"]["service"] == "Despido laboral"

        pending = client.get("/api/client-lead-deliveries/pending").json()["notifications"]
        assert len(pending) == 1
        assert pending[0]["template_name"] == "konecta_delivery_lead_alert_context_es"
        assert pending[0]["template_body_params"] == [
            "Abogados laborales",
            (
                "Nombre: Ana Perez; WhatsApp: 5491111111111; Email: ana@example.com; "
                "Campaña: Abogados laborales; Servicio: Despido laboral"
            ),
            "https://wa.me/5491111111111",
        ]

        events = PlatformEvent.list_recent(target_type="client_lead_source", target_id=source_id)
        assert [event.event_type for event in events] == ["client_lead.meta_form_imported"]
        assert events[0].payload_dict()["leadgen_id"] == "meta-lead-1"


def test_meta_lead_form_import_blocks_invalid_phone(monkeypatch, tmp_path) -> None:
    """Meta instant-form leads with unusable phone values should stay visible but blocked."""
    configure_delivery_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

        imported = client.post(
            f"/api/client-lead-sources/{source_id}/meta-lead",
            json={
                "leadgen_id": "meta-lead-bad-phone",
                "field_data": [
                    {"name": "full_name", "values": ["Sin Telefono"]},
                    {"name": "phone_number", "values": ["no tengo"]},
                    {"name": "email", "values": ["bad@example.com"]},
                ],
            },
        )
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["imported"] == 1
        assert payload["blocked"] == 1
        assert payload["queued"] == 0

        leads = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"]
        assert leads[0]["source_row_key"] == "meta-lead-bad-phone"
        assert leads[0]["delivery_status"] == "blocked"
        assert leads[0]["block_reason"] == "lead_phone_invalid"
        assert client.get("/api/client-lead-deliveries/pending").json()["notifications"] == []


def test_meta_lead_form_import_appends_new_rows_to_google_sheet(monkeypatch, tmp_path) -> None:
    """New Meta form imports should append to Sheets once and dedupe repeats."""
    configure_delivery_db(monkeypatch, tmp_path)
    appended_rows = []

    def fake_append_record_to_sheet(source, row):
        appended_rows.append((source.id, row))
        return {"range": "'Leads'", "headers": list(row.keys())}

    monkeypatch.setattr(client_leads_endpoints, "append_record_to_sheet", fake_append_record_to_sheet)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        command = {
            "leadgen_id": "meta-sheet-lead-1",
            "form_id": "form_sheet_1",
            "ad_id": "ad_sheet_1",
            "campaign_id": "campaign_sheet_1",
            "campaign_name": "Sheet Campaign",
            "field_data": [
                {"name": "full_name", "values": ["Sheet Lead"]},
                {"name": "phone_number", "values": ["+5491112345678"]},
                {"name": "email", "values": ["sheet@example.com"]},
                {"name": "unexpected_internal_answer", "values": ["do not export"]},
            ],
        }

        imported = client.post(f"/api/client-lead-sources/{source_id}/meta-lead", json=command)
        assert imported.status_code == 200
        assert imported.json()["sheet_appended"] == 1
        assert len(appended_rows) == 1
        assert appended_rows[0][1]["leadgen_id"] == "meta-sheet-lead-1"
        assert appended_rows[0][1]["campaign_name"] == "Sheet Campaign"
        assert "form_id" not in appended_rows[0][1]
        assert "ad_id" not in appended_rows[0][1]
        assert "campaign_id" not in appended_rows[0][1]
        assert "unexpected_internal_answer" not in appended_rows[0][1]

        repeated = client.post(f"/api/client-lead-sources/{source_id}/meta-lead", json=command)
        assert repeated.status_code == 200
        assert repeated.json()["sheet_appended"] == 0
        assert len(appended_rows) == 1

        monkeypatch.setenv("META_SHEET_APPEND_EXTRA_FIELDS", "unexpected_internal_answer, campaign_id")
        extra_imported = client.post(
            f"/api/client-lead-sources/{source_id}/meta-lead",
            json={**command, "leadgen_id": "meta-sheet-lead-2"},
        )
        assert extra_imported.status_code == 200
        assert appended_rows[-1][1]["unexpected_internal_answer"] == "do not export"
        assert appended_rows[-1][1]["campaign_id"] == "campaign_sheet_1"


def test_meta_lead_form_fetch_imports_from_graph(monkeypatch, tmp_path) -> None:
    """A leadgen_id fetch should import through the same Delivery queue."""
    configure_delivery_db(monkeypatch, tmp_path)

    def fake_fetch_meta_lead_payload(*, leadgen_id, fields):
        assert leadgen_id == "meta-fetch-lead-1"
        assert fields == DEFAULT_META_LEAD_FIELDS
        return {
            "id": "meta-fetch-lead-1",
            "created_time": "2026-05-30T13:00:00+0000",
            "form_id": "form_fetch_1",
            "ad_id": "ad_fetch_1",
            "campaign_id": "campaign_fetch_1",
            "campaign_name": "Meta Fetch Campaign",
            "field_data": [
                {"name": "full_name", "values": ["Fetch Lead"]},
                {"name": "phone_number", "values": ["+5491155556666"]},
                {"name": "email", "values": ["fetch@example.com"]},
            ],
        }

    monkeypatch.setattr(client_leads_endpoints, "fetch_meta_lead_payload", fake_fetch_meta_lead_payload)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

        imported = client.post(
            f"/api/client-lead-sources/{source_id}/meta-lead/fetch",
            json={"leadgen_id": "meta-fetch-lead-1"},
        )
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["imported"] == 1
        assert payload["queued"] == 1

        repeated = client.post(
            f"/api/client-lead-sources/{source_id}/meta-lead/fetch",
            json={"leadgen_id": "meta-fetch-lead-1"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["updated"] == 1
        assert repeated.json()["queued"] == 0

        lead = client.get(f"/api/client-lead-sources/{source_id}/leads").json()["leads"][0]
        assert lead["source_row_key"] == "meta-fetch-lead-1"
        assert lead["raw_row"]["campaign_name"] == "Meta Fetch Campaign"
        assert lead["delivery_status"] == "pending"

        events = PlatformEvent.list_recent(target_type="client_lead_source", target_id=source_id)
        assert [event.event_type for event in events] == ["client_lead.meta_form_fetched_imported"]
        assert events[0].payload_dict()["leadgen_id"] == "meta-fetch-lead-1"


def test_meta_lead_form_backfill_imports_form_leads(monkeypatch, tmp_path) -> None:
    """A form backfill should fetch recent form leads and append new imports to Sheets."""
    configure_delivery_db(monkeypatch, tmp_path)
    appended_rows = []

    def fake_fetch_meta_form_leads_with_paging(*, form_id, fields, limit, max_pages, max_leads):
        assert form_id == "form_backfill_1"
        assert fields == DEFAULT_META_LEAD_FIELDS
        assert limit == 100
        assert max_pages == 5
        assert max_leads == 500
        return MetaFormLeadFetchResult(
            leads=[
                {
                    "id": "backfill-lead-1",
                    "form_id": "form_backfill_1",
                    "field_data": [
                        {"name": "full_name", "values": ["Backfill Uno"]},
                        {"name": "phone_number", "values": ["+5491111112222"]},
                        {"name": "email", "values": ["uno@example.com"]},
                    ],
                },
                {
                    "id": "backfill-lead-2",
                    "form_id": "form_backfill_1",
                    "field_data": [
                        {"name": "full_name", "values": ["Backfill Dos"]},
                        {"name": "phone_number", "values": ["+5491133334444"]},
                        {"name": "email", "values": ["dos@example.com"]},
                    ],
                },
            ],
            pages_fetched=1,
        )

    monkeypatch.setattr(client_leads_endpoints, "fetch_meta_form_leads_with_paging", fake_fetch_meta_form_leads_with_paging)
    monkeypatch.setattr(
        client_leads_endpoints,
        "append_record_to_sheet",
        lambda source, row: appended_rows.append(row) or {"range": "'Leads'"},
    )

    with TestClient(app) as client:
        source_id = client.post(
            "/api/client-lead-sources",
            json=source_payload(meta_lead_form_id="form_backfill_1"),
        ).json()["id"]

        imported = client.post(f"/api/client-lead-sources/{source_id}/meta-leads/backfill", json={})
        assert imported.status_code == 200
        payload = imported.json()
        assert payload["fetched"] == 2
        assert payload["imported"] == 2
        assert payload["queued"] == 2
        assert payload["sheet_appended"] == 2
        assert len(appended_rows) == 2

        repeated = client.post(f"/api/client-lead-sources/{source_id}/meta-leads/backfill", json={})
        assert repeated.status_code == 200
        repeated_payload = repeated.json()
        assert repeated_payload["fetched"] == 2
        assert repeated_payload["imported"] == 0
        assert repeated_payload["updated"] == 2
        assert repeated_payload["queued"] == 0
        assert repeated_payload["sheet_appended"] == 0
        assert len(appended_rows) == 2


def test_meta_form_leads_fetch_paginates_with_caps(monkeypatch) -> None:
    """Meta form reads should follow cursors only within explicit caps."""
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    calls: list[tuple[str, dict]] = []

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        calls.append((path, params or {}))
        if len(calls) == 1:
            return {
                "data": [{"id": "page-1-lead"}],
                "paging": {"next": "https://graph.example/next", "cursors": {"after": "cursor-1"}},
            }
        return {
            "data": [{"id": "page-2-lead"}],
            "paging": {"next": "https://graph.example/next", "cursors": {"after": "cursor-2"}},
        }

    result = fetch_meta_form_leads_with_paging(
        form_id="form_page_1",
        limit=1,
        max_pages=2,
        max_leads=10,
        graph_get=fake_graph_get,
    )

    assert [item["id"] for item in result.leads] == ["page-1-lead", "page-2-lead"]
    assert result.pages_fetched == 2
    assert result.truncated is True
    assert result.complete is False
    assert result.next_cursor == "cursor-2"
    assert calls[1][1]["after"] == "cursor-1"


def test_meta_form_leads_fetch_reports_partial_error_after_first_page(monkeypatch) -> None:
    """A later page error should leave operators with partial status metadata."""
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    calls = 0

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        nonlocal calls
        del path, params
        calls += 1
        if calls == 1:
            return {
                "data": [{"id": "first-page-lead"}],
                "paging": {"next": "https://graph.example/next", "cursors": {"after": "cursor-1"}},
            }
        raise RuntimeError("Meta page two failed")

    result = fetch_meta_form_leads_with_paging(
        form_id="form_partial_1",
        limit=1,
        max_pages=3,
        graph_get=fake_graph_get,
    )

    assert [item["id"] for item in result.leads] == ["first-page-lead"]
    assert result.truncated is True
    assert result.complete is False
    assert "Meta page two failed" in result.errors[0]


def test_meta_lead_form_fetch_reports_missing_credentials(monkeypatch, tmp_path) -> None:
    """Graph fetch should fail before network calls when Meta credentials are absent."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

        response = client.post(
            f"/api/client-lead-sources/{source_id}/meta-lead/fetch",
            json={"leadgen_id": "missing-creds-lead"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "status": "missing_credentials",
            "errors": ["META_MARKETING_API_VERSION", "META_MARKETING_ACCESS_TOKEN"],
        }

        source = client.get("/api/client-lead-sources").json()["sources"][0]
        assert source["last_sync_status"] == "failed"
        assert "META_MARKETING_ACCESS_TOKEN" in source["last_sync_note"]


def test_meta_lead_webhook_verifies_and_imports_leadgen_change(monkeypatch, tmp_path) -> None:
    """The public Meta webhook should verify challenges and route leadgen changes by form id."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_LEAD_WEBHOOK_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("META_LEAD_WEBHOOK_APP_SECRET", "meta-secret")

    def fake_fetch_meta_lead_payload(*, leadgen_id, fields):
        assert leadgen_id == "webhook-lead-1"
        assert fields == DEFAULT_META_LEAD_FIELDS
        return {
            "id": "webhook-lead-1",
            "form_id": "form_webhook_1",
            "field_data": [
                {"name": "full_name", "values": ["Webhook Lead"]},
                {"name": "phone_number", "values": ["+5491199998888"]},
                {"name": "email", "values": ["webhook@example.com"]},
            ],
        }

    monkeypatch.setattr(client_leads_endpoints, "fetch_meta_lead_payload", fake_fetch_meta_lead_payload)

    with TestClient(app) as client:
        challenge = client.get(
            "/api/meta-leads/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "challenge-ok",
            },
        )
        assert challenge.status_code == 200
        assert challenge.text == "challenge-ok"

        source_id = client.post(
            "/api/client-lead-sources",
            json=source_payload(meta_lead_form_id="form_webhook_1"),
        ).json()["id"]
        body, headers = signed_meta_webhook_body(
            {
                "object": "page",
                "entry": [
                    {
                        "id": "page_1",
                        "changes": [
                            {
                                "field": "leadgen",
                                "value": {
                                    "leadgen_id": "webhook-lead-1",
                                    "form_id": "form_webhook_1",
                                    "page_id": "page_1",
                                },
                            }
                        ],
                    }
                ],
            }
        )
        webhook = client.post(
            "/api/meta-leads/webhook",
            content=body,
            headers=headers,
        )
        assert webhook.status_code == 200
        payload = webhook.json()
        assert payload["processed"] == 1
        assert payload["items"][0]["source_id"] == source_id
        assert payload["items"][0]["imported"] == 1

        row = ClientLeadDelivery.list_by_source(source_id)[0]
        assert row.source_row_key == "webhook-lead-1"
        assert row.delivery_status == ClientLeadDeliveryStatus.PENDING


def test_meta_lead_webhook_rejects_missing_signature(monkeypatch, tmp_path) -> None:
    """Meta lead webhooks must fail closed when the signature header is missing."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_LEAD_WEBHOOK_APP_SECRET", "meta-secret")

    with TestClient(app) as client:
        response = client.post("/api/meta-leads/webhook", content=b"not-json")

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Meta webhook signature."


def test_meta_lead_webhook_rejects_invalid_signature(monkeypatch, tmp_path) -> None:
    """Meta lead webhooks must fail closed when the signature does not match the body."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_LEAD_WEBHOOK_APP_SECRET", "meta-secret")
    body, headers = signed_meta_webhook_body({"entry": []}, secret="wrong-secret")

    with TestClient(app) as client:
        response = client.post("/api/meta-leads/webhook", content=body, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Meta webhook signature."


def test_meta_lead_webhook_rejects_missing_app_secret(monkeypatch, tmp_path) -> None:
    """Meta lead webhooks need an app secret before any POST body is trusted."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    monkeypatch.delenv("META_LEAD_WEBHOOK_APP_SECRET", raising=False)
    body, headers = signed_meta_webhook_body({"entry": []})

    with TestClient(app) as client:
        response = client.post("/api/meta-leads/webhook", content=body, headers=headers)

    assert response.status_code == 503
    assert response.json()["detail"] == "META_APP_SECRET is not configured."


def test_codex_tool_imports_meta_lead_form_to_delivery(monkeypatch, tmp_path) -> None:
    """Agents should be able to route retrieved Meta form leads without the UI."""
    configure_delivery_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

    result = call_tool(
        run_id="agent-run-meta-lead-import",
        tool_name="import_meta_lead_form_to_delivery",
        arguments={
            "source_id": source_id,
            "leadgen_id": "meta-agent-lead-1",
            "idempotency_key": "meta-agent-lead-import-1",
            "campaign_name": "Abogados laborales",
            "field_data": [
                {"name": "full_name", "values": ["Agente Meta"]},
                {"name": "phone_number", "values": ["+5491133334444"]},
                {"name": "email", "values": ["agente@example.com"]},
            ],
            "reason": "Webhook retry imported by agent.",
        },
    )

    assert result["ok"] is True
    assert result["result"]["imported"] == 1
    assert result["result"]["queued"] == 1
    row = ClientLeadDelivery.list_by_source(source_id)[0]
    assert row.source_row_key == "meta-agent-lead-1"
    assert row.delivery_status == ClientLeadDeliveryStatus.PENDING


def test_codex_tool_fetches_meta_lead_form_to_delivery(monkeypatch, tmp_path) -> None:
    """Agents should be able to fetch a Meta leadgen_id and route it without the UI."""
    configure_delivery_db(monkeypatch, tmp_path)

    def fake_fetch_meta_lead_payload(*, leadgen_id, fields):
        assert leadgen_id == "meta-agent-fetch-1"
        assert "field_data" in fields
        return {
            "id": "meta-agent-fetch-1",
            "form_id": "form_agent_fetch",
            "campaign_name": "Agent Fetch Campaign",
            "field_data": [
                {"name": "full_name", "values": ["Agente Fetch"]},
                {"name": "phone_number", "values": ["+5491177778888"]},
                {"name": "email", "values": ["agent-fetch@example.com"]},
            ],
        }

    monkeypatch.setattr(client_leads_endpoints, "fetch_meta_lead_payload", fake_fetch_meta_lead_payload)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]

    result = call_tool(
        run_id="agent-run-meta-lead-fetch",
        tool_name="fetch_meta_lead_form_to_delivery",
        arguments={
            "source_id": source_id,
            "leadgen_id": "meta-agent-fetch-1",
            "idempotency_key": "meta-agent-lead-fetch-1",
            "reason": "Webhook lead id fetched by agent.",
        },
    )

    assert result["ok"] is True
    assert result["result"]["imported"] == 1
    assert result["result"]["queued"] == 1
    row = ClientLeadDelivery.list_by_source(source_id)[0]
    assert row.source_row_key == "meta-agent-fetch-1"
    assert row.delivery_status == ClientLeadDeliveryStatus.PENDING


def test_client_lead_clearing_context_fields_resets_template(monkeypatch, tmp_path) -> None:
    """Clearing context in the UI payload should reset the context template."""
    configure_delivery_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/client-lead-sources",
            json=source_payload(
                context_field_mapping={"Ciudad": "city"},
            ),
        )
        assert created.status_code == 200
        source = created.json()
        assert source["template_name"] == "konecta_delivery_lead_alert_context_es"

        updated = client.put(
            f"/api/client-lead-sources/{source['id']}",
            json=source_payload(
                template_name=source["template_name"],
                context_field_mapping={},
            ),
        )
        assert updated.status_code == 200
        updated_source = updated.json()
        assert updated_source["template_name"] == "konecta_delivery_lead_alert_es"
        assert updated_source["context_field_mapping"] == {}


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

        unconfirmed = client.post(f"/api/client-leads/{delivery_id}/retry")
        assert unconfirmed.status_code == 409
        assert unconfirmed.json()["detail"] == "Retry confirmation required."

        retried = client.post(f"/api/client-leads/{delivery_id}/retry", json={"confirm": True})
        assert retried.status_code == 200
        assert retried.json()["delivery_status"] == "pending"
        assert retried.json()["delivery_attempts"] == 0
        assert retried.json()["last_delivery_error"] is None

        row = ClientLeadDelivery.get_by_id(delivery_id)
        assert row is not None
        assert row.delivery_status == ClientLeadDeliveryStatus.PENDING


def test_client_lead_pending_claim_reserves_before_dispatch(monkeypatch, tmp_path) -> None:
    """POST claim should reserve rows while GET pending stays diagnostic/read-only."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-claim-1",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Ana Claim",
                "phone_number": "+5491111111111",
                "email": "claim@example.com",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        client.post(f"/api/client-lead-sources/{source_id}/sync")

        pending = client.get("/api/client-lead-deliveries/pending")
        assert pending.status_code == 200
        assert len(pending.json()["notifications"]) == 1
        delivery_id = pending.json()["notifications"][0]["delivery_id"]
        before_claim = ClientLeadDelivery.get_by_id(delivery_id)
        assert before_claim is not None
        assert before_claim.delivery_status == ClientLeadDeliveryStatus.PENDING

        claimed = client.post("/api/client-lead-deliveries/pending/claim")
        assert claimed.status_code == 200
        assert [item["delivery_id"] for item in claimed.json()["notifications"]] == [delivery_id]

        second_claim = client.post("/api/client-lead-deliveries/pending/claim")
        assert second_claim.status_code == 200
        assert second_claim.json()["notifications"] == []

        pending_after_claim = client.get("/api/client-lead-deliveries/pending")
        assert pending_after_claim.status_code == 200
        assert pending_after_claim.json()["notifications"] == []

        after_claim = ClientLeadDelivery.get_by_id(delivery_id)
        assert after_claim is not None
        assert after_claim.delivery_status == ClientLeadDeliveryStatus.PENDING
        assert after_claim.dispatch_after > before_claim.dispatch_after

        failed = client.post(
            f"/api/client-lead-deliveries/{delivery_id}/delivery-failure",
            json={"error": "temporary provider failure", "max_attempts": 2, "retry_delay_seconds": 0},
        )
        assert failed.status_code == 200
        assert failed.json()["delivery_status"] == "pending"
        assert failed.json()["delivery_attempts"] == 1


def test_client_lead_delivery_status_updates_are_monotonic(monkeypatch, tmp_path) -> None:
    """Late provider failures and sent callbacks should not regress successful rows."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        del source
        return [
            {
                "id": "lead-status-1",
                "created_time": "2026-05-24T10:00:00Z",
                "full_name": "Ana Status",
                "phone_number": "+5491111111111",
                "email": "status@example.com",
            }
        ]

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        client.post(f"/api/client-lead-sources/{source_id}/sync")
        delivery_id = client.get("/api/client-lead-deliveries/pending").json()["notifications"][0]["delivery_id"]

        sent = client.put(
            f"/api/client-lead-deliveries/{delivery_id}/delivery",
            json={"status": "sent", "external_id": "wamid.monotonic.1", "sent_text": "sent ok"},
        )
        assert sent.status_code == 200
        assert sent.json()["delivery_status"] == "sent"

        late_failure = client.post(
            f"/api/client-lead-deliveries/{delivery_id}/delivery-failure",
            json={"error": "late failure", "max_attempts": 1},
        )
        assert late_failure.status_code == 200
        assert late_failure.json()["delivery_status"] == "sent"
        assert late_failure.json()["last_delivery_error"] is None

        delivered = client.put(
            "/api/client-lead-deliveries/delivery/by-external-id",
            json={"external_id": "wamid.monotonic.1", "status": "delivered"},
        )
        assert delivered.status_code == 200
        assert delivered.json()["delivery_status"] == "delivered"

        late_sent = client.put(
            "/api/client-lead-deliveries/delivery/by-external-id",
            json={"external_id": "wamid.monotonic.1", "status": "sent"},
        )
        assert late_sent.status_code == 200
        assert late_sent.json()["delivery_status"] == "delivered"

        delivered_failure = client.post(
            f"/api/client-lead-deliveries/{delivery_id}/delivery-failure",
            json={"error": "late delivered failure", "max_attempts": 1},
        )
        assert delivered_failure.status_code == 200
        assert delivered_failure.json()["delivery_status"] == "delivered"


def test_client_lead_delivery_external_id_duplicates_return_conflict(monkeypatch, tmp_path) -> None:
    """Provider callbacks should not update an arbitrary row when external ids are duplicated."""
    configure_delivery_db(monkeypatch, tmp_path)

    source = ClientLeadSource.upsert(
        source_id="delivery-duplicate-source",
        label="Delivery Duplicate",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        recipient_phone="+5491122223333",
    )
    first, _ = ClientLeadDelivery.upsert_from_sheet_row(
        source=source,
        source_row_key="row-duplicate-1",
        row_number=1,
        raw_row={"id": "row-duplicate-1"},
        full_name="Uno",
        phone_number="+5491111111111",
        email=None,
        created_time=None,
        wa_link="",
        notification_text="uno",
    )
    second, _ = ClientLeadDelivery.upsert_from_sheet_row(
        source=source,
        source_row_key="row-duplicate-2",
        row_number=2,
        raw_row={"id": "row-duplicate-2"},
        full_name="Dos",
        phone_number="+5491111111112",
        email=None,
        created_time=None,
        wa_link="",
        notification_text="dos",
    )
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE client_lead_deliveries SET external_id = ? WHERE id IN (?, ?)",
            ("wamid.duplicate", first.id, second.id),
        )

    with pytest.raises(HTTPException) as error:
        asyncio.run(
            client_leads_endpoints.update_client_lead_delivery_by_external_id(
                client_leads_endpoints.ClientLeadDeliveryByExternalIdCommand(
                    external_id="wamid.duplicate",
                    status="delivered",
                )
            )
        )
    assert error.value.status_code == 409
    assert error.value.detail == "Duplicate Delivery external_id: wamid.duplicate"


def test_client_lead_delivery_external_id_unique_index_blocks_duplicates(monkeypatch, tmp_path) -> None:
    """Non-empty Delivery external ids should be unique below the helper layer."""
    configure_delivery_db(monkeypatch, tmp_path)

    source = ClientLeadSource.upsert(
        source_id="delivery-index-source",
        label="Delivery Index",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        recipient_phone="+5491122223333",
    )
    first, _ = ClientLeadDelivery.upsert_from_sheet_row(
        source=source,
        source_row_key="row-1",
        row_number=1,
        raw_row={"id": "row-1"},
        full_name="Uno",
        phone_number="+5491111111111",
        email=None,
        created_time=None,
        wa_link="",
        notification_text="uno",
    )
    second, _ = ClientLeadDelivery.upsert_from_sheet_row(
        source=source,
        source_row_key="row-2",
        row_number=2,
        raw_row={"id": "row-2"},
        full_name="Dos",
        phone_number="+5491111111112",
        email=None,
        created_time=None,
        wa_link="",
        notification_text="dos",
    )
    assert ClientLeadDelivery.update_delivery_status(
        delivery_id=first.id,
        delivery_status="sent",
        external_id="wamid.delivery.unique",
        sent_text="sent",
    )

    database_module.ensure_client_lead_delivery_external_id_index()

    with pytest.raises(ValueError, match="Duplicate Delivery external_id"):
        ClientLeadDelivery.update_delivery_status(
            delivery_id=second.id,
            delivery_status="sent",
            external_id="wamid.delivery.unique",
            sent_text="sent",
        )
    with pytest.raises(IntegrityError):
        with database_module.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE client_lead_deliveries SET external_id = ? WHERE id = ?",
                ("wamid.delivery.unique", second.id),
            )

    with database_module.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE client_lead_deliveries SET external_id = '' WHERE id IN (?, ?)", (first.id, second.id))


def test_meta_lead_form_routing_rejects_enabled_duplicates(monkeypatch, tmp_path) -> None:
    """Only one enabled Delivery source can own a Meta lead form id."""
    configure_delivery_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        first = client.post(
            "/api/client-lead-sources",
            json=source_payload(id="meta-source-1", meta_lead_form_id="form_unique_1"),
        )
        duplicate = client.post(
            "/api/client-lead-sources",
            json=source_payload(id="meta-source-2", meta_lead_form_id="form_unique_1"),
        )
        disabled = client.post(
            "/api/client-lead-sources",
            json=source_payload(id="meta-source-3", enabled=False, meta_lead_form_id="form_unique_1"),
        )

    assert first.status_code == 200
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "Duplicate enabled Meta lead form routing: form_unique_1"
    assert disabled.status_code == 200


def test_meta_lead_webhook_ambiguous_form_id_fails_closed(monkeypatch, tmp_path) -> None:
    """Legacy duplicate enabled form ids should not route webhook leads to the first row."""
    configure_delivery_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_LEAD_WEBHOOK_APP_SECRET", "meta-secret")
    monkeypatch.setattr(database_module, "ensure_client_lead_source_meta_form_id_index", lambda: None)

    def fail_import(*args, **kwargs):
        raise AssertionError("ambiguous webhook routing should not import")

    monkeypatch.setattr(meta_leads_endpoints, "fetch_and_import_meta_lead_form_record", fail_import)

    first = ClientLeadSource.upsert(
        source_id="ambiguous-meta-1",
        label="Ambiguous One",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        recipient_phone="+5491122223333",
        meta_lead_form_id="form_ambiguous",
    )
    second = ClientLeadSource.upsert(
        source_id="ambiguous-meta-2",
        label="Ambiguous Two",
        enabled=False,
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        recipient_phone="+5491122223334",
        meta_lead_form_id="form_ambiguous",
    )
    with database_module.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE client_lead_sources SET enabled = 1 WHERE id = ?", (second.id,))

    body, headers = signed_meta_webhook_body(
        {
            "object": "page",
            "entry": [
                {
                    "id": "page_1",
                    "changes": [
                        {
                            "field": "leadgen",
                            "value": {
                                "leadgen_id": "webhook-ambiguous",
                                "form_id": "form_ambiguous",
                                "page_id": "page_1",
                            },
                        }
                    ],
                }
            ],
        }
    )

    with TestClient(app) as client:
        response = client.post("/api/meta-leads/webhook", content=body, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["failed"] == 1
    assert payload["processed"] == 0
    assert payload["items"][0]["status"] == "failed"
    assert "Ambiguous Meta lead form routing" in payload["items"][0]["detail"]
    events = PlatformEvent.list_recent(target_type="meta_lead", target_id="webhook-ambiguous", limit=5)
    assert [event.event_type for event in events] == ["client_lead.meta_webhook_ambiguous"]
    assert first.id != second.id


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
    assert client_leads_endpoints.public_csv_url(
        "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=456",
        None,
    ) == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=456"
    assert client_leads_endpoints.public_csv_url(
        "https://spreadsheets.google.com/spreadsheets/d/abc123/gviz/tq?tqx=out:csv&gid=456",
        None,
    ) == "https://docs.google.com/spreadsheets/d/abc123/export?format=csv&gid=456"
    assert client_leads_endpoints.rows_to_records([["Name", "phone"], ["Ana", "+5491111111111"]]) == [
        {"Name": "Ana", "phone": "+5491111111111"}
    ]
    assert client_leads_endpoints.records_have_mappable_headers(
        [{"lead_key": "1", "Nombre": "Ana", "Telefono": "+5491111111111"}],
        {"source_id": "lead_key", "full_name": "Nombre", "phone_number": "Telefono"},
    )
    assert not client_leads_endpoints.records_have_mappable_headers(
        [{"<html><body>Sign in</body></html>": ""}],
        {"full_name": "Nombre", "phone_number": "Telefono"},
    )
    assert not client_leads_endpoints.records_have_mappable_headers(
        [{"email": "ana@example.com"}],
        {"email": "email"},
    )
    assert not client_leads_endpoints.records_have_mappable_headers(
        [{"phone_number": "+5491111111111"}],
        {"phone_number": "phone_number"},
    )
    assert client_leads_endpoints.records_have_mappable_headers(
        [{"row_code": "1", "work_phone": "+5491111111111", "contact_name": "Ana"}],
        {"source_id": "row_code", "phone_number": "work_phone", "full_name": "contact_name"},
    )


def test_meta_sheet_append_uses_raw_value_input(monkeypatch) -> None:
    """Meta lead appends should keep Google Sheets in RAW mode."""
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeValuesApi:
        def get(self, **kwargs):
            calls.append(("get", kwargs))
            return SimpleNamespace(execute=lambda: {"values": [["leadgen_id"]]})

        def update(self, **kwargs):
            calls.append(("update", kwargs))
            return SimpleNamespace(execute=lambda: {})

        def append(self, **kwargs):
            calls.append(("append", kwargs))
            return SimpleNamespace(execute=lambda: {"updates": {"updatedRows": 1}})

    class FakeSheetsApi:
        def values(self):
            return FakeValuesApi()

    class FakeService:
        def spreadsheets(self):
            return FakeSheetsApi()

    monkeypatch.setattr(client_leads_endpoints, "service_account_file", lambda: "/tmp/fake-service-account.json")
    monkeypatch.setattr(client_leads_endpoints, "build_sheets_service", lambda *args, **kwargs: FakeService())
    monkeypatch.setattr(client_leads_endpoints, "resolve_range_from_gid", lambda *args, **kwargs: "Leads")

    source = ClientLeadSource(
        label="Meta Sheet",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        sheet_gid="123",
    )
    client_leads_endpoints.append_record_to_sheet(
        source,
        {
            "leadgen_id": "=meta-lead",
            "full_name": "+Formula Lead",
        },
    )

    update_call = next(kwargs for action, kwargs in calls if action == "update")
    append_call = next(kwargs for action, kwargs in calls if action == "append")
    assert update_call["valueInputOption"] == "RAW"
    assert append_call["valueInputOption"] == "RAW"
    assert append_call["body"]["values"] == [["=meta-lead", "+Formula Lead"]]


def test_client_lead_sheet_helpers_reject_ssrf_urls_before_http(monkeypatch) -> None:
    """Sheet URL helpers should reject non-Google URLs before fetches are built."""
    class NoHttpClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs
            raise AssertionError("HTTP client should not be opened for rejected sheet URLs")

    monkeypatch.setattr(client_leads_endpoints.httpx, "AsyncClient", NoHttpClient)
    try:
        client_leads_endpoints.public_csv_url("https://evil.example/export?format=csv", None)
    except ValueError as exc:
        assert "Google Sheets" in str(exc)
    else:
        raise AssertionError("Non-Google CSV URL was accepted")
    try:
        client_leads_endpoints.public_csv_url("http://169.254.169.254/latest/meta-data?format=csv", None)
    except ValueError as exc:
        assert "Google Sheets" in str(exc)
    else:
        raise AssertionError("SSRF-ish sheet URL was accepted")
    try:
        asyncio.run(
            client_leads_endpoints.fetch_sheet_records(
                SimpleNamespace(
                    sheet_url="http://169.254.169.254/latest/meta-data?format=csv",
                    sheet_gid=None,
                    sheet_tab_name=None,
                )
            )
        )
    except ValueError as exc:
        assert "Google Sheets" in str(exc)
    else:
        raise AssertionError("SSRF-ish sheet URL was fetched")


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


def test_client_lead_sync_rejects_wrong_tab_with_single_matching_header(monkeypatch, tmp_path) -> None:
    """A wrong tab with one weak matching header should fail before import."""
    configure_delivery_db(monkeypatch, tmp_path)

    async def fake_fetch_sheet_records(source):
        if not client_leads_endpoints.records_have_mappable_headers(
            [{"email": "ana@example.com"}],
            source.column_mapping,
        ):
            raise RuntimeError(client_leads_endpoints.invalid_sheet_headers_message())
        return []

    monkeypatch.setattr(client_leads_endpoints, "fetch_sheet_records", fake_fetch_sheet_records)

    with TestClient(app) as client:
        source_id = client.post("/api/client-lead-sources", json=source_payload()).json()["id"]
        sync = client.post(f"/api/client-lead-sources/{source_id}/sync")
        assert sync.status_code == 502
        assert "Wrong Delivery sheet tab" in sync.json()["detail"]

        sources = client.get("/api/client-lead-sources").json()["sources"]
        failed_source = next(source for source in sources if source["id"] == source_id)
        assert failed_source["last_sync_status"] == "failed"
        assert "Wrong Delivery sheet tab" in failed_source["last_sync_note"]


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
              "context_fields": ["campaign_name", "ad_name"],
              "sheets": [
                {
                  "id": "deuda",
                  "label": "Deuda",
                  "sheet_url": "https://docs.google.com/spreadsheets/d/deuda-sheet/edit",
                  "sheet_tab_name": "deuda",
                  "context_field_mapping": {
                    "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
                    "Caso": "breve_descripción_de_su_caso"
                  }
                },
                {
                  "id": "simple",
                  "label": "Simple Form Setup",
                  "sheet_url": "https://docs.google.com/spreadsheets/d/simple-sheet/edit",
                  "sheet_tab_name": "simple form setup 2026-05-25",
                  "column_mapping": {
                    "full_name": "contact_name",
                    "phone_number": "work_phone",
                    "email": "work_email"
                  }
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
    assert sources["mmb-ads-deuda-ana"]["column_mapping"]["email"] == "email"
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["source_id"] == "id"
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["created_time"] == "timestamp"
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["full_name"] == "contact_name"
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["phone_number"] == "work_phone"
    assert sources["mmb-ads-simple-luis"]["column_mapping"]["email"] == "work_email"
    assert sources["mmb-ads-deuda-ana"]["context_field_mapping"] == {
        "Tipo de deuda": "¿qué_tipo_de_deuda_tiene_pendiente?",
        "Caso": "breve_descripción_de_su_caso",
    }
    assert sources["mmb-ads-simple-luis"]["context_field_mapping"] == {
        "campaign_name": "campaign_name",
        "ad_name": "ad_name",
    }
    assert sources["mmb-ads-simple-luis"]["template_name"] == "konecta_delivery_lead_alert_context_es"


def test_client_lead_config_reload_preserves_existing_context_when_omitted(monkeypatch, tmp_path) -> None:
    """Server-local config reloads should not erase API-configured context by omission."""
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
              "sheet_url": "https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
              "sheet_gid": "123",
              "sheet_tab_name": "Leads",
              "recipient_phone": "+5491122223333"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH", str(seed_path))
    monkeypatch.setenv("CLIENT_LEAD_SOURCES_CONFIG_PATH", str(config_path))

    with TestClient(app) as client:
        created = client.post(
            "/api/client-lead-sources",
            json=source_payload(context_field_mapping={"Ciudad": "city"}),
        )
        assert created.status_code == 200
        assert created.json()["context_field_mapping"] == {"Ciudad": "city"}

        result = client_lead_config.sync_client_lead_sources_from_config()
        assert result.errors == []

        payload = client.get("/api/client-lead-sources").json()

    sources = {source["id"]: source for source in payload["sources"]}
    assert sources["mmb-ads"]["context_field_mapping"] == {"Ciudad": "city"}
    assert sources["mmb-ads"]["template_name"] == "konecta_delivery_lead_alert_context_es"


def test_delivery_count_by_status_aggregates_in_sql_shape(monkeypatch, tmp_path) -> None:
    """Delivery count helper should keep per-status response shape."""
    configure_delivery_db(monkeypatch, tmp_path)
    source = ClientLeadSource.upsert(
        source_id="count-source",
        label="Count Source",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        sheet_gid="123",
        recipient_name="Cliente",
        recipient_phone="+5491122223333",
    )
    for row_key, phone, block_reason in [
        ("pending-1", "+5491111111111", ""),
        ("pending-2", "+5491111111112", ""),
        ("blocked-1", "sin telefono", "invalid phone"),
    ]:
        ClientLeadDelivery.upsert_from_sheet_row(
            source=source,
            source_row_key=row_key,
            row_number=1,
            raw_row={"id": row_key, "phone_number": phone},
            full_name="Lead",
            phone_number=phone,
            email="lead@example.com",
            created_time=None,
            wa_link="",
            notification_text="Lead",
            block_reason=block_reason,
        )

    assert ClientLeadDelivery.count_by_status_for_sources()["count-source"] == {
        "pending": 2,
        "blocked": 1,
        "total": 3,
    }


def test_recipient_chat_limits_visible_deliveries_across_sibling_sources(monkeypatch, tmp_path) -> None:
    """Recipient chat should ask SQL for the visible cross-source tail only."""
    configure_delivery_db(monkeypatch, tmp_path)
    first_source = ClientLeadSource.upsert(
        source_id="chat-source-a",
        label="Chat Source A",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=123",
        sheet_gid="123",
        recipient_name="Cliente",
        recipient_phone="+5491122223333",
    )
    second_source = ClientLeadSource.upsert(
        source_id="chat-source-b",
        label="Chat Source B",
        sheet_url="https://docs.google.com/spreadsheets/d/sheet-id/edit#gid=456",
        sheet_gid="456",
        recipient_name="Cliente",
        recipient_phone="+5491122223333",
    )

    for index in range(8):
        source = first_source if index % 2 == 0 else second_source
        item, _ = ClientLeadDelivery.upsert_from_sheet_row(
            source=source,
            source_row_key=f"visible-{index}",
            row_number=index,
            raw_row={"id": f"visible-{index}"},
            full_name=f"Lead {index}",
            phone_number=f"+54911111111{index:02d}",
            email=f"lead{index}@example.com",
            created_time=None,
            wa_link="",
            notification_text=f"Notification {index}",
        )
        with Session(database_module.engine) as session:
            row = session.get(ClientLeadDelivery, item.id)
            row.delivery_status = ClientLeadDeliveryStatus.SENT
            row.sent_text = f"Sent {index}"
            row.sent_at = item.created_at
            session.add(row)
            session.commit()

    for status in [ClientLeadDeliveryStatus.PENDING, ClientLeadDeliveryStatus.BLOCKED]:
        ClientLeadDelivery.upsert_from_sheet_row(
            source=first_source,
            source_row_key=f"hidden-{status.value}",
            row_number=99,
            raw_row={"id": f"hidden-{status.value}"},
            full_name="Hidden",
            phone_number="+5491111111199",
            email="hidden@example.com",
            created_time=None,
            wa_link="",
            notification_text="Hidden",
            block_reason="blocked" if status == ClientLeadDeliveryStatus.BLOCKED else None,
        )

    with TestClient(app) as client:
        response = client.get("/api/client-lead-sources/chat-source-a/recipient-chat?limit=3")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [message["text"] for message in messages] == ["Sent 5", "Sent 6", "Sent 7"]
    assert {message["lead_name"] for message in messages} == {"Lead 5", "Lead 6", "Lead 7"}
    assert {message["delivery_status"] for message in messages} == {"sent"}
