"""Regression tests for the dedicated Contadores flow."""

from __future__ import annotations

import asyncio
import csv
import json
import os
from io import BytesIO, StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import backend.calendar_events as calendar_events_module
import backend.database as database_module
import backend.ai.codex_agent_runtime as codex_agent_runtime
import backend.endpoints.contadores as contadores_endpoints
import backend.endpoints.workstation as workstation_endpoints
import backend.meta_ads_publish as meta_ads_publish_module
import backend.meta_lead_forms as meta_lead_forms_module
import backend.platform_profile_extraction as profile_extraction_module
from backend.audio_transcription import AudioTranscriptionError
from backend.codex_utils import CodexSkill, CodexTurnResult
from backend.meta_ads_inventory import sync_meta_inventory
from backend.redaction import redact_sensitive_text
from backend.ai.contadores_conversation_bot import ContadoresConversationBotResult, REJECTION_SURVEY_REPLY
from backend.contadores_strategies import get_contadores_strategy
from backend.database import (
    AgentRun,
    AgentToolCall,
    ClientLeadSource,
    CONTADORES_LEAD_MANUAL_CONVERTED_REASON,
    ContadoresAlertDelivery,
    ContadoresConfig,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresRuntimeAlert,
    ContadoresSheetSyncState,
    ContadoresStrategyAssignment,
    MessageDeliveryStatus,
    PlatformAdCampaign,
    PlatformClientProfile,
    PlatformClientUpdate,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformHumanQuestion,
    PlatformMetaInventorySnapshot,
    PlatformMeeting,
    PlatformMetaPublishAttempt,
    ScheduledAgentTask,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
    WorkstationMediaAsset,
    WorkstationPublicPage,
    build_contadores_external_lead_id,
)
from backend.funnel_config import get_funnel
from backend.ai.codex_agent_tools import call_tool
from backend.main import app
from backend.tests.support import (
    add_recent_inbound,
    build_abogados_test_funnel,
    build_contadores_test_funnel,
    configure_contadores_db,
    fake_profile_extraction,
    now_utc,
    write_funnels_config,
)



def test_meta_publish_plan_requires_instant_form_delivery_source(monkeypatch, tmp_path) -> None:
    """Instant-form plans should prove how leads enter Client Lead Delivery."""
    configure_contadores_db(monkeypatch, tmp_path)

    blocked_result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-form-1",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados instant form",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "instant_form",
                "page_id": "page_routing_1",
                "lead_form_id": "lead_form_routing_1",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-1",
                                "image_hash": "hash_routing_1",
                                "primary_text": "Si te despidieron, completa tus datos.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-routing-form-blocked-1",
        },
    )
    assert blocked_result["ok"] is True
    assert "destination.client_lead_source_id" in blocked_result["result"]["required_before_live_publish"]

    ClientLeadSource.upsert(
        source_id="abogados-meta-form-leads",
        label="Abogados Meta form leads",
        enabled=True,
        sheet_url="https://docs.google.com/spreadsheets/d/client/export?format=csv&gid=0",
        sheet_gid="0",
        recipient_name="Alan",
        recipient_phone="+5491111111111",
    )

    ready_result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-form-2",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados instant form ready",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "instant_form",
                "page_id": "page_routing_1",
                "lead_form_id": "lead_form_routing_1",
                "client_lead_source_id": "abogados-meta-form-leads",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-2",
                                "image_hash": "hash_routing_2",
                                "primary_text": "Si te despidieron, completa tus datos.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-routing-form-ready-1",
        },
    )
    assert ready_result["ok"] is True
    assert ready_result["result"]["required_before_live_publish"] == []
    payload = ready_result["result"]["attempt"]["request_payload"]
    assert payload["lead_routing"]["route_type"] == "client_lead_delivery_source"
    assert payload["lead_routing"]["client_lead_source_id"] == "abogados-meta-form-leads"


def test_meta_publish_plan_blocks_wrong_whatsapp_source_mapping(monkeypatch, tmp_path) -> None:
    """A provided CTWA source id must map to the same funnel before live publish."""
    configure_contadores_db(monkeypatch, tmp_path)
    write_funnels_config(
        tmp_path,
        build_abogados_test_funnel(referral_ids=["ctwa-good-source"]),
        build_contadores_test_funnel(),
    )

    result = call_tool(
        run_id="agent-run-meta-routing",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-routing-wa-1",
            "client_id": "client-routing-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_routing_1",
            "campaign_name": "Abogados WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_routing_1",
                "whatsapp_phone_number_id": "wa_phone_routing_1",
                "whatsapp_referral_source_id": "ctwa-wrong-source",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-routing-wa-1",
                                "image_hash": "hash_routing_wa_1",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-routing-wa-wrong-1",
        },
    )

    assert result["ok"] is True
    assert "destination.whatsapp_referral_source_id.funnel_mapping" in result["result"][
        "required_before_live_publish"
    ]
    payload = result["result"]["attempt"]["request_payload"]
    assert payload["lead_routing"]["whatsapp_referral_source_id"] == "ctwa-wrong-source"
    assert payload["lead_routing"]["mapped_funnel_ids"] == []


def test_meta_inventory_sync_persists_read_only_inventory(monkeypatch, tmp_path) -> None:
    """Meta inventory sync should persist sanitized read-only provider state."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    for env_name in (
        "META_PAGE_IDS",
        "META_PAGE_ID",
        "META_WHATSAPP_BUSINESS_ACCOUNT_IDS",
        "META_WHATSAPP_BUSINESS_ACCOUNT_ID",
        "META_WHATSAPP_PHONE_NUMBER_IDS",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    ):
        monkeypatch.delenv(env_name, raising=False)

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        del params
        if path == "me/adaccounts":
            return {"data": [{"id": "act_123", "name": "Agency account", "currency": "USD"}]}
        if path == "act_123":
            return {"id": "act_123", "name": "Agency account", "account_status": 1}
        if path == "act_123/campaigns":
            return {"data": [{"id": "campaign_1", "name": "Existing campaign", "status": "PAUSED"}]}
        if path == "act_123/adspixels":
            return {"data": [{"id": "pixel_1", "name": "Main pixel"}]}
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "Client Page", "access_token": "secret-page-token"}]}
        if path == "page_1/leadgen_forms":
            return {"data": [{"id": "form_1", "name": "Lead form", "status": "ACTIVE"}]}
        if path == "business_1/owned_whatsapp_business_accounts":
            return {"data": [{"id": "waba_1", "name": "WABA"}]}
        if path == "waba_1/phone_numbers":
            return {"data": [{"id": "wa_phone_1", "display_phone_number": "+54 9 11 1234-5678"}]}
        raise AssertionError(path)

    snapshot, result = sync_meta_inventory(
        ad_account_id="act_123",
        business_id="business_1",
        source="test",
        actor="tester",
        graph_get=fake_graph_get,
    )

    assert result.status == "ready"
    assert snapshot.status == "ready"
    assert snapshot.inventory()["ad_accounts"][0]["id"] == "act_123"
    assert snapshot.inventory()["pages"][0].get("access_token") is None
    assert snapshot.inventory()["lead_forms"][0]["page_id"] == "page_1"
    assert snapshot.inventory()["whatsapp_phone_numbers"][0]["id"] == "wa_phone_1"
    assert PlatformEvent.list_recent(target_type="meta_inventory", target_id=snapshot.id)[0].event_type == "meta_inventory.synced"


def test_meta_inventory_sync_uses_configured_env_ids(monkeypatch, tmp_path) -> None:
    """Agents should get a complete inventory snapshot without knowing configured Meta IDs."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_env")
    monkeypatch.setenv("META_BUSINESS_ID", "business_env")
    monkeypatch.setenv("META_PAGE_ID", "page_env")
    monkeypatch.setenv("META_WHATSAPP_BUSINESS_ACCOUNT_ID", "waba_env")
    monkeypatch.setenv("META_WHATSAPP_PHONE_NUMBER_ID", "wa_phone_env")
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    calls: list[str] = []

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        del params
        calls.append(path)
        if path == "me/adaccounts":
            return {"data": [{"id": "act_env", "name": "Configured account"}]}
        if path == "act_env":
            return {"id": "act_env", "name": "Configured account"}
        if path == "act_env/campaigns":
            return {"data": [{"id": "campaign_env", "name": "Configured campaign"}]}
        if path == "act_env/adspixels":
            return {"data": [{"id": "pixel_env", "name": "Configured pixel"}]}
        if path == "me/accounts":
            return {"data": []}
        if path == "page_env":
            return {"id": "page_env", "name": "Configured page"}
        if path == "page_env/leadgen_forms":
            return {"data": []}
        if path == "business_env/owned_whatsapp_business_accounts":
            return {"data": []}
        if path == "waba_env":
            return {"id": "waba_env", "name": "Configured WABA"}
        if path == "waba_env/phone_numbers":
            return {"data": [{"id": "wa_phone_env", "display_phone_number": "+39 333 824 6345"}]}
        raise AssertionError(path)

    snapshot, result = sync_meta_inventory(source="test", actor="tester", graph_get=fake_graph_get)

    inventory = snapshot.inventory()
    assert result.status == "ready"
    assert result.ad_account_id == "act_env"
    assert result.business_id == "business_env"
    assert inventory["selected_ad_account"]["id"] == "act_env"
    assert inventory["campaigns"][0]["id"] == "campaign_env"
    assert inventory["pixels"][0]["id"] == "pixel_env"
    assert inventory["pages"][0]["id"] == "page_env"
    assert inventory["whatsapp_business_accounts"][0]["id"] == "waba_env"
    assert inventory["whatsapp_phone_numbers"][0]["id"] == "wa_phone_env"
    assert "page_env" in calls
    assert "waba_env" in calls


def test_meta_inventory_sync_redacts_access_token_from_errors(monkeypatch, tmp_path) -> None:
    """Meta inventory errors must not persist provider URLs with raw tokens."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    for env_name in (
        "META_PAGE_IDS",
        "META_PAGE_ID",
        "META_WHATSAPP_BUSINESS_ACCOUNT_IDS",
        "META_WHATSAPP_BUSINESS_ACCOUNT_ID",
        "META_WHATSAPP_PHONE_NUMBER_IDS",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    ):
        monkeypatch.delenv(env_name, raising=False)

    def fake_graph_get(path: str, params: dict | None = None) -> dict:
        del params
        if path == "me/adaccounts":
            return {"data": [{"id": "act_123", "name": "Agency account"}]}
        if path == "act_123":
            return {"id": "act_123", "name": "Agency account"}
        if path == "act_123/campaigns":
            return {"data": []}
        if path == "act_123/adspixels":
            return {"data": []}
        if path == "me/accounts":
            return {"data": [{"id": "page_1", "name": "Client Page"}]}
        if path == "page_1/leadgen_forms":
            raise RuntimeError("403 for https://graph.facebook.com/v25.0/page_1/leadgen_forms?access_token=secret-token&limit=50")
        if path == "business_1/owned_whatsapp_business_accounts":
            return {"data": []}
        raise AssertionError(path)

    snapshot, result = sync_meta_inventory(
        ad_account_id="act_123",
        business_id="business_1",
        source="test",
        actor="tester",
        graph_get=fake_graph_get,
    )

    error_text = json.dumps(result.errors + snapshot.errors())
    assert result.status == "partial"
    assert "secret-token" not in error_text
    assert "access_token=[redacted]" in error_text


def test_meta_lead_form_write_tools_are_gated_and_post_expected_payloads(monkeypatch, tmp_path) -> None:
    """Lead form creation and webhook subscription should share the Meta live-write gate."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)

    blocked = call_tool(
        run_id="agent-run-meta-lead-form-blocked",
        tool_name="create_meta_lead_form",
        arguments={
            "page_id": "page_1",
            "name": "Consulta laboral",
            "privacy_policy_url": "https://example.com/privacy",
            "reason": "Test blocked gate.",
            "idempotency_key": "meta-lead-form-blocked-1",
        },
    )
    assert blocked["ok"] is True
    assert blocked["result"]["status"] == "blocked"
    assert "live_writes_requested" in blocked["result"]["blocked"]
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in blocked["result"]["blocked"]

    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    calls = []

    def fake_graph_post(path: str, params: dict) -> dict:
        calls.append((path, params))
        if path == "page_1/leadgen_forms":
            assert params["name"] == "Consulta laboral"
            assert params["privacy_policy"]["url"] == "https://example.com/privacy"
            assert params["questions"] == [{"type": "FULL_NAME"}]
            return {"id": "form_created_1"}
        if path == "page_1/subscribed_apps":
            assert params["subscribed_fields"] == "leadgen"
            return {"success": True}
        raise AssertionError(path)

    created = meta_lead_forms_module.create_meta_lead_form(
        meta_lead_forms_module.CreateMetaLeadFormArgs(
            page_id="page_1",
            name="Consulta laboral",
            questions=[{"type": "FULL_NAME"}],
            privacy_policy_url="https://example.com/privacy",
            live_writes_requested=True,
            reason="Create test form.",
        ),
        graph_post=fake_graph_post,
        source="test",
        actor="tester",
    )
    subscribed = meta_lead_forms_module.subscribe_meta_lead_webhook(
        meta_lead_forms_module.SubscribeMetaLeadWebhookArgs(
            page_id="page_1",
            live_writes_requested=True,
            reason="Subscribe test page.",
        ),
        graph_post=fake_graph_post,
        source="test",
        actor="tester",
    )

    assert created.status == "created"
    assert created.lead_form_id == "form_created_1"
    assert subscribed.status == "subscribed"
    assert [path for path, _params in calls] == ["page_1/leadgen_forms", "page_1/subscribed_apps"]


def test_meta_lead_form_writes_are_idempotent(monkeypatch, tmp_path) -> None:
    """Duplicate Meta form/subscription writes should reuse durable success events."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    calls: list[tuple[str, dict]] = []

    def fake_graph_post(path: str, params: dict) -> dict:
        calls.append((path, params))
        if path == "page_1/leadgen_forms":
            return {"id": "form_idempotent_1"}
        if path == "page_1/subscribed_apps":
            return {"success": True}
        raise AssertionError(path)

    form_args = meta_lead_forms_module.CreateMetaLeadFormArgs(
        page_id="page_1",
        name="Consulta laboral",
        questions=[{"type": "FULL_NAME"}],
        privacy_policy_url="https://example.com/privacy",
        live_writes_requested=True,
    )
    created = meta_lead_forms_module.create_meta_lead_form(form_args, graph_post=fake_graph_post)
    repeated = meta_lead_forms_module.create_meta_lead_form(form_args, graph_post=fake_graph_post)
    assert created.lead_form_id == "form_idempotent_1"
    assert repeated.lead_form_id == "form_idempotent_1"

    subscribed = meta_lead_forms_module.subscribe_meta_lead_webhook(
        meta_lead_forms_module.SubscribeMetaLeadWebhookArgs(page_id="page_1", live_writes_requested=True),
        graph_post=fake_graph_post,
    )
    repeated_subscribe = meta_lead_forms_module.subscribe_meta_lead_webhook(
        meta_lead_forms_module.SubscribeMetaLeadWebhookArgs(page_id="page_1", live_writes_requested=True),
        graph_post=fake_graph_post,
    )
    assert subscribed.status == "subscribed"
    assert repeated_subscribe.status == "subscribed"
    assert [path for path, _params in calls] == ["page_1/leadgen_forms", "page_1/subscribed_apps"]

    try:
        meta_lead_forms_module.create_meta_lead_form(
            meta_lead_forms_module.CreateMetaLeadFormArgs(
                page_id="page_1",
                name="Consulta laboral",
                questions=[{"type": "EMAIL"}],
                privacy_policy_url="https://example.com/privacy",
                live_writes_requested=True,
            ),
            graph_post=fake_graph_post,
        )
    except meta_lead_forms_module.MetaLeadFormsError as error:
        assert "idempotency conflict" in str(error)
    else:
        raise AssertionError("Expected conflicting Meta lead form payload to fail")


def test_meta_publish_attempt_idempotency_key_has_db_guard(monkeypatch, tmp_path) -> None:
    """Meta publish idempotency should be enforced below the application lookup."""
    configure_contadores_db(monkeypatch, tmp_path)
    database_module.ensure_platform_meta_publish_attempt_idempotency_index()

    first = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-unique-1",
        request_payload={"objective": "LEADS"},
        idempotency_key="publish-unique-1",
    )
    retry = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-unique-1",
        request_payload={"objective": "LEADS"},
        idempotency_key="publish-unique-1",
    )
    assert retry.id == first.id

    duplicate = PlatformMetaPublishAttempt(
        campaign_id="campaign-unique-1",
        request_json=json.dumps({"objective": "LEADS"}),
        idempotency_key="publish-unique-1",
    )
    raised = False
    with Session(database_module.engine) as session:
        session.add(duplicate)
        try:
            session.commit()
        except IntegrityError:
            raised = True
            session.rollback()
    assert raised is True


def test_platform_logical_identity_indexes_guard_duplicates(monkeypatch, tmp_path) -> None:
    """Platform logical identities should be enforced below read-before-insert helpers."""
    configure_contadores_db(monkeypatch, tmp_path)
    database_module.ensure_platform_logical_identity_indexes()

    event = PlatformEvent.add(event_type="identity.test", idempotency_key="event-key-1")
    assert PlatformEvent.add(event_type="identity.test", idempotency_key="event-key-1").id == event.id
    with pytest.raises(IntegrityError):
        with Session(database_module.engine) as session:
            session.add(PlatformEvent(event_type="identity.raw", idempotency_key="event-key-1"))
            session.commit()

    meeting = PlatformMeeting.add(lead_id="lead-1", idempotency_key="meeting-key-1")
    assert PlatformMeeting.add(lead_id="lead-1", idempotency_key="meeting-key-1").id == meeting.id
    with pytest.raises(IntegrityError):
        with Session(database_module.engine) as session:
            session.add(PlatformMeeting(lead_id="lead-raw", idempotency_key="meeting-key-1"))
            session.commit()

    campaign = PlatformAdCampaign.add(client_id="client-1", idempotency_key="campaign-key-1")
    assert PlatformAdCampaign.add(client_id="client-1", idempotency_key="campaign-key-1").id == campaign.id
    with pytest.raises(IntegrityError):
        with Session(database_module.engine) as session:
            session.add(PlatformAdCampaign(client_id="client-raw", idempotency_key="campaign-key-1"))
            session.commit()

    profile = PlatformClientProfile.upsert(client_id="client-profile-1", business_summary="first")
    updated = PlatformClientProfile.upsert(client_id="client-profile-1", business_summary="second")
    assert updated.id == profile.id
    assert updated.business_summary == "second"
    with pytest.raises(IntegrityError):
        with Session(database_module.engine) as session:
            session.add(PlatformClientProfile(client_id="client-profile-1"))
            session.commit()


def test_meta_creative_asset_upload_patches_publish_plan(monkeypatch, tmp_path) -> None:
    """Generated files should become Meta-ready image hashes before live publish."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    creative_file = data_dir / "meta-assets" / "creative.png"
    creative_file.parent.mkdir(parents=True, exist_ok=True)
    creative_file.write_bytes(b"png-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ads_publish_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")

    asset_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="stage_creative_asset",
        arguments={
            "campaign_id": "campaign-upload-1",
            "client_id": "client-upload-1",
            "asset_type": "image",
            "prompt": "Problem-first ad creative.",
            "file_path": "data/meta-assets/creative.png",
            "idempotency_key": "stage-upload-asset-1",
        },
    )
    assert asset_result["ok"] is True
    asset_id = asset_result["result"]["asset"]["id"]

    plan_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-upload-1",
            "client_id": "client-upload-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_upload_1",
            "campaign_name": "Abogados upload - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_upload_1",
                "whatsapp_phone_number_id": "wa_phone_upload_1",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": asset_id,
                                "asset_file_path": "data/meta-assets/creative.png",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-upload-agent-1",
        },
    )
    assert plan_result["ok"] is True
    attempt_id = plan_result["result"]["attempt"]["id"]

    live_preflight_before_upload = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "preflight-upload-before-1",
        },
    )
    assert live_preflight_before_upload["ok"] is True
    assert "ad_sets[1].ads[1].creative.meta_asset" in live_preflight_before_upload["result"]["preflight"][
        "blocked_reasons"
    ]

    upload_calls: list[tuple[str, Path, str, dict]] = []

    def fake_graph_uploader(*, api_version: str, access_token: str, timeout: float = 120):
        assert api_version == "v25.0"
        assert access_token == "test-token"
        assert timeout == 120

        def graph_upload(path: str, file_path: Path, file_field: str, params: dict) -> dict:
            upload_calls.append((path, file_path, file_field, params))
            assert file_path.read_bytes() == b"png-bytes"
            return {"images": {file_path.name: {"hash": "hash_uploaded_1", "access_token": "do-not-store"}}}

        return graph_upload

    monkeypatch.setattr(meta_ads_publish_module, "_default_graph_uploader", fake_graph_uploader)
    upload_result = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="upload_meta_creative_asset",
        arguments={
            "asset_id": asset_id,
            "ad_account_id": "act_upload_1",
            "live_writes_requested": True,
            "idempotency_key": "upload-meta-creative-1",
        },
    )
    assert upload_result["ok"] is True
    assert upload_result["result"]["upload"]["status"] == "uploaded"
    assert upload_result["result"]["upload"]["image_hash"] == "hash_uploaded_1"
    assert upload_result["result"]["upload"]["linked_publish_attempts"] == [attempt_id]
    assert upload_calls[0][0] == "/act_upload_1/adimages"
    assert upload_calls[0][2] == "filename"

    uploaded_asset = PlatformCreativeAsset.get_by_id(asset_id)
    assert uploaded_asset.status == "uploaded_to_meta"
    assert uploaded_asset.image_hash == "hash_uploaded_1"
    assert "access_token" not in json.dumps(uploaded_asset.meta_upload_response())

    retry_upload = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="upload_meta_creative_asset",
        arguments={
            "asset_id": asset_id,
            "ad_account_id": "act_upload_1",
            "live_writes_requested": True,
            "idempotency_key": "upload-meta-creative-retry-1",
        },
    )
    assert retry_upload["ok"] is True
    assert retry_upload["result"]["upload"]["status"] == "already_uploaded"
    assert retry_upload["result"]["upload"]["image_hash"] == "hash_uploaded_1"
    assert len(upload_calls) == 1

    patched_plan = PlatformMetaPublishAttempt.get_by_id(attempt_id).request_payload()
    patched_creative = patched_plan["ad_sets"][0]["ads"][0]["creative"]
    assert patched_creative["image_hash"] == "hash_uploaded_1"

    live_preflight_after_upload = call_tool(
        run_id="agent-run-meta-creative-upload",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "preflight-upload-after-1",
        },
    )
    assert live_preflight_after_upload["ok"] is True
    assert "ad_sets[1].ads[1].creative.meta_asset" not in live_preflight_after_upload["result"]["preflight"][
        "blocked_reasons"
    ]


def test_meta_creative_asset_upload_blocks_without_credentials(monkeypatch, tmp_path) -> None:
    """Agent-native uploads should report exact blockers instead of trying live writes."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    asset = PlatformCreativeAsset.add(
        campaign_id="campaign-upload-blocked-1",
        client_id="client-upload-blocked-1",
        asset_type="image",
        file_path="data/meta-assets/missing.png",
    )
    result = call_tool(
        run_id="agent-run-meta-creative-upload-blocked",
        tool_name="upload_meta_creative_asset",
        arguments={
            "asset_id": asset.id,
            "ad_account_id": "act_upload_blocked_1",
            "live_writes_requested": True,
            "idempotency_key": "upload-meta-creative-blocked-1",
        },
    )
    assert result["ok"] is True
    blockers = result["result"]["upload"]["blocked_reasons"]
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in blockers
    assert "META_MARKETING_ACCESS_TOKEN" in blockers
    assert "META_MARKETING_API_VERSION" in blockers
    assert "asset.file_path.exists" in blockers
    assert PlatformCreativeAsset.get_by_id(asset.id).status == "upload_blocked"


def test_meta_creative_upload_retries_saved_provider_ref_after_local_ref_loss(monkeypatch, tmp_path) -> None:
    """Retry should reuse a successful durable upload attempt before writing again to Meta."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    creative_file = data_dir / "meta-assets" / "creative.png"
    creative_file.parent.mkdir(parents=True, exist_ok=True)
    creative_file.write_bytes(b"png-bytes")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ads_publish_module, "DATA_DIR", data_dir)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    asset = PlatformCreativeAsset.add(
        campaign_id="campaign-upload-retry-1",
        client_id="client-upload-retry-1",
        asset_type="image",
        file_path="data/meta-assets/creative.png",
        status="upload_provider_succeeded",
        meta_upload_response={
            "schema_version": "konecta.meta_creative_upload_attempt.v1",
            "status": "uploaded",
            "ad_account_id": "act_upload_retry_1",
            "provider_asset_type": "image",
            "file_path": str(creative_file),
            "file_size_bytes": len(b"png-bytes"),
            "file_sha256": "ea80334363eed145dfeee51ebae7dc3f1cd7d0c7879f8bfd2070c061d3c33f56",
            "path": "/act_upload_retry_1/adimages",
            "file_field": "filename",
            "request_params": {"name": "creative.png"},
            "response": {"images": {"creative.png": {"hash": "hash_saved_retry"}}},
            "image_hash": "hash_saved_retry",
        },
    )
    upload_calls: list[str] = []

    def fake_upload(path: str, file_path: Path, file_field: str, params: dict) -> dict:
        del file_path, file_field, params
        upload_calls.append(path)
        return {"images": {"creative.png": {"hash": "hash_should_not_upload"}}}

    updated_asset, result = meta_ads_publish_module.upload_meta_creative_asset(
        asset_id=asset.id,
        ad_account_id="act_upload_retry_1",
        live_writes_requested=True,
        graph_upload=fake_upload,
    )

    assert result.status == "already_uploaded"
    assert result.image_hash == "hash_saved_retry"
    assert updated_asset.image_hash == "hash_saved_retry"
    assert upload_calls == []


def test_meta_publish_approval_blocks_unproven_meta_creative_id(monkeypatch, tmp_path) -> None:
    """Manual Meta creative IDs should be proven by inventory before live approval."""
    configure_contadores_db(monkeypatch, tmp_path)
    plan = {
        "schema_version": "konecta.meta_publish_plan.v1",
        "provider": "meta_marketing_api",
        "funnel_id": "contadores",
        "ad_account_id": "act_creative_id_1",
        "campaign": {"name": "Creative ID validation", "objective": "OUTCOME_LEADS"},
        "destination": {
            "destination_type": "landing_page",
            "landing_page_url": "https://crm.fgoiriz.com/c/opaque-id/",
        },
        "ad_sets": [
            {
                "name": "Creative ID ad set",
                "budget_daily_usd": 10,
                "targeting": {"geo_locations": {"countries": ["AR"]}},
                "ads": [
                    {
                        "name": "Creative ID ad",
                        "creative": {
                            "meta_creative_id": "creative_not_in_inventory",
                            "primary_text": "Texto",
                            "headline": "Titulo",
                        },
                    }
                ],
            }
        ],
    }
    attempt = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-creative-id-1",
        request_payload=plan,
        idempotency_key="publish-creative-id-1",
    )
    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_creative_id_1",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_creative_id_1", "currency": "USD"}],
            "selected_ad_account": {"id": "act_creative_id_1", "currency": "USD"},
            "pages": [],
            "lead_forms": [],
            "whatsapp_phone_numbers": [],
            "campaigns": [],
        },
    )

    _updated, approval = meta_ads_publish_module.approve_meta_publish_attempt(
        attempt_id=attempt.id,
        approved_by="facundo",
        approve_live_writes=True,
        max_daily_budget_usd=50,
        max_estimated_monthly_budget_usd=1500,
    )

    assert approval.approved is False
    assert "meta_inventory.ad_sets[1].ads[1].creative.meta_creative_id" in approval.blocked_reasons


def test_meta_publish_plan_applies_campaign_pixel_optimization(monkeypatch, tmp_path) -> None:
    """Owned campaign pixel optimization should become Meta ad-set params."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    campaign = PlatformAdCampaign.add(
        client_id="client-pixel-opt-1",
        funnel_id="contadores",
        status="draft",
        objective="lead_capture_form",
        creative_testing={
            "destination": "owned_form",
            "meta_optimization": {
                "enabled": True,
                "pixel_id": "1234567890",
                "event_name": "Lead",
                "custom_event_type": "LEAD",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "billing_event": "IMPRESSIONS",
                "promoted_object": {"pixel_id": "1234567890", "custom_event_type": "LEAD"},
            },
        },
    )

    plan_result = call_tool(
        run_id="agent-run-meta-pixel-optimization",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": campaign.id,
            "client_id": "client-pixel-opt-1",
            "funnel_id": "contadores",
            "ad_account_id": "act_pixel_opt_1",
            "campaign_name": "Contadores pixel optimized",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "landing_page",
                "page_id": "page_pixel_opt_1",
                "landing_page_url": "https://crm.fgoiriz.com/c/opaque-id/",
            },
            "ad_sets": [
                {
                    "name": "Pixel optimized leads",
                    "budget_daily_usd": 20,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Lead form ad",
                            "creative": {
                                "image_hash": "hash_pixel_opt_1",
                                "primary_text": "Completa el formulario y te contactamos.",
                                "headline": "Recibi asesoramiento",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-pixel-opt-agent-1",
        },
    )
    assert plan_result["ok"] is True
    assert plan_result["result"]["required_before_live_publish"] == []
    attempt_id = plan_result["result"]["attempt"]["id"]
    plan_payload = PlatformMetaPublishAttempt.get_by_id(attempt_id).request_payload()
    ad_set = plan_payload["ad_sets"][0]
    assert plan_payload["meta_optimization"]["enabled"] is True
    assert ad_set["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert ad_set["billing_event"] == "IMPRESSIONS"
    assert ad_set["promoted_object"] == {"pixel_id": "1234567890", "custom_event_type": "LEAD"}

    preflight_result = call_tool(
        run_id="agent-run-meta-pixel-optimization",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "idempotency_key": "preflight-pixel-opt-1"},
    )
    assert preflight_result["ok"] is True
    ad_set_operation = preflight_result["result"]["preflight"]["operations"][1]
    assert ad_set_operation["object_type"] == "ad_set"
    assert ad_set_operation["params"]["optimization_goal"] == "OFFSITE_CONVERSIONS"
    assert ad_set_operation["params"]["billing_event"] == "IMPRESSIONS"
    assert ad_set_operation["params"]["promoted_object"] == {
        "pixel_id": "1234567890",
        "custom_event_type": "LEAD",
    }


def test_meta_publish_approval_gate_requires_inventory_and_budget(monkeypatch, tmp_path) -> None:
    """Meta approval should be explicit, budget-capped, inventory-backed, and still no live write."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    plan_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert plan_result["ok"] is True
    attempt_id = plan_result["result"]["attempt"]["id"]

    idempotency_conflict = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - changed",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert idempotency_conflict["ok"] is False
    assert "idempotency conflict" in idempotency_conflict["error"]

    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    unapproved_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "idempotency_key": "preflight-approval-unapproved-1"},
    )
    assert unapproved_preflight["ok"] is True
    assert unapproved_preflight["result"]["preflight"]["ready_for_live_publish"] is False

    fake_approved_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_attempt",
        arguments={
            "campaign_id": "campaign-fake-approval-1",
            "approval_status": "approved",
            "request_payload": {
                "schema_version": "konecta.meta_publish_plan.v1",
                "provider": "meta_marketing_api",
                "publish_mode": "approved_live_candidate",
                "live_writes_allowed": True,
                "ad_account_id": "act_999",
                "budget_currency": "USD",
                "campaign": {
                    "name": "Fake approved plan",
                    "objective": "OUTCOME_LEADS",
                    "buying_type": "AUCTION",
                    "special_ad_categories": [],
                    "create_status": "PAUSED",
                },
                "destination": {
                    "destination_type": "whatsapp",
                    "page_id": "page_999",
                    "whatsapp_phone_number_id": "wa_phone_999",
                },
                "ad_sets": [
                    {
                        "name": "Fake ad set",
                        "budget_daily_usd": 10,
                        "status": "PAUSED",
                        "targeting": {"geo_locations": {"countries": ["AR"]}},
                        "ads": [
                            {
                                "name": "Fake ad",
                                "status": "PAUSED",
                                "creative": {
                                    "creative_asset_id": "creative-approval-1",
                                    "image_hash": "hash_approval_fake_1",
                                    "primary_text": "Manda tu caso por WhatsApp.",
                                    "headline": "Necesitas ayuda?",
                                },
                            }
                        ],
                    }
                ],
                "required_before_live_publish": [],
            },
            "idempotency_key": "publish-plan-fake-approved-agent-1",
        },
    )
    assert fake_approved_result["ok"] is True
    fake_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": fake_approved_result["result"]["attempt"]["id"],
            "live_writes_requested": True,
            "idempotency_key": "preflight-approval-fake-1",
        },
    )
    assert fake_preflight["ok"] is True
    assert fake_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "meta_publish.approval_gate" in fake_preflight["result"]["preflight"]["blocked_reasons"]
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    blocked_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Test approval should stay blocked until inventory and cap pass.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 50,
            "max_estimated_monthly_budget_usd": 1500,
            "idempotency_key": "approve-blocked-inventory-budget-1",
        },
    )
    assert blocked_result["ok"] is True
    assert blocked_result["result"]["approval"]["approved"] is False
    assert "budget.daily_cap" in blocked_result["result"]["approval"]["blocked_reasons"]
    assert "meta_inventory.ready" in blocked_result["result"]["approval"]["blocked_reasons"]

    inventory_bypass_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Inventory cannot be bypassed for live writes.",
            "approve_live_writes": True,
            "require_inventory_ready": False,
            "max_daily_budget_usd": 100,
            "max_estimated_monthly_budget_usd": 3000,
            "idempotency_key": "approve-inventory-bypass-1",
        },
    )
    assert inventory_bypass_result["ok"] is True
    assert inventory_bypass_result["result"]["approval"]["approved"] is False
    assert "require_inventory_ready=true" in inventory_bypass_result["result"]["approval"]["blocked_reasons"]

    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_999",
        business_id="business_999",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_999", "currency": "USD"}],
            "selected_ad_account": {"id": "act_999", "currency": "USD"},
            "pages": [{"id": "page_999", "name": "Abogados"}],
            "lead_forms": [],
            "pixels": [],
            "whatsapp_business_accounts": [{"id": "waba_999"}],
            "whatsapp_phone_numbers": [{"id": "wa_phone_999", "whatsapp_business_account_id": "waba_999"}],
            "campaigns": [],
        },
    )
    approved_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "approved_by": "facundo",
            "approval_note": "Budget and inventory reviewed.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 100,
            "max_estimated_monthly_budget_usd": 3000,
            "idempotency_key": "approve-live-budget-inventory-1",
        },
    )
    assert approved_result["ok"] is True
    assert approved_result["result"]["approval"]["approved"] is True
    approved_attempt = PlatformMetaPublishAttempt.get_by_id(attempt_id)
    assert approved_attempt.approval_status == "approved"
    assert approved_attempt.request_payload()["live_writes_allowed"] is True
    assert approved_attempt.request_payload()["approval_policy"]["approved_by"] == "facundo"

    blocked_execute = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={"attempt_id": attempt_id, "idempotency_key": "execute-approval-blocked-1"},
    )
    assert blocked_execute["ok"] is True
    assert blocked_execute["result"]["execution"]["status"] == "blocked"
    assert "live_writes_requested=true" in blocked_execute["result"]["execution"]["blocked_reasons"]

    posted: list[tuple[str, dict]] = []

    def fake_graph_poster(*, api_version: str, access_token: str, timeout: float = 30):
        assert api_version == "v25.0"
        assert access_token == "test-token"

        def graph_post(path: str, params: dict) -> dict:
            posted.append((path, params))
            return {"id": f"meta_{len(posted)}", "access_token": "do-not-store"}

        return graph_post

    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.setattr(meta_ads_publish_module, "_default_graph_poster", fake_graph_poster)
    execute_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "execute-approval-live-1",
        },
    )
    assert execute_result["ok"] is True
    assert execute_result["result"]["execution"]["status"] == "submitted"
    assert execute_result["result"]["execution"]["live_write_executed"] is True
    assert [path for path, _ in posted] == [
        "/act_999/campaigns",
        "/act_999/adsets",
        "/act_999/adcreatives",
        "/act_999/ads",
    ]
    assert posted[1][1]["campaign_id"] == "meta_1"
    assert posted[3][1]["adset_id"] == "meta_2"
    assert posted[3][1]["creative"]["creative_id"] == "meta_3"
    execute_payload = PlatformMetaPublishAttempt.get_by_id(attempt_id).response_payload()
    assert execute_payload["schema_version"] == "konecta.meta_publish_execution.v1"
    assert execute_payload["operation_results"][0]["provider_id"] == "meta_1"
    assert "access_token" not in execute_payload["operation_results"][0]["response"]
    updated_plan = PlatformMetaPublishAttempt.get_by_id(attempt_id).request_payload()
    assert updated_plan["lead_routing"]["mapped_source_ids"] == ["meta_4"]
    assert "meta_4" in get_funnel("abogados").whatsapp_referral_source_ids
    routing_events = [
        event
        for event in PlatformEvent.list_recent(target_type="funnel", target_id="abogados")
        if event.event_type == "meta_publish.lead_routing_mapped"
    ]
    assert routing_events[0].payload_dict()["mapped_source_ids"] == ["meta_4"]

    retry_execute = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="execute_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "execute-approval-retry-1",
        },
    )
    assert retry_execute["ok"] is True
    assert retry_execute["result"]["execution"]["status"] == "already_submitted"
    assert retry_execute["result"]["execution"]["live_write_executed"] is False
    assert len(posted) == 4

    failure_plan_result = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-failure-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_998",
            "campaign_name": "Abogados failure - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_998",
                "whatsapp_phone_number_id": "wa_phone_998",
            },
            "ad_sets": [
                {
                    "name": "Despidos",
                    "budget_daily_usd": 10,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "Despido",
                            "creative": {
                                "creative_asset_id": "creative-approval-failure-1",
                                "image_hash": "hash_approval_failure_1",
                                "primary_text": "Si te despidieron, manda tu caso por WhatsApp.",
                                "headline": "Te despidieron?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-failure-agent-1",
        },
    )
    assert failure_plan_result["ok"] is True
    failure_attempt_id = failure_plan_result["result"]["attempt"]["id"]
    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_998",
        business_id="business_998",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_998", "currency": "USD"}],
            "selected_ad_account": {"id": "act_998", "currency": "USD"},
            "pages": [{"id": "page_998", "name": "Abogados"}],
            "lead_forms": [],
            "pixels": [],
            "whatsapp_business_accounts": [{"id": "waba_998"}],
            "whatsapp_phone_numbers": [{"id": "wa_phone_998", "whatsapp_business_account_id": "waba_998"}],
            "campaigns": [],
        },
    )
    failure_approval = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="approve_meta_publish_plan",
        arguments={
            "attempt_id": failure_attempt_id,
            "approved_by": "facundo",
            "approval_note": "Failure path reviewed.",
            "approve_live_writes": True,
            "max_daily_budget_usd": 50,
            "max_estimated_monthly_budget_usd": 1500,
            "idempotency_key": "approve-failure-path-1",
        },
    )
    assert failure_approval["ok"] is True
    failure_posts: list[str] = []

    def failing_graph_post(path: str, params: dict) -> dict:
        del params
        failure_posts.append(path)
        if path.endswith("/adsets"):
            raise RuntimeError("Meta rejected ad set")
        return {"id": f"failure_meta_{len(failure_posts)}"}

    failed_attempt, failed_execution = meta_ads_publish_module.execute_meta_publish_attempt(
        attempt_id=failure_attempt_id,
        live_writes_requested=True,
        graph_post=failing_graph_post,
    )
    assert failed_execution.status == "partial_failed"
    assert failed_execution.operation_results[0].status == "executed"
    assert failed_execution.operation_results[1].status == "failed"
    assert "Meta rejected ad set" in failed_attempt.error
    assert PlatformMetaPublishAttempt.get_by_id(failure_attempt_id).request_payload()["live_execution_state"][
        "operation_results"
    ][0]["provider_id"] == "failure_meta_1"

    idempotent_retry = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="stage_meta_publish_plan",
        arguments={
            "campaign_id": "campaign-approval-1",
            "client_id": "client-approval-1",
            "funnel_id": "abogados",
            "ad_account_id": "act_999",
            "campaign_name": "Abogados aprobacion - WhatsApp",
            "objective": "OUTCOME_LEADS",
            "destination": {
                "destination_type": "whatsapp",
                "page_id": "page_999",
                "whatsapp_phone_number_id": "wa_phone_999",
            },
            "ad_sets": [
                {
                    "name": "Accidentes laborales",
                    "budget_daily_usd": 75,
                    "targeting": {"geo_locations": {"countries": ["AR"]}},
                    "ads": [
                        {
                            "name": "ART no paga",
                            "creative": {
                                "creative_asset_id": "creative-approval-1",
                                "image_hash": "hash_approval_1",
                                "primary_text": "Si la ART no te paga, manda tu caso por WhatsApp.",
                                "headline": "La ART no te pago?",
                            },
                        }
                    ],
                }
            ],
            "idempotency_key": "publish-plan-approval-agent-1",
        },
    )
    assert idempotent_retry["ok"] is True
    assert idempotent_retry["result"]["attempt"]["id"] == redact_sensitive_text(attempt_id)

    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    monkeypatch.delenv("META_MARKETING_API_VERSION", raising=False)
    missing_api_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "preflight-approval-missing-api-1",
        },
    )
    assert missing_api_preflight["ok"] is True
    assert missing_api_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "META_MARKETING_API_VERSION" in missing_api_preflight["result"]["preflight"]["blocked_reasons"]
    assert "meta_publish.approval_gate" not in missing_api_preflight["result"]["preflight"]["blocked_reasons"]
    monkeypatch.delenv("META_MARKETING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    live_preflight = call_tool(
        run_id="agent-run-meta-approval",
        tool_name="preflight_meta_publish_plan",
        arguments={
            "attempt_id": attempt_id,
            "live_writes_requested": True,
            "idempotency_key": "preflight-approval-live-blocked-1",
        },
    )
    assert live_preflight["ok"] is True
    assert live_preflight["result"]["preflight"]["execution_mode"] == "live_blocked"
    assert "META_MARKETING_LIVE_WRITES_ENABLED" in live_preflight["result"]["preflight"]["blocked_reasons"]
    assert "META_MARKETING_ACCESS_TOKEN" in live_preflight["result"]["preflight"]["blocked_reasons"]


def test_meta_publish_approval_blocks_non_usd_ad_account_currency(monkeypatch, tmp_path) -> None:
    """Live Meta approval should fail closed when account currency is not USD."""
    configure_contadores_db(monkeypatch, tmp_path)
    plan = {
        "schema_version": "konecta.meta_publish_plan.v1",
        "provider": "meta_marketing_api",
        "ad_account_id": "act_currency_1",
        "budget_currency": "USD",
        "campaign": {
            "name": "Currency campaign",
            "objective": "OUTCOME_LEADS",
            "buying_type": "AUCTION",
            "special_ad_categories": [],
            "create_status": "PAUSED",
        },
        "funnel_id": "abogados",
        "destination": {
            "destination_type": "whatsapp",
            "page_id": "page_currency_1",
            "whatsapp_phone_number_id": "wa_currency_1",
        },
        "ad_sets": [
            {
                "name": "Currency ad set",
                "budget_daily_usd": 10,
                "status": "PAUSED",
                "targeting": {"geo_locations": {"countries": ["AR"]}},
                "ads": [
                    {
                        "name": "Currency ad",
                        "status": "PAUSED",
                        "creative": {
                            "image_hash": "hash_currency_1",
                            "primary_text": "Manda tu caso por WhatsApp.",
                            "headline": "Necesitas ayuda?",
                        },
                    }
                ],
            }
        ],
        "required_before_live_publish": [],
    }
    attempt = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-currency-1",
        request_payload=plan,
        idempotency_key="publish-currency-1",
    )
    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_currency_1",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_currency_1", "currency": "ARS"}],
            "selected_ad_account": {"id": "act_currency_1", "currency": "ARS"},
            "pages": [{"id": "page_currency_1"}],
            "whatsapp_phone_numbers": [{"id": "wa_currency_1"}],
        },
    )

    _updated, approval = meta_ads_publish_module.approve_meta_publish_attempt(
        attempt_id=attempt.id,
        approved_by="facundo",
        approve_live_writes=True,
        max_daily_budget_usd=50,
        max_estimated_monthly_budget_usd=1500,
    )

    assert approval.approved is False
    assert "ad_account.currency=USD" in approval.blocked_reasons
    assert approval.budget.ad_account_currency == "ARS"


def test_meta_publish_execution_persists_first_provider_id_before_crash(monkeypatch, tmp_path) -> None:
    """A hard crash after one Graph write should not duplicate that write on retry."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    plan = {
        "schema_version": "konecta.meta_publish_plan.v1",
        "provider": "meta_marketing_api",
        "publish_mode": "approved_live_candidate",
        "live_writes_allowed": True,
        "ad_account_id": "act_crash_1",
        "budget_currency": "USD",
        "campaign": {
            "name": "Crash campaign",
            "objective": "OUTCOME_LEADS",
            "buying_type": "AUCTION",
            "special_ad_categories": [],
            "create_status": "PAUSED",
        },
        "funnel_id": "abogados",
        "destination": {
            "destination_type": "whatsapp",
            "page_id": "page_crash_1",
            "whatsapp_phone_number_id": "wa_crash_1",
        },
        "ad_sets": [
            {
                "name": "Crash ad set",
                "budget_daily_usd": 10,
                "status": "PAUSED",
                "targeting": {"geo_locations": {"countries": ["AR"]}},
                "ads": [
                    {
                        "name": "Crash ad",
                        "status": "PAUSED",
                        "creative": {
                            "image_hash": "hash_crash_1",
                            "primary_text": "Manda tu caso por WhatsApp.",
                            "headline": "Necesitas ayuda?",
                        },
                    }
                ],
            }
        ],
        "required_before_live_publish": [],
    }
    attempt = PlatformMetaPublishAttempt.add(
        campaign_id="campaign-crash-1",
        status="approved",
        approval_status="approved",
        request_payload=plan,
        idempotency_key="publish-crash-1",
    )
    PlatformEvent.add(
        event_type="meta_publish.approval_checked",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=attempt.id,
        payload={"approved": True, "approval_status": "approved", "blocked_reasons": []},
    )
    PlatformMetaInventorySnapshot.add(
        status="ready",
        source="test",
        actor="tester",
        ad_account_id="act_crash_1",
        api_version="v25.0",
        inventory={
            "ad_accounts": [{"id": "act_crash_1", "currency": "USD"}],
            "selected_ad_account": {"id": "act_crash_1", "currency": "USD"},
            "pages": [{"id": "page_crash_1"}],
            "whatsapp_phone_numbers": [{"id": "wa_crash_1"}],
        },
    )

    class CrashAfterFirstWrite(BaseException):
        pass

    crash_calls: list[str] = []

    def crashing_post(path: str, params: dict) -> dict:
        del params
        crash_calls.append(path)
        if len(crash_calls) == 1:
            return {"id": "crash_meta_campaign_1"}
        raise CrashAfterFirstWrite()

    try:
        meta_ads_publish_module.execute_meta_publish_attempt(
            attempt_id=attempt.id,
            live_writes_requested=True,
            graph_post=crashing_post,
        )
    except CrashAfterFirstWrite:
        pass
    else:
        raise AssertionError("Expected hard crash after first provider write")

    persisted = PlatformMetaPublishAttempt.get_by_id(attempt.id)
    assert persisted.response_payload()["operation_results"][0]["provider_id"] == "crash_meta_campaign_1"

    retry_calls: list[str] = []

    def retry_post(path: str, params: dict) -> dict:
        retry_calls.append(path)
        if path.endswith("/adsets"):
            assert params["campaign_id"] == "crash_meta_campaign_1"
        return {"id": f"retry_meta_{len(retry_calls)}"}

    _updated, execution = meta_ads_publish_module.execute_meta_publish_attempt(
        attempt_id=attempt.id,
        live_writes_requested=True,
        graph_post=retry_post,
    )

    assert execution.operation_results[0].status == "skipped"
    assert retry_calls[0] == "/act_crash_1/adsets"


def test_meta_creative_asset_upload_blocks_oversized_files(monkeypatch, tmp_path) -> None:
    """Agent-staged creative paths should enforce the platform upload size cap."""
    configure_contadores_db(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"
    creative_file = data_dir / "meta-assets" / "huge.png"
    creative_file.parent.mkdir(parents=True, exist_ok=True)
    creative_file.write_bytes(b"12345")
    monkeypatch.setattr(database_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ads_publish_module, "DATA_DIR", data_dir)
    monkeypatch.setattr(meta_ads_publish_module, "CREATIVE_ASSET_MAX_UPLOAD_BYTES", 4)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")
    asset = PlatformCreativeAsset.add(
        campaign_id="campaign-upload-size-1",
        client_id="client-upload-size-1",
        asset_type="image",
        file_path="data/meta-assets/huge.png",
    )
    upload_calls: list[str] = []

    def fake_upload(path: str, file_path: Path, file_field: str, params: dict) -> dict:
        del file_path, file_field, params
        upload_calls.append(path)
        return {"images": {"huge.png": {"hash": "hash_should_not_upload"}}}

    updated_asset, result = meta_ads_publish_module.upload_meta_creative_asset(
        asset_id=asset.id,
        ad_account_id="act_upload_size_1",
        live_writes_requested=True,
        graph_upload=fake_upload,
    )

    assert result.status == "blocked"
    assert result.file_size_bytes == 5
    assert "asset.file_size<=4" in result.blocked_reasons
    assert upload_calls == []
    assert updated_asset.status == "upload_blocked"
