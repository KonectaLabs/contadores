"""Tests for the bot worker orchestration loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

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
