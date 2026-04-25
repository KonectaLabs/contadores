"""Tests for the bot runtime logging helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import logging_utils


def test_error_only_access_filter_keeps_only_failing_access_logs() -> None:
    filter_ = logging_utils.ErrorOnlyAccessFilter()

    ok_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/health", "1.1", 200),
        exc_info=None,
    )
    error_record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/api/messages/pending-delivery", "1.1", 500),
        exc_info=None,
    )

    assert filter_.filter(ok_record) is False
    assert filter_.filter(error_record) is True


def test_log_dispatch_activity_deduplicates_waiting_messages(monkeypatch, caplog) -> None:
    logger = logging.getLogger("bot.test.waiting")
    state = logging_utils.BotLogState()
    timeline = iter([100.0, 120.0])
    monkeypatch.setattr(logging_utils, "monotonic", lambda: next(timeline))
    caplog.set_level(logging.INFO, logger=logger.name)

    waiting_results = [
        SimpleNamespace(
            status="deferred",
            channel="email",
            contact_value="test@example.com",
            error="email_delay_not_elapsed",
            wait_seconds=1455.8,
        ),
        SimpleNamespace(
            status="deferred",
            channel="whatsapp",
            contact_value="+5491111111111",
            error="whatsapp_delay_not_elapsed",
            wait_seconds=21.1,
        ),
    ]

    logging_utils.log_dispatch_activity(logger, waiting_results, state)
    logging_utils.log_dispatch_activity(logger, waiting_results, state)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    assert "waiting for send time" in messages[0]
    assert "1 email" in messages[0]
    assert "1 WhatsApp message" in messages[0]
    assert "email_delay_not_elapsed" not in messages[0]


def test_log_dispatch_activity_uses_human_language_for_success_and_failure(caplog) -> None:
    logger = logging.getLogger("bot.test.summary")
    state = logging_utils.BotLogState()
    caplog.set_level(logging.INFO, logger=logger.name)

    results = [
        SimpleNamespace(
            status="delivered",
            channel="email",
            contact_value="one@example.com",
            error=None,
        ),
        SimpleNamespace(
            status="delivered",
            channel="whatsapp",
            contact_value="+5491222222222",
            error=None,
        ),
        SimpleNamespace(
            status="failed",
            channel="email",
            contact_value="two@example.com",
            error="smtp_timeout",
            message_id=55,
        ),
    ]

    logging_utils.log_dispatch_activity(logger, results, state)

    messages = [record.getMessage() for record in caplog.records]
    assert "📧 Sent 1 email. Delivery confirmation will arrive by webhook." in messages
    assert "📲 Sent 1 WhatsApp message. Delivery confirmation will arrive later." in messages
    assert "❌ Could not send email to two@example.com: smtp timeout" in messages


def test_log_whatsapp_status_activity_uses_provider_read_state(caplog) -> None:
    logger = logging.getLogger("bot.test.whatsapp.status")
    caplog.set_level(logging.INFO, logger=logger.name)

    logging_utils.log_whatsapp_status_activity(
        logger,
        {
            "id": 44,
            "delivery_status": "delivered",
            "provider_status": "read",
        },
    )

    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["📲 message #44 status changed to read."]
