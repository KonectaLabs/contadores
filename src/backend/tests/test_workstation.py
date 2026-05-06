"""Focused tests for Workstation endpoint helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from backend.endpoints.workstation import (
    build_conversation_text,
    copy_previous_landing_page_version,
    fallback_workstation_agent_decision,
    parse_workstation_agent_decision,
)


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


def test_parse_workstation_agent_decision_allows_text_reply() -> None:
    """The agent can choose a text answer instead of forcing another preview."""
    decision = parse_workstation_agent_decision(
        '{"action":"send_text","message":"Mandeme lo que quiere sumar y lo agrego.","reason":"asked how to add content"}'
    )

    assert decision.action == "send_text"
    assert "lo agrego" in decision.message


def test_fallback_workstation_agent_decision_answers_content_question() -> None:
    """A client question about content should not become a page revision."""
    decision = fallback_workstation_agent_decision("Y como hago para meterle todas las cosas que hice?")

    assert decision.action == "send_text"
    assert "Conteme" in decision.message


def test_copy_previous_landing_page_version_preserves_design_files(tmp_path) -> None:
    """Revision folders should start from the prior HTML/CSS/JS instead of a blank redesign."""
    previous = tmp_path / "v001"
    next_version = tmp_path / "v002"
    (previous / "assets").mkdir(parents=True)
    next_version.mkdir()
    (previous / "index.html").write_text("<main>Original</main>", encoding="utf-8")
    (previous / "styles.css").write_text("body { color: black; }", encoding="utf-8")
    (previous / "script.js").write_text("console.log('same project');", encoding="utf-8")
    (previous / "assets" / "logo.txt").write_text("logo", encoding="utf-8")

    copy_previous_landing_page_version(previous_version=previous, version_dir=next_version)

    assert (next_version / "index.html").read_text(encoding="utf-8") == "<main>Original</main>"
    assert (next_version / "styles.css").read_text(encoding="utf-8") == "body { color: black; }"
    assert (next_version / "script.js").read_text(encoding="utf-8") == "console.log('same project');"
    assert (next_version / "assets" / "logo.txt").read_text(encoding="utf-8") == "logo"
