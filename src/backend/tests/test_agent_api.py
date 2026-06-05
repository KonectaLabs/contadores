"""Tests for the agent API and CLI browser-login auth."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import backend.database as database_module
import backend.endpoints.agent as agent_endpoints
from backend.auth import auth_manager
from backend.database import (
    AgentToolCall,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    PlatformMetaInventorySnapshot,
)
from backend.main import app
from backend.tests.test_contadores import add_recent_inbound, configure_contadores_db


def configure_agent_db(monkeypatch, tmp_path) -> None:
    """Point all agent-facing DB imports at one temporary SQLite database."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setattr(agent_endpoints, "engine", database_module.engine)
    monkeypatch.setenv("AUTH_DISABLE", "true")
    auth_manager.reload_from_env()


def create_agent_lead(
    *,
    external_id: str = "agent-lead-1",
    phone: str = "+5491133344444",
    stage: ContadoresLeadStage | str | None = None,
) -> ContadoresLead:
    """Create one lead suitable for agent API tests."""
    lead = ContadoresLead.upsert(
        external_lead_id=external_id,
        phone=phone,
        full_name="Agent Lead",
        platform="whatsapp",
    )
    if stage is not None:
        lead = ContadoresLead.update_flow_state(lead.id, stage=stage) or lead
    return lead


def move_to_needs_reply(lead: ContadoresLead) -> ContadoresLead:
    """Move a lead to manual attention with a fresh inbound message."""
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_handoff",
        clear_manual_reply_handled_at=True,
    )
    add_recent_inbound(lead.id, text="Me ayudas con esto?")
    return ContadoresLead.get_by_id(lead.id) or lead


def test_cli_login_flow_requires_browser_session_and_revokes_bearer(monkeypatch, tmp_path) -> None:
    """Browser login creates one single-use CLI token and logout revokes it."""
    auth_file = tmp_path / "auth.toml"
    auth_file.write_text("[users]\nfacu = \"secret\"\n", encoding="utf-8")
    monkeypatch.setenv("AUTH_DISABLE", "false")
    monkeypatch.setenv("AUTH_TOML", str(auth_file))
    monkeypatch.setenv("INTERNAL_API_TOKEN", "internal-secret")
    auth_manager.reload_from_env()

    client = TestClient(app)
    unauthenticated = client.get(
        "/api/agent/auth/cli/start",
        params={"callback_url": "http://127.0.0.1:54321/callback", "state": "state-12345"},
        follow_redirects=False,
    )
    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"].startswith("/login?next=")

    login = client.post("/api/auth/login", json={"user": "facu", "password": "secret"})
    assert login.status_code == 200

    rejected_callback = client.get(
        "/api/agent/auth/cli/start",
        params={"callback_url": "https://example.com/callback", "state": "state-12345"},
        follow_redirects=False,
    )
    assert rejected_callback.status_code == 400

    start = client.get(
        "/api/agent/auth/cli/start",
        params={"callback_url": "http://127.0.0.1:54321/callback", "state": "state-12345"},
        follow_redirects=False,
    )
    assert start.status_code == 303
    callback = urlparse(start.headers["location"])
    params = parse_qs(callback.query)
    assert callback.hostname == "127.0.0.1"
    assert params["state"] == ["state-12345"]
    code = params["code"][0]

    exchange = client.post("/api/agent/auth/cli/exchange", json={"code": code})
    assert exchange.status_code == 200
    token = exchange.json()["session_token"]

    second_exchange = client.post("/api/agent/auth/cli/exchange", json={"code": code})
    assert second_exchange.status_code == 400

    fresh_client = TestClient(app)
    bearer_me = fresh_client.get("/api/agent/me", headers={"Authorization": f"Bearer {token}"})
    assert bearer_me.status_code == 200
    assert bearer_me.json()["auth_source"] == "cli"

    internal_me = fresh_client.get("/api/agent/me", headers={"X-Internal-Token": "internal-secret"})
    assert internal_me.status_code == 200
    assert internal_me.json()["auth_source"] == "internal-token"

    logout = fresh_client.post("/api/agent/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200
    revoked = fresh_client.get("/api/agent/me", headers={"Authorization": f"Bearer {token}"})
    assert revoked.status_code == 401


def test_needs_attention_queue_uses_derived_manual_reply_status(monkeypatch, tmp_path) -> None:
    """The needs-attention queue returns leads whose latest inbound needs a manual answer."""
    configure_agent_db(monkeypatch, tmp_path)
    lead = move_to_needs_reply(create_agent_lead())

    client = TestClient(app)
    queue = client.get("/api/agent/queues/needs-attention", params={"limit": 20})
    assert queue.status_code == 200
    payload = queue.json()
    assert payload["queue"] == "needs-attention"
    assert payload["count"] == 1
    assert payload["conversations"][0]["lead"]["id"] == lead.id
    assert payload["conversations"][0]["lead"]["attention_state"] == "needs_reply"

    conversations = client.get(
        "/api/agent/conversations",
        params={"attention_state": "needs_reply", "limit": 20},
    )
    assert conversations.status_code == 200
    assert conversations.json()["conversations"][0]["lead"]["manual_reply_status"] == "needs_reply"


def test_conversation_detail_includes_lead_messages_and_workstation_id(monkeypatch, tmp_path) -> None:
    """Conversation detail exposes lead, funnel config, messages, and optional Workstation linkage."""
    configure_agent_db(monkeypatch, tmp_path)
    lead = move_to_needs_reply(create_agent_lead())

    client = TestClient(app)
    response = client.get(f"/api/agent/conversations/{lead.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lead"]["id"] == lead.id
    assert payload["lead"]["funnel_id"] == "contadores"
    assert payload["config"]
    assert payload["messages"][0]["lead_id"] == lead.id
    assert "workstation_client_id" in payload


def test_send_message_uses_existing_guards_dry_run_and_idempotency(monkeypatch, tmp_path) -> None:
    """Agent sends go through audited tools, dry-run stays read-only, and idempotency prevents duplicates."""
    configure_agent_db(monkeypatch, tmp_path)
    lead = move_to_needs_reply(create_agent_lead())
    client = TestClient(app)

    dry_run = client.post(
        f"/api/agent/conversations/{lead.id}/messages",
        json={"text": "te respondo ahora", "dry_run": True, "idempotency_key": "dry-run-key"},
    )
    assert dry_run.status_code == 200
    assert dry_run.json()["dry_run"] is True
    assert len([item for item in ContadoresMessage.list_by_lead(lead.id) if item.from_me]) == 0

    first = client.post(
        f"/api/agent/conversations/{lead.id}/messages",
        json={"text": "te respondo ahora", "idempotency_key": "send-key-1"},
    )
    assert first.status_code == 200
    assert first.json()["ok"] is True
    outbound = [item for item in ContadoresMessage.list_by_lead(lead.id) if item.from_me]
    assert len(outbound) == 1
    assert outbound[0].sequence_step == "agent_api_manual"

    second = client.post(
        f"/api/agent/conversations/{lead.id}/messages",
        json={"text": "te respondo ahora", "idempotency_key": "send-key-1"},
    )
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert len([item for item in ContadoresMessage.list_by_lead(lead.id) if item.from_me]) == 1
    assert AgentToolCall.list_recent(limit=10)[0].tool_name == "send_whatsapp_text"


def test_closed_send_and_unknown_tool_are_rejected(monkeypatch, tmp_path) -> None:
    """Closed leads cannot receive CRM sends, and unknown tool names are not executable."""
    configure_agent_db(monkeypatch, tmp_path)
    lead = move_to_needs_reply(create_agent_lead())
    ContadoresLead.update_flow_state(lead.id, stage=ContadoresLeadStage.CLOSED)

    client = TestClient(app)
    send = client.post(
        f"/api/agent/conversations/{lead.id}/messages",
        json={"text": "no deberia salir", "idempotency_key": "closed-send"},
    )
    assert send.status_code == 400
    assert "closed" in str(send.json()["detail"]).lower()

    unknown_tool = client.post(
        "/api/agent/runs/test-run/tools/unknown_tool",
        json={"arguments": {}},
    )
    assert unknown_tool.status_code == 404


def test_agent_meta_readiness_and_inventory_sync(monkeypatch, tmp_path) -> None:
    """Agent API should expose Meta readiness and read-only inventory sync directly."""
    configure_agent_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "secret-token")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_env")
    monkeypatch.setenv("META_BUSINESS_ID", "business_env")
    monkeypatch.setenv("META_PAGE_ID", "page_env")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "false")
    PlatformMetaInventorySnapshot.add(
        status="partial",
        source="test",
        actor="tester",
        ad_account_id="act_env",
        business_id="business_env",
        api_version="v25.0",
        inventory={"campaigns": [{"id": "campaign_1"}], "pixels": []},
        errors=["page_env/leadgen_forms: 403"],
    )

    class FakeResult:
        status = "ready"

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            assert mode == "json"
            return {
                "status": "ready",
                "ad_account_id": "act_env",
                "business_id": "business_env",
                "inventory": {"campaigns": [{"id": "campaign_2"}]},
                "errors": [],
            }

    def fake_sync_meta_inventory(**kwargs: object) -> tuple[PlatformMetaInventorySnapshot, FakeResult]:
        assert kwargs["ad_account_id"] == ""
        assert kwargs["business_id"] == ""
        assert kwargs["page_ids"] == []
        assert kwargs["limit"] == 10
        assert kwargs["source"] == "agent_api"
        snapshot = PlatformMetaInventorySnapshot.add(
            status="ready",
            source="agent_api",
            actor="agent",
            ad_account_id="act_env",
            business_id="business_env",
            api_version="v25.0",
            inventory={"campaigns": [{"id": "campaign_2"}]},
            errors=[],
        )
        return snapshot, FakeResult()

    monkeypatch.setattr(agent_endpoints, "sync_meta_inventory", fake_sync_meta_inventory)
    client = TestClient(app)

    readiness = client.get("/api/agent/meta/readiness")
    assert readiness.status_code == 200
    readiness_payload = readiness.json()
    assert readiness_payload["configured"]["credentials_present"] is True
    assert readiness_payload["configured"]["page_ids"] == ["page_env"]
    assert readiness_payload["required_permissions"]["native_lead_forms"] == ["leads_retrieval", "pages_manage_ads"]
    assert readiness_payload["latest_snapshot"]["inventory_counts"]["campaigns"] == 1

    sync = client.post("/api/agent/meta/inventory/sync", json={"limit": 10})
    assert sync.status_code == 200
    payload = sync.json()
    assert payload["saved"] is True
    assert payload["result"]["status"] == "ready"
    assert payload["snapshot"]["source"] == "agent_api"
    assert payload["snapshot"]["inventory_counts"]["campaigns"] == 1
