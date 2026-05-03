"""Tests for the bot worker orchestration loop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import main as bot_main


def test_worker_iteration_dispatches_pending_messages_without_campaign_funnels(monkeypatch) -> None:
    """Queued WhatsApp messages should not wait on an active campaign funnel."""
    dispatched_limits: list[int] = []
    dispatched_batches: list[list[str]] = []

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

    monkeypatch.setattr(bot_main, "fetch_funnels", fail_if_funnels_are_refetched)
    monkeypatch.setattr(bot_main, "fetch_pending_contadores_outbound", fake_fetch_pending)
    monkeypatch.setattr(bot_main, "dispatch_pending_contadores_messages", fake_dispatch_pending)

    asyncio.run(
        bot_main.run_worker_iteration(
            backend_client=SimpleNamespace(),
            email_provider=SimpleNamespace(),
            whatsapp_provider=SimpleNamespace(),
            funnels=[],
        )
    )

    assert dispatched_limits == [200]
    assert dispatched_batches == [["pending-message"]]
