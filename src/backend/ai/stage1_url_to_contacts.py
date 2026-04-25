"""Stage 1: URL -> contact discovery from crawled website content."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
from enum import Enum
from time import monotonic
from urllib.parse import urlparse

import dspy
from firecrawl import Firecrawl
from firecrawl.v2.types import ScrapeOptions
import httpx
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import FAST_MODEL

logger = logging.getLogger(__name__)

DEFAULT_CRAWL_LIMIT = 8
DEFAULT_CRAWL_POLL_INTERVAL = 1
DEFAULT_CRAWL_TIMEOUT_SECONDS = max(120, int(os.getenv("STAGE1_CRAWL_TIMEOUT_SECONDS", "300")))
DEFAULT_FIRECRAWL_MAX_RETRIES = max(0, int(os.getenv("STAGE1_FIRECRAWL_MAX_RETRIES", "2")))
DEFAULT_FIRECRAWL_RETRY_BASE_DELAY_SECONDS = max(
    0.0,
    float(os.getenv("STAGE1_FIRECRAWL_RETRY_BASE_DELAY_SECONDS", "10")),
)
DEFAULT_HTML_PROBE_TIMEOUT_SECONDS = 10
DEFAULT_HTML_FALLBACK_TIMEOUT_SECONDS = 20
DEFAULT_LLM_MAX_RETRIES = max(0, int(os.getenv("STAGE1_LLM_MAX_RETRIES", "5")))
DEFAULT_LLM_RETRY_BASE_DELAY_SECONDS = max(
    0.0,
    float(os.getenv("STAGE1_LLM_RETRY_BASE_DELAY_SECONDS", "5")),
)
DEFAULT_EXTRACTION_MAX_CHARS = max(50_000, int(os.getenv("STAGE1_EXTRACTION_MAX_CHARS", "350000")))
DEFAULT_MIN_EXTRACTION_CHARS = max(10_000, int(os.getenv("STAGE1_MIN_EXTRACTION_CHARS", "50000")))
DEFAULT_MARKDOWN_MAX_CHARS = max(10_000, int(os.getenv("STAGE1_MARKDOWN_MAX_CHARS", "250000")))
DEFAULT_RAW_HTML_MAX_CHARS_WITH_MARKDOWN = max(
    10_000,
    int(os.getenv("STAGE1_RAW_HTML_MAX_CHARS_WITH_MARKDOWN", "75000")),
)
DEFAULT_RAW_HTML_MAX_CHARS_NO_MARKDOWN = max(
    10_000,
    int(os.getenv("STAGE1_RAW_HTML_MAX_CHARS_NO_MARKDOWN", "200000")),
)
DEFAULT_RAW_HTML_CONTACT_SNIPPET_BUDGET_CHARS = max(
    5_000,
    int(os.getenv("STAGE1_RAW_HTML_CONTACT_SNIPPET_BUDGET_CHARS", "50000")),
)
DEFAULT_CONTACT_SNIPPET_RADIUS_CHARS = max(
    100,
    int(os.getenv("STAGE1_CONTACT_SNIPPET_RADIUS_CHARS", "250")),
)
HTML_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; KonectaAuditor/1.0; +https://konectalabs.com)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
}
TRUNCATION_TEMPLATE = "\n\n[...TRUNCATED {omitted_chars} chars...]\n\n"
CONTACT_EVIDENCE_PATTERNS = (
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?=[^a-zA-Z]|$)", re.IGNORECASE),
    re.compile(
        r"mailto:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?=[^a-zA-Z]|$)",
        re.IGNORECASE,
    ),
    re.compile(r"tel:[+0-9().\-\s]{5,}", re.IGNORECASE),
    re.compile(r"(?:https?:\/\/)?wa\.me\/[+a-zA-Z0-9_-]{4,}", re.IGNORECASE),
    re.compile(r"(?:https?:\/\/)?api\.whatsapp\.com\/[^\s\"'<>]+", re.IGNORECASE),
    re.compile(r"(?:https?:\/\/)?(?:www\.)?linkedin\.com\/[^\s\"'<>]+", re.IGNORECASE),
)



def get_firecrawl_client() -> Firecrawl:
    api_key = (os.getenv("FIRECRAWL_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("FIRECRAWL_API_KEY is required for Stage1 crawl.")
    return Firecrawl(api_key=api_key)


class CrawledWebsiteContent(BaseModel):
    """Website content returned by the Stage 1 crawl."""

    markdown: str = ""
    extraction_content: str = ""


def build_extraction_content(markdown: str, raw_html: str) -> str:
    """Combine crawl outputs into the single string consumed by the extractor."""
    normalized_markdown = markdown.strip()
    normalized_raw_html = raw_html.strip()
    parts: list[str] = []
    if normalized_markdown:
        parts.append(normalized_markdown)
    if normalized_raw_html:
        parts.append(f"## Raw HTML\n\n{normalized_raw_html}")
    original_content = "\n\n".join(parts)
    if len(original_content) <= DEFAULT_EXTRACTION_MAX_CHARS:
        return original_content

    compacted_markdown = truncate_text_keep_edges(
        normalized_markdown,
        DEFAULT_MARKDOWN_MAX_CHARS,
    )
    raw_html_budget = (
        DEFAULT_RAW_HTML_MAX_CHARS_WITH_MARKDOWN
        if compacted_markdown
        else DEFAULT_RAW_HTML_MAX_CHARS_NO_MARKDOWN
    )
    raw_html_contact_evidence = extract_contact_evidence_snippets(
        normalized_raw_html,
        max_total_chars=min(DEFAULT_RAW_HTML_CONTACT_SNIPPET_BUDGET_CHARS, raw_html_budget),
        radius_chars=DEFAULT_CONTACT_SNIPPET_RADIUS_CHARS,
    )
    raw_html_excerpt_budget = max(
        0,
        raw_html_budget - len(raw_html_contact_evidence),
    )
    raw_html_excerpt = truncate_text_keep_edges(
        normalized_raw_html,
        raw_html_excerpt_budget,
    )

    compacted_parts: list[str] = []
    remaining_budget = DEFAULT_EXTRACTION_MAX_CHARS
    remaining_budget = append_bounded_section(
        compacted_parts,
        compacted_markdown,
        remaining_budget=remaining_budget,
    )
    remaining_budget = append_bounded_section(
        compacted_parts,
        raw_html_contact_evidence,
        heading="## Raw HTML Contact Evidence",
        remaining_budget=remaining_budget,
    )
    append_bounded_section(
        compacted_parts,
        raw_html_excerpt,
        heading="## Raw HTML Excerpt",
        remaining_budget=remaining_budget,
    )

    compacted_content = "\n\n".join(compacted_parts)

    logger.info(
        "Stage1: compacted extraction payload (markdown_chars=%s raw_html_chars=%s compacted_chars=%s original_chars=%s)",
        len(normalized_markdown),
        len(normalized_raw_html),
        len(compacted_content),
        len(original_content),
    )
    return compacted_content


def truncate_text_keep_edges(text: str, max_chars: int) -> str:
    """Keep both the beginning and end of a large string within a hard char budget."""
    normalized_text = text.strip()
    if not normalized_text or max_chars <= 0 or len(normalized_text) <= max_chars:
        return normalized_text
    if max_chars <= 64:
        return normalized_text[:max_chars]
    marker = TRUNCATION_TEMPLATE.format(
        omitted_chars=max(0, len(normalized_text) - max_chars),
    )
    available_chars = max_chars - len(marker)
    if available_chars <= 0:
        return normalized_text[:max_chars]
    head_chars = max(1, int(available_chars * 0.6))
    tail_chars = max(1, available_chars - head_chars)
    head = normalized_text[:head_chars].rstrip()
    tail = normalized_text[-tail_chars:].lstrip()
    return f"{head}{marker}{tail}"


def append_bounded_section(
    parts: list[str],
    body: str,
    *,
    remaining_budget: int,
    heading: str | None = None,
) -> int:
    """Append one optional section without exceeding the remaining total budget."""
    normalized_body = body.strip()
    if not normalized_body or remaining_budget <= 0:
        return remaining_budget
    separator_chars = 2 if parts else 0
    prefix = f"{heading}\n\n" if heading else ""
    max_body_chars = remaining_budget - separator_chars - len(prefix)
    if max_body_chars <= 0:
        return 0
    bounded_body = truncate_text_keep_edges(normalized_body, max_body_chars)
    if not bounded_body:
        return remaining_budget
    section = f"{prefix}{bounded_body}"
    parts.append(section)
    return max(0, remaining_budget - separator_chars - len(section))


def extract_contact_evidence_snippets(
    raw_html: str,
    *,
    max_total_chars: int,
    radius_chars: int,
) -> str:
    """Collect deterministic HTML snippets around contact-like protocol markers."""
    normalized_raw_html = raw_html.strip()
    if not normalized_raw_html or max_total_chars <= 0:
        return ""

    windows: list[tuple[int, int]] = []
    for pattern in CONTACT_EVIDENCE_PATTERNS:
        for match in pattern.finditer(normalized_raw_html):
            start = max(0, match.start() - radius_chars)
            end = min(len(normalized_raw_html), match.end() + radius_chars)
            windows.append((start, end))

    if not windows:
        return ""

    snippets: list[str] = []
    used_ranges: list[tuple[int, int]] = []
    total_chars = 0
    for start, end in sorted(windows):
        if any(start < used_end and used_start < end for used_start, used_end in used_ranges):
            continue
        snippet = normalized_raw_html[start:end].strip()
        if not snippet:
            continue
        separator_chars = 7 if snippets else 0
        if total_chars + len(snippet) + separator_chars > max_total_chars:
            break
        used_ranges.append((start, end))
        snippets.append(snippet)
        total_chars += len(snippet) + separator_chars
    return "\n\n---\n\n".join(snippets)


def crawl(
    url: str,
    limit: int = DEFAULT_CRAWL_LIMIT,
    poll_interval: int = DEFAULT_CRAWL_POLL_INTERVAL,
    timeout: int = DEFAULT_CRAWL_TIMEOUT_SECONDS,
) -> CrawledWebsiteContent:
    """Crawl the website and return markdown plus raw HTML evidence."""
    result = get_firecrawl_client().crawl(
        url=url,
        limit=limit,
        poll_interval=poll_interval,
        timeout=timeout,
        scrape_options=ScrapeOptions(
            formats=["markdown", "raw_html"],
            only_main_content=False,
        ),
    )
    markdown = "\n\n".join(
        (doc.markdown or "").strip()
        for doc in result.data
        if (doc.markdown or "").strip()
    )
    raw_html = "\n\n".join(
        (doc.raw_html or "").strip()
        for doc in result.data
        if (doc.raw_html or "").strip()
    )
    return CrawledWebsiteContent(
        markdown=markdown,
        extraction_content=build_extraction_content(markdown, raw_html),
    )


class ContactType(str, Enum):
    """Allowed contact types for discovery."""

    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    LINKEDIN = "linkedin"


class Industry(str, Enum):
    """Canonical industry slugs for hard-match filtering."""

    REAL_ESTATE_ACTIVITIES = "real_estate_activities"
    LEGAL_ACCOUNTING = "legal_accounting"
    INSURANCE_PENSION = "insurance_pension"
    FINANCIAL_INSURANCE_AUXILIARY = "financial_insurance_auxiliary"
    COMPUTER_PROGRAMMING_CONSULTANCY = "computer_programming_consultancy"
    ADVERTISING_MARKET_RESEARCH = "advertising_market_research"
    HUMAN_HEALTH = "human_health"
    WAREHOUSING_TRANSPORT_SUPPORT = "warehousing_transport_support"
    LAND_TRANSPORT = "land_transport"
    OFFICE_ADMINISTRATIVE_SUPPORT = "office_administrative_support"
    EMPLOYMENT_ACTIVITIES = "employment_activities"
    WHOLESALE_RETAIL_MOTOR_VEHICLES = "wholesale_retail_motor_vehicles"
    OTHER = "other"
    UNKNOWN = "unknown"


class DiscoveredContact(BaseModel):
    """A single contact discovered from a website."""

    type: ContactType = Field(
        description='Contact type: must be one of "email", "phone", "whatsapp", or "linkedin".',
    )
    value: str = Field(
        description=(
            "The contact value. Email address, phone number, WhatsApp number, or LinkedIn URL/handle. "
            "Email addresses must be complete and syntactically valid, including full domain and TLD."
        ),
    )
    notes: str | None = Field(
        default=None,
        description='Optional note about where the contact was found, for example "footer" or "contact page".',
    )
    objective: str | None = Field(
        default=None,
        description=(
            "One simple sales-audit objective tailored to this contact. It must be achievable only through chat, "
            "must help evaluate the seller's usefulness/clarity/speed, and must not depend on email, files, "
            "documents, meetings, demos, or off-channel coordination."
        ),
    )


class ContactDiscoveryResult(BaseModel):
    """Result of Stage 1 URL -> contacts."""

    company_name: str = Field(description="The official company name discovered from the URL")
    company_info: str = Field(default="", description="Free-form markdown summary of general company information")
    language: str | None = Field(
        default=None,
        description="Language code (for example 'es', 'en') best suited to talk with this company contacts",
    )
    company_size: str = Field(
        default="unknown",
        description=(
            "Estimated company size bucket based on website evidence only. "
            "Must be one of: small, medium, large, unknown."
        ),
    )
    industry: str = Field(
        default="unknown",
        description="Canonical industry slug for filtering (hard string match); see Stage 1 signature instructions.",
    )
    website_markdown: str = Field(
        default="",
        description="Website markdown returned by the crawl.",
    )
    ceo_email: str | None = Field(
        default=None,
        description=(
            "Single leadership email evidenced on the website. Prefer CEO; if absent, use the highest senior "
            "decision-maker available (founder, co-founder, owner, director, manager, or equivalent). "
            "Return null only when no leadership evidence is present."
        ),
    )
    contacts: list[DiscoveredContact] = Field(default_factory=list)

    def get_contacts(self, contact_type: ContactType) -> list[DiscoveredContact]:
        """Get all contacts of a specific type."""
        return [contact for contact in self.contacts if contact.type == contact_type]

    def set_website_markdown(self, website_markdown: str):
        """Add website markdown to the result."""
        self.website_markdown = website_markdown

    @classmethod
    def from_prediction(cls, prediction: dspy.Prediction) -> ContactDiscoveryResult:
        """Build ContactDiscoveryResult from extractor (dspy) prediction."""
        return cls(
            company_name=prediction.company_name,
            company_info=prediction.company_info,
            language=prediction.language,
            company_size=getattr(prediction, "company_size", "unknown"),
            industry=getattr(prediction, "industry", "unknown"),
            ceo_email=prediction.ceo_email,
            contacts=prediction.contacts,
        )


class UrlToContactsProgram(Program):
    """Stage 1 Program: normalize URL, crawl website markdown, and extract contacts/company context."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm)

        class ContactDiscoverySignature(dspy.Signature):
            """Extract company profile + contacts from crawled website content.

            Input combines crawl markdown plus raw HTML evidence.
            Use only that evidence.

            Industry normalization:
            - Return exactly one industry value suitable for hard string-match filtering.
            - No commas; no descriptive phrases. Use a single lowercase slug with words joined by underscores.
            - Most typical industries and how to write them: """ + ", ".join([e.value for e in Industry]) + """.
            - When the evidence maps to one of these, output that exact slug. When evidence is insufficient, output unknown.

            Company size normalization:
            - Infer employee-size estimate from website evidence only.
            - Return only one bucket:
              - small: estimated 1-10 employees
              - medium: estimated 11-20 employees
              - large: estimated 20+ employees
              - unknown: insufficient evidence

            Email quality rules:
            - Return only syntactically complete email addresses with a full domain and TLD.
            - Never output truncated email values such as local-part-only addresses or domains without a dot/TLD.
            - If the evidence for an email is partial or ambiguous, omit that contact instead of guessing.
            - Every contact object must include both type and value. Never emit partial contact objects.

            Phone vs WhatsApp rules:
            - Use type=whatsapp only when the evidence explicitly shows WhatsApp, for example wa.me links,
              api.whatsapp.com links, a visible WhatsApp label/button, or text that clearly says the number is for
              WhatsApp.
            - Use type=phone for generic phone numbers, call links, office numbers, branch numbers, toll-free
              numbers, hotlines, switchboards, or any number whose WhatsApp capability is not explicit.
            - Never classify a number as whatsapp just because it is a phone number or includes a country code.

            Contact objective rules:
            - For every discovered contact, generate one simple objective that the buyer persona can pursue in chat.
            - The objective must help reveal whether the seller is good: usefulness, clarity, speed, and commercial judgment.
            - The objective must be specific and concrete, not generic ("evaluate sales quality" is too vague).
            - The objective must be resolvable through chat alone. Do not require email, attachments, PDFs, price lists,
              catalogs, documents, meetings, demos, calls, forms, or any off-channel exchange.
            - Good pattern: ask about one concrete product/service, price/range, availability, recommendation,
              comparison, fit, scope, or timing detail that a real prospect could ask naturally.
            - Keep objectives short and human-readable.
            - Adapt the objective to the real business shown in the website. Do not copy these examples literally when
              they do not fit the company.

            Contact objective examples by industry:
            - computer_programming_consultancy example 1: Ask which plan or service scope would fit a small team, what
              it costs per month, and what key capability is missing in the cheaper option.
            - computer_programming_consultancy example 2: Ask how long a simple implementation usually takes, what is
              included in onboarding, and whether they recommend a lighter starter setup first.
            - unknown example 1: If the business is not clearly classified but the offer is visible, ask the price
              range for one concrete product or service, what is included, and whether they recommend a simpler option.
            - unknown example 2: Ask whether they can handle one specific need, what the approximate timing or cost is,
              and which alternative they recommend if the first option is not the best fit.
            - language school example 1: Ask what an English course costs, how many classes per week it includes, and
              which level they recommend for a rusty beginner.
            - language school example 2: Ask whether they offer a conversation-focused plan, what the monthly fee is,
              and whether they recommend group or private classes first.
            - car dealership example 1: Ask whether they have a Toyota T-Cross, what price range it is in, and which
              similar model they would recommend instead for the same budget.
            - car dealership example 2: Ask whether they have a lower-priced used option, what it costs, and whether
              they would recommend that one over the T-Cross for someone trying to spend less.
            """

            website_content: str = dspy.InputField(
                desc="Website content produced by Stage1 crawl: markdown plus raw HTML evidence."
            )
            company_name: str = dspy.OutputField(
                desc="Official company name from the website content."
            )
            company_info: str = dspy.OutputField(
                desc="Concise markdown summary of what the company does, what it sells, and key business context."
            )
            language: str = dspy.OutputField(
                desc="Language code (for example es, en, pt) best suited for outreach."
            )
            company_size: str = dspy.OutputField(
                desc=(
                    "Estimated company size bucket from website evidence only. "
                    "Must be one of: small, medium, large, unknown."
                )
            )
            industry: str = dspy.OutputField(
                desc=(
                    "One industry slug for hard-match filtering: no commas, not descriptive. "
                    f"Use exact slugs: {', '.join([e.value for e in Industry])}."
                )
            )
            ceo_email: str | None = dspy.OutputField(
                desc=(
                    "Single leadership email from website evidence. Do not leave this blank when website evidence "
                    "shows a leadership person and an attributable email. Priority: CEO > Founder/Co-founder > "
                    "Owner/Managing Director/Director/General Manager/Head/Partner/responsible senior contact. "
                    "If multiple options exist, return only the highest-hierarchy one. Return only a complete valid "
                    "email address with full domain and TLD. Return null when no complete attributable leadership "
                    "email is evidenced."
                )
            )
            contacts: list[DiscoveredContact] = dspy.OutputField(
                desc=(
                    "Discovered contacts with type=email|phone|whatsapp|linkedin, value, optional notes, and one "
                    "chat-resolvable objective. Email values must be complete valid email addresses."
                )
            )

        self.extractor = dspy.Predict(ContactDiscoverySignature)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL to include scheme for crawl operations."""
        cleaned = url.strip()
        if not cleaned:
            return ""
        parsed = urlparse(cleaned)
        if parsed.scheme:
            return cleaned
        return f"https://{cleaned}"

    def _build_www_variant(self, normalized_url: str) -> str | None:
        """Build a www-prefixed variant for bare domains."""
        parsed = urlparse(normalized_url)
        hostname = parsed.hostname or ""
        if not hostname or hostname.startswith("www.") or hostname == "localhost" or hostname.endswith(".local"):
            return None
        try:
            ipaddress.ip_address(hostname)
            return None
        except ValueError:
            pass
        if "." not in hostname:
            return None
        auth = ""
        if parsed.username:
            auth = parsed.username
            if parsed.password:
                auth = f"{auth}:{parsed.password}"
            auth = f"{auth}@"
        netloc = f"{auth}www.{hostname}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(netloc=netloc).geturl()

    def _response_has_html_content(self, response: httpx.Response) -> bool:
        """Return True when the response looks like HTML."""
        if response.status_code >= 400:
            return False
        content_type = (response.headers.get("content-type") or "").lower()
        preview = response.text[:2048].lower()
        return (
            "text/html" in content_type
            or "application/xhtml+xml" in content_type
            or "<!doctype html" in preview
            or "<html" in preview
        )

    async def probe_html_url(self, normalized_url: str) -> bool:
        """Check whether the URL returns HTML before crawling."""
        timeout = httpx.Timeout(DEFAULT_HTML_PROBE_TIMEOUT_SECONDS, connect=5.0)
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers=HTML_REQUEST_HEADERS,
                timeout=timeout,
            ) as client:
                response = await client.get(normalized_url)
        except httpx.HTTPError as exc:
            logger.warning("Stage1: HTML probe failed for %s (%s)", normalized_url, exc)
            return False
        has_html = self._response_has_html_content(response)
        logger.info(
            "Stage1: HTML probe %s for %s (status=%s content_type=%s)",
            "succeeded" if has_html else "rejected",
            normalized_url,
            response.status_code,
            response.headers.get("content-type"),
        )
        return has_html

    async def resolve_crawl_url(self, normalized_url: str) -> str:
        """Pick the first URL variant that returns HTML."""
        if await self.probe_html_url(normalized_url):
            return normalized_url
        fallback_url = self._build_www_variant(normalized_url)
        if fallback_url and await self.probe_html_url(fallback_url):
            logger.info("Stage1: using www fallback %s for input %s", fallback_url, normalized_url)
            return fallback_url
        if fallback_url:
            raise RuntimeError(f"Stage1 HTML probe failed for both {normalized_url} and {fallback_url}.")
        raise RuntimeError(f"Stage1 HTML probe failed for {normalized_url}.")

    async def crawl_with_firecrawl(self, normalized_url: str) -> CrawledWebsiteContent:
        """Run the primary Firecrawl path in a worker thread."""
        return await asyncio.to_thread(
            crawl,
            normalized_url,
            DEFAULT_CRAWL_LIMIT,
            DEFAULT_CRAWL_POLL_INTERVAL,
            DEFAULT_CRAWL_TIMEOUT_SECONDS,
        )

    async def fetch_html_without_firecrawl(self, normalized_url: str) -> CrawledWebsiteContent:
        """Fetch direct HTML when Firecrawl is unavailable."""
        timeout = httpx.Timeout(DEFAULT_HTML_FALLBACK_TIMEOUT_SECONDS, connect=5.0)
        logger.warning(
            "Stage1: attempting direct HTML fallback for %s. This path does not render JavaScript.",
            normalized_url,
        )
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers=HTML_REQUEST_HEADERS,
                timeout=timeout,
            ) as client:
                response = await client.get(normalized_url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.exception(
                "Stage1: direct HTML fallback failed for %s.",
                normalized_url,
            )
            raise RuntimeError(f"Stage1 direct HTML fallback failed for {normalized_url}: {exc}") from exc

        if not self._response_has_html_content(response):
            logger.error(
                "Stage1: direct HTML fallback rejected non-HTML response for %s (status=%s content_type=%s)",
                normalized_url,
                response.status_code,
                response.headers.get("content-type"),
            )
            raise RuntimeError(f"Stage1 direct HTML fallback received non-HTML response for {normalized_url}.")

        raw_html = response.text.strip()
        if not raw_html:
            logger.error("Stage1: direct HTML fallback returned empty body for %s", normalized_url)
            raise RuntimeError(f"Stage1 direct HTML fallback returned empty body for {normalized_url}.")

        logger.warning(
            "Stage1: direct HTML fallback succeeded for %s (chars=%s). Continuing with raw HTML only and no JS rendering.",
            normalized_url,
            len(raw_html),
        )
        return CrawledWebsiteContent(
            markdown="",
            extraction_content=build_extraction_content("", raw_html),
        )

    def _classify_exception(self, exc: Exception) -> str:
        """Map one exception to a stable coarse error code for logs."""
        name = type(exc).__name__.lower()
        text = str(exc).lower()
        if "quota" in text or "rate" in text or "429" in text:
            return "rate_limit"
        if "timeout" in text or "timed out" in text:
            return "timeout"
        if "adapterparse" in name:
            return "adapter_parse"
        if "validation" in name or "validation" in text:
            return "validation"
        if "badrequest" in name or "bad request" in text:
            return "bad_request"
        if "firecrawl" in text:
            return "firecrawl"
        return name or exc.__class__.__name__

    def _is_context_limit_error(self, exc: Exception) -> bool:
        """Return True when provider rejected the request for exceeding model context."""
        text = str(exc).lower()
        return (
            "maximum context length" in text
            or "context length" in text and "reduce the length" in text
            or "requested about" in text and "tokens" in text
        )

    def _shrink_extraction_content(self, website_content: str) -> str:
        """Reduce extraction payload size after a model context overflow."""
        normalized_content = website_content.strip()
        if not normalized_content or len(normalized_content) <= DEFAULT_MIN_EXTRACTION_CHARS:
            return normalized_content
        next_budget = max(DEFAULT_MIN_EXTRACTION_CHARS, int(len(normalized_content) * 0.5))
        if next_budget >= len(normalized_content):
            next_budget = max(DEFAULT_MIN_EXTRACTION_CHARS, len(normalized_content) - 10_000)
        return truncate_text_keep_edges(normalized_content, next_budget)

    def _retry_delay_seconds(self, base_delay_seconds: float, attempt_index: int) -> float:
        """Compute one bounded exponential backoff delay."""
        if base_delay_seconds <= 0:
            return 0.0
        return min(base_delay_seconds * (2 ** attempt_index), 120.0)

    def _exception_info(self, exc: Exception | None):
        """Build exc_info tuple for logging outside an except block."""
        if exc is None:
            return None
        return (type(exc), exc, exc.__traceback__)

    def _lm_for_attempt(self, lm: dspy.LM, attempt_index: int):
        """Use the same model across retries while bypassing cached bad completions."""
        if attempt_index == 0 or not hasattr(lm, "copy"):
            return lm
        try:
            return lm.copy(
                cache=False,
                rollout_id=f"stage1-retry-{attempt_index + 1}",
            )
        except Exception:
            return lm

    async def crawl_website_content(self, normalized_url: str) -> CrawledWebsiteContent:
        """Run crawl and return the markdown plus raw HTML evidence."""
        logger.info(f"Stage1: crawling {normalized_url}")
        total_attempts = DEFAULT_FIRECRAWL_MAX_RETRIES + 1
        last_exception: Exception | None = None
        for attempt_index in range(total_attempts):
            attempt = attempt_index + 1
            attempt_started_at = monotonic()
            try:
                logger.info(
                    "Stage1: Firecrawl attempt %s/%s for %s",
                    attempt,
                    total_attempts,
                    normalized_url,
                )
                content = await self.crawl_with_firecrawl(normalized_url)
                if not content.extraction_content:
                    raise RuntimeError("Firecrawl returned no extractable content.")
                logger.info(
                    "Stage1: Firecrawl attempt %s/%s succeeded for %s in %.1fs (markdown_chars=%s extraction_chars=%s)",
                    attempt,
                    total_attempts,
                    normalized_url,
                    monotonic() - attempt_started_at,
                    len(content.markdown),
                    len(content.extraction_content),
                )
                if not content.markdown:
                    logger.warning(
                        "Stage1: Firecrawl returned no markdown for %s on attempt %s/%s. Continuing with raw HTML only.",
                        normalized_url,
                        attempt,
                        total_attempts,
                    )
                return content
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Stage1: Firecrawl attempt %s/%s failed for %s after %.1fs (category=%s type=%s error=%s)",
                    attempt,
                    total_attempts,
                    normalized_url,
                    monotonic() - attempt_started_at,
                    self._classify_exception(exc),
                    type(exc).__name__,
                    exc,
                )
                if attempt < total_attempts:
                    delay_seconds = self._retry_delay_seconds(
                        DEFAULT_FIRECRAWL_RETRY_BASE_DELAY_SECONDS,
                        attempt_index,
                    )
                    if delay_seconds > 0:
                        logger.warning(
                            "Stage1: waiting %.1fs before Firecrawl retry %s/%s for %s",
                            delay_seconds,
                            attempt + 1,
                            total_attempts,
                            normalized_url,
                        )
                        await asyncio.sleep(delay_seconds)

        logger.error(
            "Stage1: Firecrawl exhausted for %s after %s attempts. Falling back to direct HTML fetch without JS rendering.",
            normalized_url,
            total_attempts,
            exc_info=self._exception_info(last_exception),
        )
        return await self.fetch_html_without_firecrawl(normalized_url)

    async def extract_contacts(self, website_content: str, lm: dspy.LM = None) -> ContactDiscoveryResult:
        """Extract company profile and contacts from crawl content."""
        if lm is not None:
            with dspy.context(lm=lm):
                prediction: dspy.Prediction = await self.extractor.acall(website_content=website_content)
        else:
            prediction: dspy.Prediction = await self.extractor.acall(website_content=website_content)
        model_name = getattr(lm, "model", "default_lm")
        logger.info(f"Stage1: extracted {len(prediction.contacts)} contacts on {model_name}")
        return prediction

    async def extract_contacts_with_retries(
        self,
        website_content: str,
        *,
        lm: dspy.LM,
        source_label: str,
    ) -> dspy.Prediction:
        """Extract contacts using repeated attempts on the same model."""
        total_attempts = DEFAULT_LLM_MAX_RETRIES + 1
        attempt_content = website_content
        last_exception: Exception | None = None
        for attempt_index in range(total_attempts):
            attempt = attempt_index + 1
            attempt_started_at = monotonic()
            attempt_lm = self._lm_for_attempt(lm, attempt_index)
            try:
                logger.info(
                    "Stage1: extraction attempt %s/%s for %s using %s (content_chars=%s)",
                    attempt,
                    total_attempts,
                    source_label,
                    attempt_lm.model,
                    len(attempt_content),
                )
                prediction = await self.extract_contacts(attempt_content, lm=attempt_lm)
                logger.info(
                    "Stage1: extraction attempt %s/%s succeeded for %s in %.1fs using %s",
                    attempt,
                    total_attempts,
                    source_label,
                    monotonic() - attempt_started_at,
                    attempt_lm.model,
                )
                return prediction
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Stage1: extraction attempt %s/%s failed for %s after %.1fs using %s (category=%s type=%s error=%s)",
                    attempt,
                    total_attempts,
                    source_label,
                    monotonic() - attempt_started_at,
                    attempt_lm.model,
                    self._classify_exception(exc),
                    type(exc).__name__,
                    exc,
                )
                if attempt < total_attempts:
                    if self._is_context_limit_error(exc):
                        shrunk_content = self._shrink_extraction_content(attempt_content)
                        if shrunk_content and shrunk_content != attempt_content:
                            logger.warning(
                                "Stage1: shrinking extraction payload for %s after context overflow (chars=%s -> %s)",
                                source_label,
                                len(attempt_content),
                                len(shrunk_content),
                            )
                            attempt_content = shrunk_content
                    delay_seconds = self._retry_delay_seconds(
                        DEFAULT_LLM_RETRY_BASE_DELAY_SECONDS,
                        attempt_index,
                    )
                    if delay_seconds > 0:
                        logger.warning(
                            "Stage1: waiting %.1fs before extraction retry %s/%s for %s using %s",
                            delay_seconds,
                            attempt + 1,
                            total_attempts,
                            source_label,
                            attempt_lm.model,
                        )
                        await asyncio.sleep(delay_seconds)

        logger.error(
            "Stage1: extraction exhausted for %s after %s attempts using %s",
            source_label,
            total_attempts,
            lm.model,
            exc_info=self._exception_info(last_exception),
        )
        raise RuntimeError(
            f"Stage1 extraction exhausted for {source_label} after {total_attempts} attempts using {lm.model}."
        ) from last_exception

    async def dev_aforward(self, text: str) -> ContactDiscoveryResult:
        """Development endpoint for testing."""
        prediction: dspy.Prediction = await self.extract_contacts_with_retries(
            text,
            lm=FAST_MODEL,
            source_label="dev_text",
        )
        assert isinstance(prediction, dspy.Prediction)

        pydantic_result = ContactDiscoveryResult.from_prediction(prediction)
        pydantic_result.set_website_markdown(text)

        return pydantic_result

    async def aforward(self, url: str) -> ContactDiscoveryResult:
        """Forward the URL to the program and return contact discovery."""
        normalized_url = self._normalize_url(url)
        if not normalized_url:
            raise ValueError("url is required")
        logger.info(f"Stage1: normalized url: {normalized_url}")

        crawl_url = await self.resolve_crawl_url(normalized_url)
        logger.info(f"Stage1: selected crawl url: {crawl_url}")

        website_content = await self.crawl_website_content(crawl_url)
        if not website_content.extraction_content:
            raise RuntimeError(f"Stage1 crawl produced no extractable content for {crawl_url}.")

        prediction: dspy.Prediction = await self.extract_contacts_with_retries(
            website_content.extraction_content,
            lm=FAST_MODEL,
            source_label=crawl_url,
        )
        assert isinstance(prediction, dspy.Prediction)

        pydantic_result = ContactDiscoveryResult.from_prediction(prediction)
        pydantic_result.set_website_markdown(website_content.markdown)

        return pydantic_result


if __name__ == "__main__":
    async def amain():
        program = UrlToContactsProgram()
        result = await program.aforward("https://konectalabs.com")
        print(f"\nCompany: {result.company_name}")
        print(f"\nContacts found: {len(result.contacts)}")
        for contact in result.contacts:
            suffix = f" ({contact.notes})" if contact.notes else ""
            print(f"  - {contact.type.value}: {contact.value}{suffix}")
        print(f"\nCompany info:\n{result.company_info[:500]}...")
        print(f"\nWebsite markdown chars: {len(result.website_markdown)}")

    def main():
        result = crawl(url="https://konectalabs.com", limit=5, poll_interval=1, timeout=120)
        print(result)
    asyncio.run(amain())
