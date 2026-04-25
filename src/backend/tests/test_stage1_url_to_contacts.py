"""Unit tests for Stage 1 URL probing and www fallback selection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import dspy
import pytest

from backend.ai.stage1_url_to_contacts import (
    CrawledWebsiteContent,
    ContactType,
    DiscoveredContact,
    UrlToContactsProgram,
    build_extraction_content,
    crawl,
)


def test_build_www_variant_preserves_path_and_query() -> None:
    program = UrlToContactsProgram()

    result = program._build_www_variant("https://za-tek.com/contact?lang=es")

    assert result == "https://www.za-tek.com/contact?lang=es"


def test_resolve_crawl_url_skips_www_when_original_probe_succeeds(monkeypatch) -> None:
    program = UrlToContactsProgram()
    calls: list[str] = []

    async def fake_probe(url: str) -> bool:
        calls.append(url)
        return url == "https://za-tek.com"

    monkeypatch.setattr(program, "probe_html_url", fake_probe)

    result = asyncio.run(program.resolve_crawl_url("https://za-tek.com"))

    assert result == "https://za-tek.com"
    assert calls == ["https://za-tek.com"]


def test_resolve_crawl_url_uses_www_when_original_probe_fails(monkeypatch) -> None:
    program = UrlToContactsProgram()
    calls: list[str] = []

    async def fake_probe(url: str) -> bool:
        calls.append(url)
        return url == "https://www.za-tek.com"

    monkeypatch.setattr(program, "probe_html_url", fake_probe)

    result = asyncio.run(program.resolve_crawl_url("https://za-tek.com"))

    assert result == "https://www.za-tek.com"
    assert calls == ["https://za-tek.com", "https://www.za-tek.com"]


def test_resolve_crawl_url_raises_when_all_variants_fail(monkeypatch) -> None:
    program = UrlToContactsProgram()

    async def fake_probe(url: str) -> bool:
        return False

    monkeypatch.setattr(program, "probe_html_url", fake_probe)

    with pytest.raises(RuntimeError, match="both"):
        asyncio.run(program.resolve_crawl_url("https://za-tek.com"))


def test_crawl_requests_markdown_and_raw_html_with_full_content(monkeypatch) -> None:
    captured_kwargs: dict[str, object] = {}

    class FakeFirecrawl:
        def crawl(self, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        markdown="# ZA-TEK",
                        raw_html="<footer>ceo@za-tek.com</footer>",
                    )
                ]
            )

    monkeypatch.setattr(
        "backend.ai.stage1_url_to_contacts.get_firecrawl_client",
        lambda: FakeFirecrawl(),
    )

    result = crawl("https://za-tek.com")

    scrape_options = captured_kwargs["scrape_options"]
    assert captured_kwargs["url"] == "https://za-tek.com"
    assert scrape_options.only_main_content is False
    assert scrape_options.formats == ["markdown", "raw_html"]
    assert result.markdown == "# ZA-TEK"
    assert result.extraction_content == "# ZA-TEK\n\n## Raw HTML\n\n<footer>ceo@za-tek.com</footer>"


def test_build_extraction_content_compacts_large_payload_and_keeps_contact_evidence(monkeypatch) -> None:
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_EXTRACTION_MAX_CHARS", 260)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_MIN_EXTRACTION_CHARS", 80)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_MARKDOWN_MAX_CHARS", 120)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_RAW_HTML_MAX_CHARS_WITH_MARKDOWN", 90)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_RAW_HTML_CONTACT_SNIPPET_BUDGET_CHARS", 80)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_CONTACT_SNIPPET_RADIUS_CHARS", 20)

    markdown = "# ZA-TEK\n\n" + ("industrial automation " * 20)
    raw_html = (
        "<html><body>"
        + ("x" * 180)
        + '<a href="mailto:ceo@za-tek.com">Email</a>'
        + ("y" * 180)
        + "</body></html>"
    )

    extraction_content = build_extraction_content(markdown, raw_html)

    assert len(extraction_content) <= 260
    assert "ceo@za-tek.com" in extraction_content
    assert "[...TRUNCATED" in extraction_content


def test_aforward_crawls_selected_url(monkeypatch) -> None:
    program = UrlToContactsProgram()
    crawled_urls: list[str] = []

    async def fake_resolve(normalized_url: str) -> str:
        assert normalized_url == "https://za-tek.com"
        return "https://www.za-tek.com"

    async def fake_crawl(normalized_url: str) -> CrawledWebsiteContent:
        crawled_urls.append(normalized_url)
        return CrawledWebsiteContent(
            markdown="# ZA-TEK",
            extraction_content="# ZA-TEK\n\n## Raw HTML\n\n<footer>ceo@za-tek.com</footer>",
        )

    async def fake_extract(website_content: str, lm=None) -> dspy.Prediction:
        assert website_content == "# ZA-TEK\n\n## Raw HTML\n\n<footer>ceo@za-tek.com</footer>"
        return dspy.Prediction(
            company_name="ZA-TEK",
            company_info="Industrial automation",
            language="es",
            company_size="small",
            industry="computer_programming_consultancy",
            ceo_email="ceo@za-tek.com",
            contacts=[
                DiscoveredContact(
                    type=ContactType.EMAIL,
                    value="ceo@za-tek.com",
                    notes="leadership contact",
                )
            ],
        )

    monkeypatch.setattr(program, "resolve_crawl_url", fake_resolve)
    monkeypatch.setattr(program, "crawl_website_content", fake_crawl)
    monkeypatch.setattr(program, "extract_contacts", fake_extract)

    result = asyncio.run(program.aforward("https://za-tek.com"))

    assert crawled_urls == ["https://www.za-tek.com"]
    assert result.company_name == "ZA-TEK"
    assert result.ceo_email == "ceo@za-tek.com"
    assert result.website_markdown == "# ZA-TEK"


def test_crawl_website_content_falls_back_to_direct_html_when_firecrawl_fails(monkeypatch) -> None:
    program = UrlToContactsProgram()
    calls: list[tuple[str, str]] = []
    sleep_delays: list[float] = []

    async def fake_firecrawl(normalized_url: str) -> CrawledWebsiteContent:
        calls.append(("firecrawl", normalized_url))
        raise RuntimeError("Firecrawl insufficient credits")

    async def fake_html_fallback(normalized_url: str) -> CrawledWebsiteContent:
        calls.append(("httpx", normalized_url))
        return CrawledWebsiteContent(
            markdown="",
            extraction_content="## Raw HTML\n\n<html><body>info@za-tek.com</body></html>",
        )

    monkeypatch.setattr(program, "crawl_with_firecrawl", fake_firecrawl)
    monkeypatch.setattr(program, "fetch_html_without_firecrawl", fake_html_fallback)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_FIRECRAWL_MAX_RETRIES", 2)

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.asyncio.sleep", fake_sleep)

    result = asyncio.run(program.crawl_website_content("https://za-tek.com"))

    assert calls == [
        ("firecrawl", "https://za-tek.com"),
        ("firecrawl", "https://za-tek.com"),
        ("firecrawl", "https://za-tek.com"),
        ("httpx", "https://za-tek.com"),
    ]
    assert sleep_delays == [10.0, 20.0]
    assert result.markdown == ""
    assert result.extraction_content == "## Raw HTML\n\n<html><body>info@za-tek.com</body></html>"


def test_aforward_accepts_raw_html_only_content(monkeypatch) -> None:
    program = UrlToContactsProgram()

    async def fake_resolve(normalized_url: str) -> str:
        assert normalized_url == "https://za-tek.com"
        return normalized_url

    async def fake_crawl(normalized_url: str) -> CrawledWebsiteContent:
        assert normalized_url == "https://za-tek.com"
        return CrawledWebsiteContent(
            markdown="",
            extraction_content="## Raw HTML\n\n<footer>ceo@za-tek.com</footer>",
        )

    async def fake_extract(website_content: str, lm=None) -> dspy.Prediction:
        assert website_content == "## Raw HTML\n\n<footer>ceo@za-tek.com</footer>"
        return dspy.Prediction(
            company_name="ZA-TEK",
            company_info="Industrial automation",
            language="es",
            company_size="small",
            industry="computer_programming_consultancy",
            ceo_email="ceo@za-tek.com",
            contacts=[
                DiscoveredContact(
                    type=ContactType.EMAIL,
                    value="ceo@za-tek.com",
                    notes="leadership contact",
                )
            ],
        )

    monkeypatch.setattr(program, "resolve_crawl_url", fake_resolve)
    monkeypatch.setattr(program, "crawl_website_content", fake_crawl)
    monkeypatch.setattr(program, "extract_contacts", fake_extract)

    result = asyncio.run(program.aforward("https://za-tek.com"))

    assert result.company_name == "ZA-TEK"
    assert result.ceo_email == "ceo@za-tek.com"
    assert result.website_markdown == ""


def test_extract_contacts_with_retries_reuses_fast_model(monkeypatch) -> None:
    program = UrlToContactsProgram()
    attempts: list[object] = []
    sleep_delays: list[float] = []
    fake_lm = SimpleNamespace(model="openrouter/x-ai/grok-4.1-fast")

    async def fake_extract(website_content: str, lm=None) -> dspy.Prediction:
        attempts.append(lm)
        if len(attempts) < 3:
            raise RuntimeError("temporary provider error")
        return dspy.Prediction(
            company_name="ZA-TEK",
            company_info="Industrial automation",
            language="es",
            company_size="small",
            industry="computer_programming_consultancy",
            ceo_email="ceo@za-tek.com",
            contacts=[],
        )

    async def fake_sleep(delay: float) -> None:
        sleep_delays.append(delay)

    monkeypatch.setattr(program, "extract_contacts", fake_extract)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_LLM_MAX_RETRIES", 5)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.asyncio.sleep", fake_sleep)

    prediction = asyncio.run(
        program.extract_contacts_with_retries(
            "website content",
            lm=fake_lm,
            source_label="https://za-tek.com",
        )
    )

    assert prediction.company_name == "ZA-TEK"
    assert attempts == [fake_lm, fake_lm, fake_lm]
    assert sleep_delays == [5.0, 10.0]


def test_extract_contacts_with_retries_shrinks_payload_after_context_limit(monkeypatch) -> None:
    program = UrlToContactsProgram()
    payloads: list[str] = []
    fake_lm = SimpleNamespace(model="openrouter/x-ai/grok-4.1-fast")

    async def fake_extract(website_content: str, lm=None) -> dspy.Prediction:
        payloads.append(website_content)
        if len(payloads) == 1:
            raise RuntimeError(
                "This endpoint's maximum context length is 2000000 tokens. "
                "However, you requested about 2904963 tokens. Please reduce the length."
            )
        return dspy.Prediction(
            company_name="ZA-TEK",
            company_info="Industrial automation",
            language="es",
            company_size="small",
            industry="computer_programming_consultancy",
            ceo_email="ceo@za-tek.com",
            contacts=[],
        )

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(program, "extract_contacts", fake_extract)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_LLM_MAX_RETRIES", 2)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_MIN_EXTRACTION_CHARS", 100)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.asyncio.sleep", fake_sleep)

    prediction = asyncio.run(
        program.extract_contacts_with_retries(
            "A" * 600,
            lm=fake_lm,
            source_label="https://za-tek.com",
        )
    )

    assert prediction.company_name == "ZA-TEK"
    assert len(payloads) == 2
    assert len(payloads[1]) < len(payloads[0])


def test_extract_contacts_with_retries_bypasses_cache_on_retry(monkeypatch) -> None:
    program = UrlToContactsProgram()
    payload_lms: list[object] = []

    class CopyableLM:
        def __init__(self, model: str, kwargs: dict[str, object] | None = None):
            self.model = model
            self.kwargs = kwargs or {}

        def copy(self, **kwargs):
            return CopyableLM(self.model, kwargs)

    fake_lm = CopyableLM("openrouter/x-ai/grok-4.1-fast")

    async def fake_extract(website_content: str, lm=None) -> dspy.Prediction:
        payload_lms.append(lm)
        if len(payload_lms) == 1:
            raise RuntimeError("temporary validation error")
        return dspy.Prediction(
            company_name="ZA-TEK",
            company_info="Industrial automation",
            language="es",
            company_size="small",
            industry="computer_programming_consultancy",
            ceo_email="ceo@za-tek.com",
            contacts=[],
        )

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(program, "extract_contacts", fake_extract)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.DEFAULT_LLM_MAX_RETRIES", 2)
    monkeypatch.setattr("backend.ai.stage1_url_to_contacts.asyncio.sleep", fake_sleep)

    prediction = asyncio.run(
        program.extract_contacts_with_retries(
            "website content",
            lm=fake_lm,
            source_label="https://za-tek.com",
        )
    )

    assert prediction.company_name == "ZA-TEK"
    assert len(payload_lms) == 2
    assert payload_lms[0] is fake_lm
    assert payload_lms[1] is not fake_lm
    assert payload_lms[1].kwargs == {"cache": False, "rollout_id": "stage1-retry-2"}
