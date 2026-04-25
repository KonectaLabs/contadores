"""Public leadership-recipient discovery for Konecta Auditor."""

from __future__ import annotations

import json

import dspy
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import gpt_5_4_mini
from backend.database import normalize_company_source_url, normalize_email
from backend.deep_research import extract_response_data, pro_search

LEADERSHIP_RECIPIENT_RESEARCH_BRIEF = """
You are validating whether a company has a public leadership recipient suitable for Konecta Auditor's final report.

Konecta Auditor audits inbound sales handling through the public contact channels on a company's website.
After the audit, the final report must be sent to leadership.

Company website:
{website_url}

Goal:
- confirm one real leadership recipient with a complete public email address,
- prioritize the highest-seniority recipient available.

Accepted leadership roles:
- CEO
- Founder or Co-founder
- Owner
- Managing Director
- Director General
- General Manager
- President
- Partner
- Socio gerente
- another clearly senior decision-maker only if the evidence is strong

Hard rules:
- use public sources only,
- search broadly across public sources until you either confirm a leadership recipient or exhaust the evidence,
- prefer the official company website, public LinkedIn pages, and public corporate registries,
- also use public press releases, public company profiles, public filings, public association pages, and public directory listings when they help confirm leadership,
- prefer an official company-domain email,
- return a complete valid email address,
- reject the company when only generic sales/support/contact/logistics inboxes are visible without leadership attribution,
- reject the company when the role is ambiguous or low-seniority,
- reject the company when the evidence does not clearly connect the email to leadership.

Deliver a concise research memo that answers:
- was a leadership recipient confirmed or not,
- company name,
- official website,
- recipient name if available,
- recipient role,
- recipient email,
- evidence summary,
- source URLs.
"""

LEADERSHIP_RECIPIENT_EXTRACTION_INSTRUCTIONS = """
Read the research memo and return one leadership-recipient verdict.

Rules:
- `confirmed` must be true only when the memo clearly supports a leadership recipient with a complete valid email.
- Reject generic inboxes unless the memo clearly ties that inbox to a leadership role.
- Reject missing-role or missing-email cases.
- Prefer the highest-seniority role evidenced.
- Keep `source_urls` grounded in the memo.
- Do not invent facts.
"""


class LeadershipRecipientDiscoveryResult(BaseModel):
    """One public leadership-recipient verdict."""

    confirmed: bool = False
    company_name: str | None = None
    official_website: str | None = None
    leadership_recipient_name: str | None = None
    leadership_recipient_role: str | None = None
    leadership_recipient_email: str | None = None
    evidence_summary: str = ""
    source_urls: list[str] = Field(default_factory=list)


class AuditorLeadershipRecipientProgram(Program):
    """Find one public leadership recipient with an attributable email."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or gpt_5_4_mini)

        class LeadershipRecipientSignature(dspy.Signature):
            """Extract one public leadership-recipient verdict from research notes."""

            company_website: str = dspy.InputField(desc="Official website being verified.")
            research_memo: str = dspy.InputField(desc="Research memo with public evidence.")
            result: LeadershipRecipientDiscoveryResult = dspy.OutputField(
                desc="Leadership-recipient verdict for whether the company can receive the final report."
            )

        self.extractor = dspy.Predict(
            LeadershipRecipientSignature.with_instructions(
                LEADERSHIP_RECIPIENT_EXTRACTION_INSTRUCTIONS
            )
        )

    def build_search_prompt(self, website_url: str) -> str:
        """Build the external research prompt."""
        return LEADERSHIP_RECIPIENT_RESEARCH_BRIEF.format(website_url=website_url).strip()

    async def run_research(self, website_url: str) -> str:
        """Run Perplexity pro search and bundle the memo plus citations."""
        response = await pro_search(self.build_search_prompt(website_url))
        payload = extract_response_data(response)
        parts = [
            "## Research memo",
            payload.get("output_text") or "",
        ]

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

    async def extract_result(
        self,
        *,
        website_url: str,
        research_memo: str,
    ) -> LeadershipRecipientDiscoveryResult:
        """Extract one typed verdict from the research memo."""
        prediction = await self.extractor.acall(
            company_website=website_url,
            research_memo=research_memo,
        )
        return self.normalize_result(prediction.result, website_url=website_url)

    def normalize_result(
        self,
        result: LeadershipRecipientDiscoveryResult,
        *,
        website_url: str,
    ) -> LeadershipRecipientDiscoveryResult:
        """Normalize emails/URLs and fail closed when evidence is incomplete."""
        normalized_website = normalize_company_source_url(result.official_website or website_url) or website_url
        normalized_email = normalize_email(result.leadership_recipient_email or "") or None
        normalized_role = (result.leadership_recipient_role or "").strip() or None
        normalized_sources = self.normalize_url_list(result.source_urls, fallback_url=normalized_website)
        confirmed = bool(result.confirmed and normalized_email and normalized_role)

        return LeadershipRecipientDiscoveryResult(
            confirmed=confirmed,
            company_name=(result.company_name or "").strip() or None,
            official_website=normalized_website,
            leadership_recipient_name=(result.leadership_recipient_name or "").strip() or None,
            leadership_recipient_role=normalized_role,
            leadership_recipient_email=normalized_email,
            evidence_summary=" ".join((result.evidence_summary or "").split()),
            source_urls=normalized_sources if confirmed else [],
        )

    def normalize_url_list(self, values: list[str], *, fallback_url: str) -> list[str]:
        """Normalize and dedupe public evidence URLs."""
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

    async def aforward(self, *, website_url: str) -> LeadershipRecipientDiscoveryResult:
        """Run public research and extract the leadership-recipient verdict."""
        normalized_website = normalize_company_source_url(website_url) or website_url.strip()
        research_memo = await self.run_research(normalized_website)
        return await self.extract_result(
            website_url=normalized_website,
            research_memo=research_memo,
        )


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        program = AuditorLeadershipRecipientProgram()
        result = await program.aforward(website_url="https://example.com")
        print(json.dumps(result.model_dump(), indent=2))

    asyncio.run(_main())
