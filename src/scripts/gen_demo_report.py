"""Generate demo structured report JSON for local validation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.ai import CompanyReport
from backend.database import (
    CompanyLLMInfo,
    ContactConversationStats,
    ContactLLMInfo,
    ConversationMessage,
)


def build_demo_report(now: datetime) -> CompanyReport:
    """Build a deterministic sample report using the Stage 3 structured contract."""
    contact_1_conversation = [
        ConversationMessage(
            from_me=True,
            text="Hi Marta, we are evaluating workflow automation options and ROI.",
            timestamp=now,
        ),
        ConversationMessage(
            from_me=False,
            text="Great, we usually see around 30% less manual workload.",
            timestamp=now + timedelta(minutes=4),
        ),
    ]
    contact_2_conversation = [
        ConversationMessage(
            from_me=True,
            text="Do you have an example for a budget-constrained team?",
            timestamp=now + timedelta(minutes=7),
        )
    ]

    contact_1 = ContactLLMInfo(
        contact_type="email",
        contact_value="marta@konectalabs.com",
        notes="Marta",
        additional_context=None,
        stats=ContactConversationStats(
            first_response_seconds=240.0,
            avg_response_seconds=240.0,
        ),
        conversation=contact_1_conversation,
    )
    contact_2 = ContactLLMInfo(
        contact_type="whatsapp",
        contact_value="+54 11 5555 2211",
        notes=None,
        additional_context=None,
        stats=ContactConversationStats(
            first_response_seconds=None,
            avg_response_seconds=None,
        ),
        conversation=contact_2_conversation,
    )

    company_info = CompanyLLMInfo(
        company_name="Konecta Labs",
        source_url="https://konectalabs.com",
        company_info="B2B software company focused on operational workflow automation.",
        objective="Evaluate sales quality and conversion risk under budget pressure.",
        contacts=[contact_1, contact_2],
    )

    return CompanyReport(
        company_info=company_info,
        language="en",
        experts_knowledge=(
            "Experts in consultative sales recommend deeper discovery before moving to a CTA, "
            "explicit objection handling with evidence, and strict next-step clarity in each interaction."
        ),
        report_text=(
            "Konecta Labs shows one conversation with promising value framing but limited discovery depth, "
            "and one thread that requires follow-up discipline. Priority actions: standardize early "
            "discovery questions, tighten objection handling with concrete evidence, and enforce one explicit next "
            "step in every outbound message."
        ),
    )


def main() -> None:
    """Write demo report to disk for manual review."""
    report = build_demo_report(datetime.now(timezone.utc))

    output_dir = Path("data/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "demo_audit_payload.json"
    output_path.write_text(report.model_dump_json(indent=2, by_alias=True), encoding="utf-8")
    print(f"Generated: {output_path}")


if __name__ == "__main__":
    main()
