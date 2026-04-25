"""Regression tests for auditor research program defaults."""

from __future__ import annotations

import asyncio

from backend.ai.auditor_company_discovery import AuditorCompanyDiscoveryProgram
from backend.ai.auditor_leadership_recipient import AuditorLeadershipRecipientProgram


def test_auditor_leadership_recipient_program_defaults_to_gpt_5_4_mini() -> None:
    program = AuditorLeadershipRecipientProgram()
    assert program.lm.model == "openai/gpt-5.4-mini"


def test_auditor_company_discovery_program_defaults_to_gpt_5_4_mini() -> None:
    program = AuditorCompanyDiscoveryProgram()
    assert program.lm.model == "openai/gpt-5.4-mini"


def test_auditor_leadership_recipient_program_uses_pro_search(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_pro_search(query: str):
        captured["query"] = query
        return object()

    def fake_extract_response_data(response):
        assert response is not None
        return {
            "output_text": "Leadership research memo",
            "citations": '[{"url":"https://example.com/about"}]',
        }

    monkeypatch.setattr(
        "backend.ai.auditor_leadership_recipient.pro_search",
        fake_pro_search,
    )
    monkeypatch.setattr(
        "backend.ai.auditor_leadership_recipient.extract_response_data",
        fake_extract_response_data,
    )

    program = AuditorLeadershipRecipientProgram()
    memo = asyncio.run(program.run_research("https://example.com"))

    assert "https://example.com" in captured["query"]
    assert "## Research memo" in memo
    assert "## Citations" in memo


def test_auditor_company_discovery_program_uses_pro_search(monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_pro_search(query: str):
        captured["query"] = query
        return object()

    def fake_extract_response_data(response):
        assert response is not None
        return {
            "output_text": "Company discovery memo",
            "search_queries": '["auditor icp candidates"]',
            "citations": '[{"url":"https://example.com/contact"}]',
        }

    monkeypatch.setattr(
        "backend.ai.auditor_company_discovery.pro_search",
        fake_pro_search,
    )
    monkeypatch.setattr(
        "backend.ai.auditor_company_discovery.extract_response_data",
        fake_extract_response_data,
    )

    program = AuditorCompanyDiscoveryProgram()
    memo = asyncio.run(
        program.run_research(
            count=2,
            exclude_company_urls=["https://known.example"],
            exclude_company_names=["Known Co"],
        )
    )

    assert "Known Co" in captured["query"]
    assert "https://known.example" in captured["query"]
    assert "## Research memo" in memo
    assert "## Search queries" in memo
    assert "## Citations" in memo
