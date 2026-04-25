"""Tests for report schedule helpers."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.endpoints.companies import (
    build_company_summary,
    compute_report_schedule_at,
    compute_report_window_minutes_for_scheduled_send,
)


class ReportScheduleHelperTests(unittest.TestCase):
    """Validate report schedule normalization and alignment rules."""

    def test_compute_report_schedule_truncates_start_to_minute(self) -> None:
        created_at = datetime(2026, 3, 6, 9, 21, 37, 456000, tzinfo=timezone.utc)

        scheduled_at = compute_report_schedule_at(
            created_at=created_at,
            report_window_minutes=90,
        )

        self.assertEqual(
            scheduled_at,
            datetime(2026, 3, 6, 10, 51, 0, tzinfo=timezone.utc),
        )

    def test_compute_report_window_minutes_accepts_aligned_schedule(self) -> None:
        created_at = datetime(2026, 3, 6, 9, 21, 37, tzinfo=timezone.utc)
        scheduled_send_at = datetime(2026, 3, 6, 10, 45, 0, tzinfo=timezone.utc)

        resolved_minutes = compute_report_window_minutes_for_scheduled_send(
            created_at=created_at,
            scheduled_send_at=scheduled_send_at,
        )

        self.assertEqual(resolved_minutes, 84)

    def test_compute_report_window_minutes_rejects_misaligned_schedule(self) -> None:
        created_at = datetime(2026, 3, 6, 9, 21, 37, tzinfo=timezone.utc)
        scheduled_send_at = datetime(2026, 3, 6, 10, 45, 30, tzinfo=timezone.utc)

        with self.assertRaises(HTTPException) as context:
            compute_report_window_minutes_for_scheduled_send(
                created_at=created_at,
                scheduled_send_at=scheduled_send_at,
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("whole-minute increments", str(context.exception.detail))

    @patch("backend.endpoints.companies.Task.list_pending_task_types_for_resource", return_value=[])
    @patch("backend.endpoints.companies.Message.count_contacts_with_pending_delivery", return_value=0)
    @patch("backend.endpoints.companies.Message.count_contacts_with_inbound_messages", return_value=0)
    def test_build_company_summary_serializes_naive_datetimes_as_utc(
        self,
        _mock_inbound: object,
        _mock_pending_delivery: object,
        _mock_pending_tasks: object,
    ) -> None:
        company = SimpleNamespace(
            id="company-1",
            source_url="https://example.com",
            company_name="Example Co",
            objective=None,
            industry="unknown",
            company_size="unknown",
            language=None,
            conversation_automation_enabled=False,
            ceo_delivery_enabled=False,
            report_window_hours=1,
            report_scheduled_send_at=None,
            ceo_delivery_sent_at=None,
            ceo_delivery_blocked_reason=None,
            status="active",
            report_snapshot_json=None,
            report_pdf_model_json=None,
            report_html=None,
            created_at=datetime(2026, 3, 8, 5, 16, 0),
            updated_at=datetime(2026, 3, 8, 5, 16, 30),
            count_contacts=lambda: 0,
        )

        summary = build_company_summary(company)

        self.assertEqual(summary.created_at, "2026-03-08T05:16:00Z")
        self.assertEqual(summary.updated_at, "2026-03-08T05:16:30Z")
        self.assertEqual(summary.report_window_minutes, 60)
        self.assertEqual(summary.scheduled_send_at, "2026-03-08T06:16:00Z")
        self.assertFalse(summary.has_contact_reply)
        self.assertFalse(summary.has_ceo_email)
        self.assertTrue(summary.can_rescan)

    @patch("backend.endpoints.companies.Task.list_pending_task_types_for_resource", return_value=[])
    @patch("backend.endpoints.companies.Message.count_contacts_with_pending_delivery", return_value=0)
    @patch("backend.endpoints.companies.Message.count_contacts_with_inbound_messages", return_value=0)
    def test_build_company_summary_hides_legacy_hour_alias_for_sub_hour_windows(
        self,
        _mock_inbound: object,
        _mock_pending_delivery: object,
        _mock_pending_tasks: object,
    ) -> None:
        company = SimpleNamespace(
            id="company-1",
            source_url="https://example.com",
            company_name="Example Co",
            objective=None,
            tags=["vip", "argentina"],
            industry="unknown",
            company_size="unknown",
            language=None,
            conversation_automation_enabled=False,
            ceo_delivery_enabled=False,
            report_window_hours=1,
            report_scheduled_send_at=datetime(2026, 3, 8, 5, 21, 0, tzinfo=timezone.utc),
            ceo_delivery_sent_at=None,
            ceo_delivery_blocked_reason=None,
            status="active",
            report_snapshot_json=None,
            report_pdf_model_json=None,
            report_html=None,
            created_at=datetime(2026, 3, 8, 5, 16, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 8, 5, 16, 30, tzinfo=timezone.utc),
            count_contacts=lambda: 0,
        )

        summary = build_company_summary(company)

        self.assertIsNone(summary.report_window_hours)
        self.assertEqual(summary.report_window_minutes, 5)
        self.assertEqual(summary.scheduled_send_at, "2026-03-08T05:21:00Z")
        self.assertEqual(summary.tags, ["vip", "argentina"])
        self.assertFalse(summary.has_contact_reply)
        self.assertFalse(summary.has_ceo_email)

    @patch("backend.endpoints.companies.Task.list_pending_task_types_for_resource", return_value=["run_company_scan_task"])
    @patch("backend.endpoints.companies.Message.count_contacts_with_pending_delivery", return_value=0)
    @patch("backend.endpoints.companies.Message.count_contacts_with_inbound_messages", return_value=0)
    def test_build_company_summary_marks_processing_when_task_pending(
        self,
        _mock_inbound: object,
        _mock_pending_delivery: object,
        _mock_pending_tasks: object,
    ) -> None:
        company = SimpleNamespace(
            id="company-2",
            source_url="https://example.com",
            company_name="Example Co",
            objective=None,
            industry="unknown",
            company_size="unknown",
            language=None,
            conversation_automation_enabled=False,
            ceo_delivery_enabled=False,
            report_window_hours=24,
            report_scheduled_send_at=None,
            ceo_delivery_sent_at=None,
            ceo_delivery_blocked_reason=None,
            status="active",
            report_snapshot_json=None,
            report_pdf_model_json=None,
            report_html=None,
            created_at=datetime(2026, 3, 8, 5, 16, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 8, 5, 16, 30, tzinfo=timezone.utc),
            count_contacts=lambda: 0,
        )

        summary = build_company_summary(company)

        self.assertTrue(summary.processing)
        self.assertEqual(summary.status, "initializing")
        self.assertFalse(summary.can_rescan)

    @patch("backend.endpoints.companies.Task.list_pending_task_types_for_resource", return_value=[])
    @patch("backend.endpoints.companies.Message.count_contacts_with_pending_delivery", return_value=0)
    @patch("backend.endpoints.companies.Message.count_contacts_with_inbound_messages", return_value=2)
    def test_build_company_summary_marks_contact_reply_presence(
        self,
        _mock_inbound: object,
        _mock_pending_delivery: object,
        _mock_pending_tasks: object,
    ) -> None:
        company = SimpleNamespace(
            id="company-3",
            source_url="https://example.com",
            company_name="Example Co",
            objective=None,
            industry="unknown",
            company_size="unknown",
            language=None,
            conversation_automation_enabled=False,
            ceo_delivery_enabled=False,
            report_window_hours=24,
            report_scheduled_send_at=None,
            ceo_delivery_sent_at=None,
            ceo_delivery_blocked_reason=None,
            status="active",
            report_snapshot_json=None,
            report_pdf_model_json=None,
            report_html=None,
            created_at=datetime(2026, 3, 8, 5, 16, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 8, 5, 16, 30, tzinfo=timezone.utc),
            count_contacts=lambda: 2,
        )

        summary = build_company_summary(company)

        self.assertTrue(summary.has_contact_reply)

    @patch("backend.endpoints.companies.Task.list_pending_task_types_for_resource", return_value=[])
    @patch("backend.endpoints.companies.Message.count_contacts_with_pending_delivery", return_value=0)
    @patch("backend.endpoints.companies.Message.count_contacts_with_inbound_messages", return_value=0)
    def test_build_company_summary_marks_ceo_email_presence(
        self,
        _mock_inbound: object,
        _mock_pending_delivery: object,
        _mock_pending_tasks: object,
    ) -> None:
        company = SimpleNamespace(
            id="company-4",
            source_url="https://example.com",
            company_name="Example Co",
            objective=None,
            industry="unknown",
            company_size="unknown",
            language=None,
            conversation_automation_enabled=False,
            ceo_delivery_enabled=False,
            ceo_email=" CEO@example.com ",
            report_window_hours=24,
            report_scheduled_send_at=None,
            ceo_delivery_sent_at=None,
            ceo_delivery_blocked_reason=None,
            status="active",
            report_snapshot_json=None,
            report_pdf_model_json=None,
            report_html=None,
            created_at=datetime(2026, 3, 8, 5, 16, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 3, 8, 5, 16, 30, tzinfo=timezone.utc),
            count_contacts=lambda: 0,
        )

        summary = build_company_summary(company)

        self.assertTrue(summary.has_ceo_email)


if __name__ == "__main__":
    unittest.main()
