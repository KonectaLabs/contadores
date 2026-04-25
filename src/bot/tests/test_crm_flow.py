"""Tests for CRM-specific bot flows."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import main as bot_main
import utils
from providers import DeliveryReceipt, EmailInboundEvent
from utils import (
    PendingCrmOutboundMessage,
    dispatch_pending_crm_messages,
    process_email_inbound_events,
    run_audit_delivery_iteration,
    should_trigger_full_audit,
)


def test_dispatch_pending_crm_messages_sends_immediately_without_random_spacing(monkeypatch) -> None:
    sent_calls: list[dict[str, str | None]] = []
    mark_sent_calls: list[int] = []

    async def fake_ensure_crm_inbox():
        return SimpleNamespace(inbox_id="crm-inbox-1", inbox_address="crm@example.com")

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        return DeliveryReceipt(
            external_id="agentmail-sent-1",
            thread_id="agentmail-thread-1",
            rfc_message_id="<reply-1@example.com>",
            from_email="bot@example.com",
        )

    async def fake_mark_backend_crm_message_sent(client, *, message_id: int, receipt: DeliveryReceipt):
        mark_sent_calls.append(message_id)
        return SimpleNamespace(id=message_id, thread_id="thread-1", status="sent")

    monkeypatch.setattr(utils, "mark_backend_crm_message_sent", fake_mark_backend_crm_message_sent)

    pending = [
        PendingCrmOutboundMessage(
            message_id=17,
            thread_id="thread-1",
            company_id="company-1",
            company_name="Example Co",
            participant_email="ceo@example.com",
            subject="Quick analysis of your website contacts",
            body="Following up on the audit.",
            gmail_thread_id="gmail-thread-1",
            latest_sent_rfc_message_id="<root@example.com>",
        )
    ]

    results = asyncio.run(
        dispatch_pending_crm_messages(
            SimpleNamespace(),
            pending=pending,
            email_provider=SimpleNamespace(
                configured=True,
                ensure_crm_inbox=fake_ensure_crm_inbox,
                send_message=fake_send_message,
            ),
        )
    )

    assert [item.status for item in results] == ["sent"]
    assert len(sent_calls) == 1
    assert sent_calls[0]["inbox_id"] == "crm-inbox-1"
    assert sent_calls[0]["inbox_address"] == "crm@example.com"
    assert sent_calls[0]["thread_id"] == "gmail-thread-1"
    assert sent_calls[0]["in_reply_to"] == "<root@example.com>"
    assert mark_sent_calls == [17]


def test_process_email_inbound_events_prioritizes_crm_thread_resolution(monkeypatch) -> None:
    resolved_calls: list[dict[str, str | None]] = []
    acknowledged: list[tuple[str, str]] = []

    async def fake_register_backend_crm_inbound(client, *, event: EmailInboundEvent):
        return SimpleNamespace(
            status="stored",
            company_id="company-1",
            thread_id="crm-thread-1",
            message_id=33,
            reason=None,
        )

    async def fake_resolve_backend_contact(*args, **kwargs):
        resolved_calls.append(kwargs)
        return SimpleNamespace(contact_id="contact-1")

    async def fake_acknowledge_message(*, inbox_id: str, message_id: str) -> None:
        acknowledged.append((inbox_id, message_id))

    monkeypatch.setattr(utils, "register_backend_crm_inbound", fake_register_backend_crm_inbound)
    monkeypatch.setattr(utils, "resolve_backend_contact", fake_resolve_backend_contact)

    outcomes = asyncio.run(
        process_email_inbound_events(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                is_crm_inbox=lambda inbox_id: inbox_id == "crm-inbox-1",
                acknowledge_message=fake_acknowledge_message,
            ),
            events=[
                EmailInboundEvent(
                    inbox_id="crm-inbox-1",
                    message_id="agentmail-message-2",
                    from_email="ceo@example.com",
                    plain_text="Thanks for the report.",
                    thread_id="gmail-thread-1",
                    in_reply_to="<root@example.com>",
                    references="<root@example.com>",
                    subject="Re: Quick analysis of your website contacts",
                )
            ],
        )
    )

    assert outcomes == [
        {
            "message_id": "agentmail-message-2",
            "inbox_id": "crm-inbox-1",
            "status": "stored",
            "company_id": "company-1",
            "thread_id": "crm-thread-1",
            "backend_message_id": 33,
            "reason": None,
        }
    ]
    assert resolved_calls == []
    assert acknowledged == [("crm-inbox-1", "agentmail-message-2")]


def test_process_email_inbound_events_falls_back_to_contact_resolution_when_crm_thread_is_missing(monkeypatch) -> None:
    registered_inbound: list[dict[str, str | None]] = []
    acknowledged: list[tuple[str, str]] = []

    async def fake_register_backend_crm_inbound(client, *, event: EmailInboundEvent):
        del client, event
        return SimpleNamespace(
            status="ignored",
            company_id=None,
            thread_id=None,
            message_id=None,
            reason="thread_not_found",
        )

    async def fake_resolve_backend_contact(*args, **kwargs):
        del args
        return SimpleNamespace(contact_id="contact-1", company_id="company-1")

    async def fake_register_backend_inbound(
        client,
        *,
        resolved,
        message: str,
        external_id: str | None,
        channel: str,
        inbox_id: str | None = None,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> None:
        del client, resolved
        registered_inbound.append(
            {
                "message": message,
                "external_id": external_id,
                "channel": channel,
                "inbox_id": inbox_id,
                "thread_id": thread_id,
                "in_reply_to": in_reply_to,
                "references": references,
            }
        )

    async def fake_acknowledge_message(*, inbox_id: str, message_id: str) -> None:
        acknowledged.append((inbox_id, message_id))

    monkeypatch.setattr(utils, "register_backend_crm_inbound", fake_register_backend_crm_inbound)
    monkeypatch.setattr(utils, "resolve_backend_contact", fake_resolve_backend_contact)
    monkeypatch.setattr(utils, "register_backend_inbound", fake_register_backend_inbound)

    outcomes = asyncio.run(
        process_email_inbound_events(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                acknowledge_message=fake_acknowledge_message,
            ),
            events=[
                EmailInboundEvent(
                    inbox_id="maximorodriguez@agentmail.to",
                    message_id="agentmail-message-3",
                    from_email="buyer@example.com",
                    plain_text="Can you send pricing?",
                    thread_id="non-crm-thread",
                    in_reply_to="<root@example.com>",
                    references="<root@example.com>",
                    subject="Re: Pricing",
                )
            ],
        )
    )

    assert outcomes == [
        {
            "message_id": "agentmail-message-3",
            "inbox_id": "maximorodriguez@agentmail.to",
            "status": "processed",
            "contact_id": "contact-1",
        }
    ]
    assert registered_inbound == [
        {
            "message": "Can you send pricing?",
            "external_id": "agentmail-message-3",
            "channel": "email",
            "inbox_id": "maximorodriguez@agentmail.to",
            "thread_id": "non-crm-thread",
            "in_reply_to": "<root@example.com>",
            "references": "<root@example.com>",
        }
    ]
    assert acknowledged == [("maximorodriguez@agentmail.to", "agentmail-message-3")]


def test_parse_content_disposition_filename_prefers_rfc5987_value() -> None:
    header = 'attachment; filename="audit-fallback.pdf"; filename*=UTF-8\'\'audit-acme%20industrial.pdf'

    filename = utils.parse_content_disposition_filename(header, "audit-company-1.pdf")

    assert filename == "audit-acme industrial.pdf"


def test_run_audit_delivery_iteration_seeds_crm_after_first_audit_email(monkeypatch) -> None:
    seeded_calls: list[dict[str, str]] = []
    sent_calls: list[dict[str, object]] = []

    async def fake_ensure_crm_inbox():
        return SimpleNamespace(inbox_id="crm-inbox-1", inbox_address="crm@example.com")

    async def fake_fetch_audit_delivery_poll_state(client):
        return [
            SimpleNamespace(
                company_id="company-1",
                created_at="2026-03-07T09:00:00Z",
                report_window_hours=24,
                report_window_minutes=24 * 60,
                scheduled_send_at="2026-03-08T09:00:00Z",
                conversation_automation_enabled=True,
                ceo_delivery_enabled=True,
                has_report_pdf_model=True,
                ceo_delivery_sent_at=None,
                ceo_delivery_blocked_reason=None,
                pending_full_audit_task=False,
                eligible_for_full_audit=False,
            )
        ]

    async def fake_fetch_company_audit_ceo_email(client, *, company_id: str):
        return SimpleNamespace(company_id=company_id, ceo_email="ceo@example.com")

    async def fake_fetch_company_audit_email_content(client, *, company_id: str):
        return SimpleNamespace(
            company_id=company_id,
            subject="Quick analysis of your website contacts",
            body="Attached is your audit report.",
        )

    async def fake_fetch_company_audit_pdf(client, *, company_id: str):
        return utils.AuditDeliveryPdfAttachment(
            filename="audit-acme-industrial.pdf",
            data=b"%PDF-1.4",
        )

    async def fake_register_backend_report_delivery_sent(
        client,
        *,
        company_id: str,
        participant_email: str,
        subject: str,
        body: str,
        receipt: DeliveryReceipt,
    ):
        seeded_calls.append(
            {
                "company_id": company_id,
                "participant_email": participant_email,
                "subject": subject,
                "body": body,
                "thread_id": receipt.thread_id or "",
                "message_id": receipt.external_id,
            }
        )
        return SimpleNamespace(thread_id="crm-thread-1", company_id=company_id, message_id=91)

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        sent_calls.append(kwargs)
        return DeliveryReceipt(
            external_id="agentmail-message-1",
            thread_id="agentmail-thread-1",
            rfc_message_id="<agentmail-message-1@example.com>",
            from_email="bot@example.com",
        )

    monkeypatch.setattr(utils, "fetch_audit_delivery_poll_state", fake_fetch_audit_delivery_poll_state)
    monkeypatch.setattr(utils, "fetch_company_audit_ceo_email", fake_fetch_company_audit_ceo_email)
    monkeypatch.setattr(utils, "fetch_company_audit_email_content", fake_fetch_company_audit_email_content)
    monkeypatch.setattr(utils, "fetch_company_audit_pdf", fake_fetch_company_audit_pdf)
    monkeypatch.setattr(utils, "register_backend_report_delivery_sent", fake_register_backend_report_delivery_sent)

    summary = asyncio.run(
        run_audit_delivery_iteration(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_crm_inbox=fake_ensure_crm_inbox,
                send_message=fake_send_message,
            ),
        )
    )

    assert summary == {
        "state_rows": 1,
        "generated_requested": 0,
        "blocked": 0,
        "delivered": 1,
    }
    assert seeded_calls == [
        {
            "company_id": "company-1",
            "participant_email": "ceo@example.com",
            "subject": "Quick analysis of your website contacts",
            "body": "Attached is your audit report.",
            "thread_id": "agentmail-thread-1",
            "message_id": "agentmail-message-1",
        }
    ]
    assert sent_calls[0]["inbox_id"] == "crm-inbox-1"
    assert sent_calls[0]["inbox_address"] == "crm@example.com"
    assert sent_calls[0]["attachments"][0].filename == "audit-acme-industrial.pdf"


def test_run_audit_delivery_iteration_never_uses_transient_email_spacing(monkeypatch) -> None:
    async def fake_ensure_crm_inbox():
        return SimpleNamespace(inbox_id="crm-inbox-1", inbox_address="crm@example.com")

    async def fake_fetch_audit_delivery_poll_state(client):
        return [
            SimpleNamespace(
                company_id="company-1",
                created_at="2026-03-07T09:00:00Z",
                report_window_hours=24,
                report_window_minutes=24 * 60,
                scheduled_send_at="2026-03-08T09:00:00Z",
                conversation_automation_enabled=True,
                ceo_delivery_enabled=True,
                has_report_pdf_model=True,
                ceo_delivery_sent_at=None,
                ceo_delivery_blocked_reason=None,
                pending_full_audit_task=False,
                eligible_for_full_audit=False,
            )
        ]

    async def fake_fetch_company_audit_ceo_email(client, *, company_id: str):
        return SimpleNamespace(company_id=company_id, ceo_email="ceo@example.com")

    async def fake_fetch_company_audit_email_content(client, *, company_id: str):
        return SimpleNamespace(
            company_id=company_id,
            subject="Quick analysis of your website contacts",
            body="Attached is your audit report.",
        )

    async def fake_fetch_company_audit_pdf(client, *, company_id: str):
        return utils.AuditDeliveryPdfAttachment(
            filename="audit-example-co.pdf",
            data=b"%PDF-1.4",
        )

    async def fake_register_backend_report_delivery_sent(*args, **kwargs):
        return SimpleNamespace(thread_id="crm-thread-1", company_id="company-1", message_id=91)

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("audit delivery must not use transient email delay scheduling")

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        return DeliveryReceipt(
            external_id="agentmail-message-1",
            thread_id="agentmail-thread-1",
            rfc_message_id="<agentmail-message-1@example.com>",
            from_email="bot@example.com",
        )

    monkeypatch.setattr(utils, "fetch_audit_delivery_poll_state", fake_fetch_audit_delivery_poll_state)
    monkeypatch.setattr(utils, "fetch_company_audit_ceo_email", fake_fetch_company_audit_ceo_email)
    monkeypatch.setattr(utils, "fetch_company_audit_email_content", fake_fetch_company_audit_email_content)
    monkeypatch.setattr(utils, "fetch_company_audit_pdf", fake_fetch_company_audit_pdf)
    monkeypatch.setattr(utils, "register_backend_report_delivery_sent", fake_register_backend_report_delivery_sent)
    monkeypatch.setattr(utils, "get_email_dispatch_wait_seconds", fail_if_called)
    monkeypatch.setattr(utils, "clear_email_dispatch_delay_key", fail_if_called)
    monkeypatch.setattr(utils, "prune_email_dispatch_delay_keys", fail_if_called)

    summary = asyncio.run(
        run_audit_delivery_iteration(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_crm_inbox=fake_ensure_crm_inbox,
                send_message=fake_send_message,
            ),
        )
    )

    assert summary == {
        "state_rows": 1,
        "generated_requested": 0,
        "blocked": 0,
        "delivered": 1,
    }


def test_should_trigger_full_audit_depends_on_persisted_window_not_runtime_delay() -> None:
    row = SimpleNamespace(
        company_id="company-1",
        created_at="2026-03-07T09:00:00Z",
        report_window_hours=24,
        report_window_minutes=90,
        scheduled_send_at="2026-03-07T10:30:00Z",
        conversation_automation_enabled=True,
        ceo_delivery_enabled=True,
        has_report_pdf_model=False,
        ceo_delivery_sent_at=None,
        ceo_delivery_blocked_reason=None,
        pending_full_audit_task=False,
        eligible_for_full_audit=False,
    )

    assert should_trigger_full_audit(
        row,
        now=utils.parse_backend_timestamp("2026-03-07T10:30:01Z"),
    )


def test_run_audit_delivery_iteration_skips_already_sent_rows_without_delay_cleanup(monkeypatch) -> None:
    async def fake_fetch_audit_delivery_poll_state(client):
        return [
            SimpleNamespace(
                company_id="company-1",
                created_at="2026-03-07T09:00:00Z",
                report_window_hours=24,
                report_window_minutes=24 * 60,
                scheduled_send_at="2026-03-08T09:00:00Z",
                conversation_automation_enabled=True,
                ceo_delivery_enabled=True,
                has_report_pdf_model=True,
                ceo_delivery_sent_at="2026-03-08T11:00:00Z",
                ceo_delivery_blocked_reason=None,
                pending_full_audit_task=False,
                eligible_for_full_audit=False,
            )
        ]

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("already-sent audit rows must exit before any delivery helper runs")

    monkeypatch.setattr(utils, "fetch_audit_delivery_poll_state", fake_fetch_audit_delivery_poll_state)
    monkeypatch.setattr(utils, "clear_email_dispatch_delay_key", fail_if_called)
    monkeypatch.setattr(utils, "fetch_company_audit_ceo_email", fail_if_called)

    summary = asyncio.run(
        run_audit_delivery_iteration(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_crm_inbox=fail_if_called,
                send_message=fail_if_called,
            ),
        )
    )

    assert summary == {
        "state_rows": 1,
        "generated_requested": 0,
        "blocked": 0,
        "delivered": 0,
    }


def test_run_audit_delivery_iteration_removes_rejected_ceo_email_and_continues(monkeypatch) -> None:
    removed_emails: list[str] = []
    blocked_companies: list[tuple[str, str]] = []
    delivered_companies: list[str] = []

    async def fake_ensure_crm_inbox():
        return SimpleNamespace(inbox_id="crm-inbox-1", inbox_address="crm@example.com")

    async def fake_fetch_audit_delivery_poll_state(client):
        del client
        return [
            SimpleNamespace(
                company_id="company-1",
                created_at="2026-03-07T09:00:00Z",
                report_window_hours=24,
                report_window_minutes=24 * 60,
                scheduled_send_at="2026-03-08T09:00:00Z",
                conversation_automation_enabled=True,
                ceo_delivery_enabled=True,
                has_report_pdf_model=True,
                ceo_delivery_sent_at=None,
                ceo_delivery_blocked_reason=None,
                pending_full_audit_task=False,
                eligible_for_full_audit=False,
            ),
            SimpleNamespace(
                company_id="company-2",
                created_at="2026-03-07T09:00:00Z",
                report_window_hours=24,
                report_window_minutes=24 * 60,
                scheduled_send_at="2026-03-08T09:00:00Z",
                conversation_automation_enabled=True,
                ceo_delivery_enabled=True,
                has_report_pdf_model=True,
                ceo_delivery_sent_at=None,
                ceo_delivery_blocked_reason=None,
                pending_full_audit_task=False,
                eligible_for_full_audit=False,
            ),
        ]

    async def fake_fetch_company_audit_ceo_email(client, *, company_id: str):
        del client
        if company_id == "company-1":
            return SimpleNamespace(company_id=company_id, ceo_email="geoff@hubindustrial.com")
        return SimpleNamespace(company_id=company_id, ceo_email="ceo@example.com")

    async def fake_fetch_company_audit_email_content(client, *, company_id: str):
        del client
        return SimpleNamespace(
            company_id=company_id,
            subject="Quick analysis of your website contacts",
            body=f"Attached is your audit report for {company_id}.",
        )

    async def fake_fetch_company_audit_pdf(client, *, company_id: str):
        del client
        return utils.AuditDeliveryPdfAttachment(
            filename=f"audit-{company_id}.pdf",
            data=b"%PDF-1.4",
        )

    async def fake_clear_company_audit_ceo_email(client, *, company_id: str):
        del client
        removed_emails.append(company_id)

    async def fake_mark_company_audit_blocked(client, *, company_id: str, reason: str):
        del client
        blocked_companies.append((company_id, reason))

    async def fake_register_backend_report_delivery_sent(
        client,
        *,
        company_id: str,
        participant_email: str,
        subject: str,
        body: str,
        receipt: DeliveryReceipt,
    ):
        del client, participant_email, subject, body, receipt
        delivered_companies.append(company_id)

    async def fake_send_message(**kwargs) -> DeliveryReceipt:
        recipient = kwargs["recipient"]
        if recipient == "geoff@hubindustrial.com":
            class MessageRejectedError(Exception):
                """Fake provider rejection with the real class name used in production."""

            raise MessageRejectedError(
                "Message rejected: Recipient(s) blocked: geoff@hubindustrial.com (bounced)"
            )
        return DeliveryReceipt(
            external_id="agentmail-message-2",
            thread_id="agentmail-thread-2",
            rfc_message_id="<agentmail-message-2@example.com>",
            from_email="bot@example.com",
        )

    monkeypatch.setattr(utils, "fetch_audit_delivery_poll_state", fake_fetch_audit_delivery_poll_state)
    monkeypatch.setattr(utils, "fetch_company_audit_ceo_email", fake_fetch_company_audit_ceo_email)
    monkeypatch.setattr(utils, "fetch_company_audit_email_content", fake_fetch_company_audit_email_content)
    monkeypatch.setattr(utils, "fetch_company_audit_pdf", fake_fetch_company_audit_pdf)
    monkeypatch.setattr(utils, "clear_company_audit_ceo_email", fake_clear_company_audit_ceo_email)
    monkeypatch.setattr(utils, "mark_company_audit_blocked", fake_mark_company_audit_blocked)
    monkeypatch.setattr(utils, "register_backend_report_delivery_sent", fake_register_backend_report_delivery_sent)

    summary = asyncio.run(
        run_audit_delivery_iteration(
            SimpleNamespace(),
            email_provider=SimpleNamespace(
                configured=True,
                ensure_crm_inbox=fake_ensure_crm_inbox,
                send_message=fake_send_message,
            ),
        )
    )

    assert summary == {
        "state_rows": 2,
        "generated_requested": 0,
        "blocked": 1,
        "delivered": 1,
    }
    assert removed_emails == ["company-1"]
    assert blocked_companies == [("company-1", "missing_ceo_email")]
    assert delivered_companies == ["company-2"]


def test_run_worker_loop_keeps_sheet_sync_when_audit_iteration_fails(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_run_worker_iteration(**kwargs):
        del kwargs
        calls.append("worker")

    async def fake_run_audit_delivery_iteration(*args, **kwargs):
        del args, kwargs
        calls.append("audit")
        raise RuntimeError("audit delivery exploded")

    async def fake_fetch_contadores_config(client):
        del client
        return SimpleNamespace(sheet_poll_seconds=300)

    async def fake_run_contadores_sheet_sync_iteration(client):
        del client
        calls.append("sheet")
        return {"status": "ok"}

    async def fake_sleep(seconds: float):
        del seconds
        raise asyncio.CancelledError

    monkeypatch.setattr(bot_main, "run_worker_iteration", fake_run_worker_iteration)
    monkeypatch.setattr(bot_main, "run_audit_delivery_iteration", fake_run_audit_delivery_iteration)
    monkeypatch.setattr(bot_main, "fetch_contadores_config", fake_fetch_contadores_config)
    monkeypatch.setattr(bot_main, "run_contadores_sheet_sync_iteration", fake_run_contadores_sheet_sync_iteration)
    monkeypatch.setattr(bot_main, "note_backend_recovered", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot_main.asyncio, "get_running_loop", lambda: SimpleNamespace(time=lambda: 1000.0))
    monkeypatch.setattr(bot_main.asyncio, "sleep", fake_sleep)

    asyncio.run(
        bot_main.run_worker_loop(
            backend_client=SimpleNamespace(),
            email_provider=SimpleNamespace(configured=False),
            legacy_gmail_provider=SimpleNamespace(configured=False),
            whatsapp_provider=SimpleNamespace(configured=False),
        )
    )

    assert calls == ["worker", "audit", "sheet"]
