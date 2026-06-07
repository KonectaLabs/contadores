"""Tests for the bot worker orchestration loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

import main as bot_main


def test_build_sheet_sync_log_summary_omits_lead_ids() -> None:
    """Routine sheet logs should stay compact when hundreds of leads sync."""
    summary = bot_main.build_sheet_sync_log_summary(
        {
            "status": "ok",
            "imported": 1,
            "updated": 2,
            "skipped": 3,
            "lead_ids": ["lead-1", "lead-2", "lead-3"],
        }
    )

    assert summary == {
        "status": "ok",
        "imported": 1,
        "updated": 2,
        "skipped": 3,
        "lead_count": 3,
    }


def test_worker_iteration_dispatches_pending_messages_without_campaign_funnels(monkeypatch) -> None:
    """Queued WhatsApp messages should not wait on an active campaign funnel."""
    dispatched_limits: list[int] = []
    dispatched_batches: list[list[str]] = []
    client_lead_limits: list[int] = []
    client_lead_batches: list[list[str]] = []
    workstation_ticks = 0

    async def fail_if_funnels_are_refetched(client):
        del client
        raise AssertionError("run_worker_iteration should reuse the provided funnel list")

    async def fake_fetch_pending(client, *, limit: int):
        del client
        dispatched_limits.append(limit)
        return ["pending-message"]

    async def fake_dispatch_pending(client, *, pending, whatsapp_provider):
        del client
        del whatsapp_provider
        dispatched_batches.append(list(pending))
        return []

    async def fake_fetch_client_lead_pending(client, *, limit: int):
        del client
        client_lead_limits.append(limit)
        return ["pending-client-lead"]

    async def fake_dispatch_client_lead_pending(client, *, pending, whatsapp_provider):
        del client
        del whatsapp_provider
        client_lead_batches.append(list(pending))
        return []

    async def fake_workstation_tick(client):
        nonlocal workstation_ticks
        del client
        workstation_ticks += 1
        return {}

    async def fake_replay_pending(*, backend_client, inbox):
        del backend_client
        del inbox
        return {"checked": 0, "delivered": 0, "failed": 0, "pending": 0}

    monkeypatch.setattr(bot_main, "fetch_funnels", fail_if_funnels_are_refetched)
    monkeypatch.setattr(bot_main, "fetch_pending_contadores_outbound", fake_fetch_pending)
    monkeypatch.setattr(bot_main, "dispatch_pending_contadores_messages", fake_dispatch_pending)
    monkeypatch.setattr(bot_main, "fetch_pending_client_lead_notifications", fake_fetch_client_lead_pending)
    monkeypatch.setattr(bot_main, "dispatch_pending_client_lead_notifications", fake_dispatch_client_lead_pending)
    monkeypatch.setattr(bot_main, "run_workstation_automation_iteration", fake_workstation_tick)
    monkeypatch.setattr(bot_main, "replay_pending_whatsapp_inbound_events", fake_replay_pending)

    asyncio.run(
        bot_main.run_worker_iteration(
            backend_client=SimpleNamespace(),
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(),
            whatsapp_inbound_inbox=SimpleNamespace(),
            funnels=[],
        )
    )

    assert dispatched_limits == [200]
    assert dispatched_batches == [["pending-message"]]
    assert client_lead_limits == [200]
    assert client_lead_batches == [["pending-client-lead"]]
    assert workstation_ticks == 1


def test_worker_iteration_dispatches_delivery_when_one_funnel_returns_400(monkeypatch) -> None:
    """One broken funnel automation tick must not block global Delivery dispatch."""
    automation_attempts: list[str] = []
    client_lead_batches: list[list[str]] = []

    async def fake_replay_pending(*, backend_client, inbox):
        del backend_client
        del inbox
        return {"checked": 0, "delivered": 0, "failed": 0, "pending": 0}

    async def fake_run_automation(client, *, funnel_id: str):
        del client
        automation_attempts.append(funnel_id)
        if funnel_id == "abogados":
            request = httpx.Request("POST", "http://backend:8000/api/contadores/automation/tick")
            response = httpx.Response(400, request=request, text="window closed")
            raise httpx.HTTPStatusError("bad request", request=request, response=response)
        return {}

    async def fake_send_alerts(*args, **kwargs):
        del args
        del kwargs
        return []

    async def fake_workstation_tick(client):
        del client
        return {}

    async def fake_fetch_pending(client, *, limit: int):
        del client
        del limit
        return []

    async def fake_dispatch_pending(client, *, pending, whatsapp_provider):
        del client
        del pending
        del whatsapp_provider
        return []

    async def fake_fetch_client_lead_pending(client, *, limit: int):
        del client
        del limit
        return ["pending-client-lead"]

    async def fake_dispatch_client_lead_pending(client, *, pending, whatsapp_provider):
        del client
        del whatsapp_provider
        client_lead_batches.append(list(pending))
        return []

    funnels = [
        SimpleNamespace(id="contadores", label="Contadores", enabled=True, kind="campaign"),
        SimpleNamespace(id="abogados", label="Abogados", enabled=True, kind="campaign"),
    ]
    monkeypatch.setattr(bot_main, "replay_pending_whatsapp_inbound_events", fake_replay_pending)
    monkeypatch.setattr(bot_main, "run_contadores_automation_iteration", fake_run_automation)
    monkeypatch.setattr(bot_main, "send_contadores_pending_alerts", fake_send_alerts)
    monkeypatch.setattr(bot_main, "run_workstation_automation_iteration", fake_workstation_tick)
    monkeypatch.setattr(bot_main, "fetch_pending_contadores_outbound", fake_fetch_pending)
    monkeypatch.setattr(bot_main, "dispatch_pending_contadores_messages", fake_dispatch_pending)
    monkeypatch.setattr(bot_main, "fetch_pending_client_lead_notifications", fake_fetch_client_lead_pending)
    monkeypatch.setattr(bot_main, "dispatch_pending_client_lead_notifications", fake_dispatch_client_lead_pending)

    asyncio.run(
        bot_main.run_worker_iteration(
            backend_client=SimpleNamespace(),
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(),
            whatsapp_inbound_inbox=SimpleNamespace(),
            funnels=funnels,
        )
    )

    assert automation_attempts == ["contadores", "abogados"]
    assert client_lead_batches == [["pending-client-lead"]]
