"""Focused tests for Workstation endpoint helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.endpoints.workstation import build_conversation_text


def test_build_conversation_text_preserves_media_context_without_text() -> None:
    """Media-only messages should not become blank lines in copy-all exports."""
    lead = SimpleNamespace(
        full_name="Ana Perez",
        phone="+5491111111111",
        normalized_phone="5491111111111",
        email="ana@example.com",
        funnel_id="contadores",
    )
    message = SimpleNamespace(
        from_me=False,
        created_at=datetime(2026, 5, 3, 15, 30, tzinfo=UTC),
        media_type="image",
        media_caption="Balance firmado",
        media_filename="balance.png",
        media_path="data/workstation/clients/ana/media/balance.png",
        text="",
    )

    transcript = build_conversation_text(lead, [message])

    assert "Cliente [image]: Balance firmado | balance.png | data/workstation/clients/ana/media/balance.png" in transcript


def test_build_conversation_text_marks_empty_media_messages() -> None:
    """A media message with no metadata should still be visible to operators."""
    lead = SimpleNamespace(
        full_name=None,
        phone="+5491111111111",
        normalized_phone="5491111111111",
        email=None,
        funnel_id="contadores",
    )
    message = SimpleNamespace(
        from_me=False,
        created_at=datetime(2026, 5, 3, 15, 30, tzinfo=UTC),
        media_type="audio",
        media_caption=None,
        media_filename=None,
        media_path=None,
        text=None,
    )

    transcript = build_conversation_text(lead, [message])

    assert "Cliente [audio]: (media sin texto)" in transcript
