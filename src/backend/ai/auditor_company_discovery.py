"""Pro-search-driven company discovery for automated auditor intake."""

from __future__ import annotations

import json

import dspy
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import gpt_5_4_mini
from backend.database import normalize_company_source_url, normalize_email
from backend.deep_research import extract_response_data, pro_search

PRIORITY_INDUSTRIES = (
    "industrial suppliers, manufacturers, or industrial B2B services",
    "logistics, freight, customs, warehousing, and supply-chain services",
    "software or SaaS companies with a demo, sales, or contact-us motion",
    "professional services, agencies, consultancies, and B2B service firms",
    "real estate, coworking, architecture, and construction-related B2B firms",
    "education, training, and executive programs that convert inbound inquiries",
)

PERPLEXITY_DISCOVERY_BRIEF = """
You are sourcing real companies for Konecta Auditor.

Konecta Auditor is a mystery-lead audit product.
It sends realistic inbound sales leads through the public contact channels on a company's website.
It then measures whether those public-facing contacts respond well, qualify the lead, build trust, and move the lead to a useful next step.
The business value is highest when the CEO is probably not the person answering those contacts, because the final report is meant to reveal operational sales issues that leadership may not be seeing.

Find companies that are strong candidates for that audit.

Perfect-match characteristics:
- the company depends on inbound leads arriving through public website contacts,
- the contact path is public and visible on the official site,
- the contact is likely handled by employees, sales reps, coordinators, branch staff, admissions staff, or a commercial team instead of the CEO/founder,
- the company has a sales motion where weak contact handling would plausibly lose revenue.

Preferred industries:
{industry_block}

Hard requirements:
- return only real companies with an official website,
- prefer companies with clear public contact paths such as contact pages, sales pages, request-a-quote pages, WhatsApp buttons, visible sales emails, or lead forms,
- prefer companies where a human conversation after the first inquiry is commercially important,
- require one public leadership recipient suitable for the final audit report,
- require a complete leadership email address with grounded public evidence,
- include grounded evidence for why the company fits.

Avoid:
- giant global brands or companies with enterprise call-center structures,
- solo consultants, freelancers, and founder-led micro-businesses where the founder is likely answering directly,
- pure self-serve ecommerce, consumer checkout flows, or app-only signup businesses,
- directories, marketplaces, job boards, government entities, nonprofits, and universities,
- companies already listed in the exclusions.

Excluded company names:
{excluded_names_block}

Excluded website URLs or domains:
{excluded_urls_block}

Deliver a concise research memo for exactly {count} strong candidates.
For each candidate include:
- company name,
- official website,
- industry,
- country or region,
- public contact paths or channels found,
- why inbound lead handling likely matters to revenue,
- why the public contact is likely handled by non-CEO employees,
- leadership recipient name if available,
- leadership recipient role,
- leadership recipient email,
- why that leadership recipient is a credible final-report destination,
- why this is a strong mystery-lead audit target,
- source URLs.
"""

EXTRACTION_INSTRUCTIONS = """
Read the research memo and return only the strongest candidate companies for Konecta Auditor.

Rules:
- Return at most the requested count.
- Keep only companies that clearly match the ICP from the memo.
- Exclude any company whose name or website appears in the exclusion lists.
- Require one official website per company.
- Prefer companies with grounded evidence of public contact channels and likely employee-handled lead intake.
- Require a grounded leadership recipient role plus a complete email address.
- Reject companies that only show generic sales/support/contact/logistics inboxes with no leadership attribution.
- Prefer companies where poor lead handling could plausibly hurt revenue.
- Do not invent facts that are not present in the research memo.
- Keep summaries concise and evidence-based.
- Keep URLs stable and official. Prefer the company homepage/root URL as `website_url`.
- `source_urls` should contain the most relevant supporting URLs mentioned in the memo.
"""


class AuditorCandidateCompany(BaseModel):
    """One company candidate returned by discovery."""

    company_name: str
    website_url: str
    industry: str
    country_or_region: str | None = None
    fit_summary: str
    likely_contact_owner: str
    leadership_recipient_name: str | None = None
    leadership_recipient_role: str
    leadership_recipient_email: str
    leadership_recipient_evidence: str
    public_contact_channels: list[str] = Field(default_factory=list)
    public_contact_paths: list[str] = Field(default_factory=list)
    lead_dependency_evidence: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class AuditorCandidateCompanyBatch(BaseModel):
    """Structured discovery output."""

    companies: list[AuditorCandidateCompany] = Field(default_factory=list)


class AuditorCompanyDiscoveryProgram(Program):
    """Find strong auditor candidates with Perplexity pro search plus typed extraction."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or gpt_5_4_mini)

        class AuditorCompanyDiscoverySignature(dspy.Signature):
            """Select the best company candidates for Konecta Auditor from research notes."""

            requested_count: int = dspy.InputField(desc="Maximum number of companies to return.")
            excluded_company_names: str = dspy.InputField(
                desc="Plain-text exclusion list of company names that must not be returned."
            )
            excluded_company_urls: str = dspy.InputField(
                desc="Plain-text exclusion list of company URLs or domains that must not be returned."
            )
            research_memo: str = dspy.InputField(
                desc="Perplexity research memo with grounded candidate evidence."
            )
            result: AuditorCandidateCompanyBatch = dspy.OutputField(
                desc="Best-fit company candidates for the auditor ICP."
            )

        self.extractor = dspy.Predict(
            AuditorCompanyDiscoverySignature.with_instructions(EXTRACTION_INSTRUCTIONS)
        )

    def build_search_prompt(
        self,
        *,
        count: int,
        exclude_company_urls: list[str],
        exclude_company_names: list[str],
    ) -> str:
        """Build the Perplexity discovery brief."""
        industry_block = "\n".join(f"- {item}" for item in PRIORITY_INDUSTRIES)
        excluded_names_block = self.format_prompt_list(exclude_company_names)
        excluded_urls_block = self.format_prompt_list(exclude_company_urls)
        return PERPLEXITY_DISCOVERY_BRIEF.format(
            count=count,
            industry_block=industry_block,
            excluded_names_block=excluded_names_block,
            excluded_urls_block=excluded_urls_block,
        ).strip()

    def format_prompt_list(self, values: list[str], *, limit: int = 200) -> str:
        """Format one exclusion list for prompt usage."""
        cleaned = [
            value.strip()
            for value in values
            if value and value.strip()
        ]
        if not cleaned:
            return "- none"
        return "\n".join(f"- {value}" for value in cleaned[:limit])

    async def run_research(
        self,
        *,
        count: int,
        exclude_company_urls: list[str],
        exclude_company_names: list[str],
    ) -> str:
        """Run Perplexity pro search and bundle the relevant response fields."""
        prompt = self.build_search_prompt(
            count=count,
            exclude_company_urls=exclude_company_urls,
            exclude_company_names=exclude_company_names,
        )
        response = await pro_search(prompt)
        payload = extract_response_data(response)
        parts = [
            "## Research memo",
            payload.get("output_text") or "",
        ]

        raw_search_queries = payload.get("search_queries")
        if raw_search_queries:
            parts.extend(
                [
                    "",
                    "## Search queries",
                    raw_search_queries,
                ]
            )

        raw_citations = payload.get("citations")
        if raw_citations:
            parts.extend(
                [
                    "",
                    "## Citations",
                    raw_citations,
                ]
            )

        return "\n".join(part for part in parts if part is not None).strip()

    async def extract_candidates(
        self,
        *,
        requested_count: int,
        exclude_company_urls: list[str],
        exclude_company_names: list[str],
        research_memo: str,
    ) -> AuditorCandidateCompanyBatch:
        """Extract the final candidate list from the research memo."""
        prediction = await self.extractor.acall(
            requested_count=requested_count,
            excluded_company_names=self.format_prompt_list(exclude_company_names),
            excluded_company_urls=self.format_prompt_list(exclude_company_urls),
            research_memo=research_memo,
        )
        return self.normalize_batch(prediction.result, requested_count=requested_count)

    def normalize_batch(
        self,
        batch: AuditorCandidateCompanyBatch,
        *,
        requested_count: int,
    ) -> AuditorCandidateCompanyBatch:
        """Normalize URLs and drop duplicate or malformed company rows."""
        companies: list[AuditorCandidateCompany] = []
        seen_urls: set[str] = set()

        for item in batch.companies:
            website_url = normalize_company_source_url(item.website_url)
            if not website_url:
                continue
            if website_url in seen_urls:
                continue
            seen_urls.add(website_url)

            companies.append(
                AuditorCandidateCompany(
                    company_name=item.company_name.strip(),
                    website_url=website_url,
                    industry=item.industry.strip() or "unknown",
                    country_or_region=(item.country_or_region or "").strip() or None,
                    fit_summary=item.fit_summary.strip(),
                    likely_contact_owner=item.likely_contact_owner.strip(),
                    leadership_recipient_name=(item.leadership_recipient_name or "").strip() or None,
                    leadership_recipient_role=item.leadership_recipient_role.strip(),
                    leadership_recipient_email=normalize_email(item.leadership_recipient_email),
                    leadership_recipient_evidence=item.leadership_recipient_evidence.strip(),
                    public_contact_channels=self.normalize_text_list(item.public_contact_channels),
                    public_contact_paths=self.normalize_text_list(item.public_contact_paths),
                    lead_dependency_evidence=self.normalize_text_list(item.lead_dependency_evidence),
                    source_urls=self.normalize_url_list(item.source_urls, fallback_url=website_url),
                )
            )

            if not companies[-1].leadership_recipient_email:
                companies.pop()
                seen_urls.discard(website_url)
                continue
            if not companies[-1].leadership_recipient_role:
                companies.pop()
                seen_urls.discard(website_url)
                continue
            if not companies[-1].leadership_recipient_evidence:
                companies.pop()
                seen_urls.discard(website_url)
                continue

            if len(companies) >= requested_count:
                break

        return AuditorCandidateCompanyBatch(companies=companies)

    def normalize_text_list(self, values: list[str]) -> list[str]:
        """Trim and dedupe one text list while preserving order."""
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in values:
            text = " ".join(str(value or "").split())
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)

        return cleaned

    def normalize_url_list(self, values: list[str], *, fallback_url: str) -> list[str]:
        """Trim, normalize, and dedupe source URLs."""
        cleaned: list[str] = []
        seen: set[str] = set()

        for value in values:
            normalized = normalize_company_source_url(value)
            if not normalized:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)

        if cleaned:
            return cleaned
        return [fallback_url]

    async def aforward(
        self,
        *,
        count: int,
        exclude_company_urls: list[str] | None = None,
        exclude_company_names: list[str] | None = None,
    ) -> AuditorCandidateCompanyBatch:
        """Run research, then extract the final structured candidates."""
        resolved_urls = exclude_company_urls or []
        resolved_names = exclude_company_names or []
        research_memo = await self.run_research(
            count=count,
            exclude_company_urls=resolved_urls,
            exclude_company_names=resolved_names,
        )
        result = await self.extract_candidates(
            requested_count=count,
            exclude_company_urls=resolved_urls,
            exclude_company_names=resolved_names,
            research_memo=research_memo,
        )
        return result


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        program = AuditorCompanyDiscoveryProgram()
        result = await program.aforward(
            count=2,
            exclude_company_urls=["https://example.com"],
            exclude_company_names=["Example Inc"],
        )
        print(json.dumps(result.model_dump(), indent=2))

    asyncio.run(_main())
