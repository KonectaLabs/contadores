"""Stage 4: Stage 3 structured report -> ReportDocumentModel (LLM-first, typed output)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import dspy
from dspy.adapters.json_adapter import JSONAdapter

from backend.ai.stage3_company_to_report import CompanyReport
from backend.base import Program
from backend.config import SMART_MODEL
from backend.database import Company
from backend.report_pdf import ReportDocumentModel, build_vector_pdf


class ReportPdfModelProgram(Program):
    """Convert one Stage 3 report payload into one render-ready PDF model."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm or SMART_MODEL)
        self._stage4_adapter = JSONAdapter()

        class ReportToPdfModelSignature(dspy.Signature):
            """Transform one sales-audit Stage 3 payload into one strict PDF Pydantic model.

            <role>
            You are a principal audit editor and structured data architect.
            Your job is to convert report evidence into one complete structured object that validates
            against the PDF model contract used by the renderer.
            The report evaluates seller behavior only; buyer/potential-customer/bot messages are context, not the object of critique.
            </role>

            <objective>
            Input is Stage 3 report payload with exactly this business payload:
            - company_info
            - experts_knowledge
            - language
            - report_text

            Output must be one complete `pdf_model` value that validates as ReportDocumentModel.
            </objective>

            <critical_contract>
            - Do not output HTML.
            - Do not output markdown.
            - Do not output explanations.
            - Fill only the `pdf_model` field.
            - No extra keys outside the target model.
            </critical_contract>

            <schema_target>
            ReportDocumentModel fields to output:
            - hero: {
                company: str,
                url: str,
                line_1: str,
                line_2_a: str,
                line_2_b: str,
                context: str,
                impact: str,
                auth: str
              }
            - risk_level_label: str
            - risk_badge_label: str
            - risk_badge_kind: str
            - risk_segments: list[{label: str, color: str, weight: float>0}]
            - contacts: list[{value: str, meta: str}]
            - threads: list[{
                title: str,
                channel: str,
                objective_text: str,
                status_kind: "critical" | "warn" | "ok" | "neutral",
                status_text: str,
                messages: list[{
                    side: "buyer"|"seller",
                    badge: str,
                    timestamp: str,
                    text: str,
                    callout: {title: str, body: str} | null
                }],
                insight_title: str,
                insight_blocks: list[{label: str, text: str}],
                quote: {quote: str, attribution: str, observed: str} | null
              }]
            - thread_layouts: list
            - message_layouts: list
            - insight_layouts: list
            - conclusion_lines: list
            - conclusion_text: str | null
            - quote_line_overrides: dict
            </schema_target>

            <data_mapping_rules>
            1) Use report as source of truth.
            2) hero synthesis:
               - hero.company and hero.url come directly from company_info (company_name/source_url normalized to compact host for url).
               - hero.line_1, hero.line_2_a, hero.line_2_b, hero.context, hero.impact, hero.auth are editorial synthesis from report_text + experts_knowledge.
               - Keep concise, executive, evidence-first style.
               - Summaries must diagnose seller-side commercial execution only.
            3) contacts:
               - derive from company_info.contacts.
               - contacts[i].value = contact_value.
               - contacts[i].meta = humanized string combining channel + meaningful note/context when present.
               - Example style: "Email · Note in source: \"es un papanatas\"".
            4) threads:
               - create exactly one thread per contact.
               - thread.title = contact_value.
               - channel humanized from contact_type (e.g., email -> Email, whatsapp -> WhatsApp, linkedin -> LinkedIn).
               - thread.objective_text = the contact objective being tested for that thread.
               - status_kind/status_text inferred from evidence (stats + conversation) without adding new facts.
               - status_kind/status_text must reflect seller performance only.
               - status_kind MUST be one of: critical, warn, ok, neutral.
               - use status_text as free label, but keep status_kind in that enum so renderer applies semantic color.
               - status language should stay short and renderer-friendly.
               - balance policy for status_kind:
                 a) evaluate each thread independently using its own evidence.
                 b) do NOT default all threads to the same severity.
                 c) assign `ok` only when seller replies are timely and trust-preserving.
                 d) assign `warn` when there is partial quality (e.g., delayed, incomplete, or mixed trust signals).
                 e) assign `critical` when there is no response, openly evasive/hostile behavior, or severe trust break.
                 f) use `neutral` only when evidence is truly insufficient/ambiguous.
               - across all threads in one report, prefer calibrated differentiation: if evidence differs between threads, status_kind should differ too.
            5) messages mapping:
               - from_me=true -> side="buyer", badge="Potential customer".
               - from_me=false -> side="seller", badge=contact_value.
               - timestamp format must be exactly "YYYY-MM-DD HH:MM".
               - sanitize seller message noise (email signature/footer/protocol artifacts) while preserving commercial meaning.
               - preserve chronological narrative and evidence meaning.
               - buyer messages must keep `callout=null`; never attach evaluative commentary to buyer/bot turns.
            6) semantic enrichments:
               - callout, insight_title, insight_blocks, quote, conclusion_text are semantic synthesis from report_text + experts_knowledge + thread evidence.
               - all diagnostics must target seller behavior only; buyer/bot turns can be mentioned only as neutral context or missed opportunity.
               - only seller messages may receive callouts.
               - insight_title and insight_blocks must critique seller performance, not buyer wording.
               - quote must quote seller wording only; if there is no meaningful seller response, set quote=null.
               - if no seller response in a thread, quote can be null and callouts can be empty.
               - use `report.contact_assessments` as the source of truth for the objective evaluation.
               - the first insight block of every thread must summarize the objective result:
                 label style example: "Objective result"
                 text style example: "Partial. The seller gave pricing but did not clearly recommend the better option."
               - additional insight blocks may cover discovery, clarity, responsiveness, trust, or momentum.
            7) risk strip contract:
               - always output exactly 3 segments in this fixed order:
                 a) Reply handling (color="good")
                 b) Trust signals (color="warn")
                 c) Commercial momentum (color="bad")
               - only labels and weights are data-driven.
               - weight defines the proportional width in the renderer and must be > 0.
               - risk_badge_label and risk_badge_kind must summarize overall risk coherently.
            8) layout contract:
               - This stage outputs content model only, not fixed layout geometry.
               - Set thread_layouts, message_layouts, insight_layouts, conclusion_lines to empty lists.
               - Set quote_line_overrides to {}.
               - Keep renderer-adaptive flow by not inventing manual coordinates.
            </data_mapping_rules>

            <quality_bar>
            - No placeholders like "None", "null" as strings, or "N/A" unless they are true business text.
            - No fabricated details.
            - Keep wording compact and high-signal.
            - Keep thread-level diagnostics grounded in observed transcript behavior.
            - Never criticize, praise, score, or rewrite buyer/bot-authored messages.
            </quality_bar>

            <output_format>
            Return only `pdf_model` with valid ReportDocumentModel content.
            </output_format>
            """

            report: CompanyReport = dspy.InputField(
                desc="Stage 3 structured report with company_info, experts_knowledge, language, report_text"
            )
            pdf_model: ReportDocumentModel = dspy.OutputField(
                desc="Render-ready PDF content model for the report renderer"
            )

        self.generator = dspy.ChainOfThought(ReportToPdfModelSignature)

    async def aforward(self, *, report: CompanyReport) -> ReportDocumentModel:
        """Generate one ReportDocumentModel directly from Stage 3 report payload."""
        # Stage 4 output reuses nested models in multiple fields; BAMLAdapter treats that as recursive.
        # Force JSONAdapter only for this call to preserve global adapter defaults in other stages.
        with dspy.context(adapter=self._stage4_adapter):
            prediction = await self.generator.acall(report=report)
        return prediction.pdf_model




if __name__ == "__main__":
    def find_konecta_company() -> Company | None:
        """Find latest Konecta company row from DB."""
        for company in Company.list_recent(limit=300):
            haystack = f"{company.company_name} {company.source_url}".lower()
            if "konecta" in haystack:
                return company
        return None


    async def run_konecta_demo(output_pdf: Path = Path("report_stage4_konectalabs.pdf")) -> Path:
        """Demo pipeline: report snapshot -> Stage 4 PDF model -> persist JSON -> render PDF."""
        company = find_konecta_company()
        if not company:
            raise RuntimeError("Konecta company not found in database")

        report = Company.get_report_snapshot(company.id)
        if not report:
            raise RuntimeError("Konecta report snapshot not found. Run /prepare-report first.")

        stage4 = ReportPdfModelProgram(lm=SMART_MODEL)
        try:
            pdf_model = await stage4.aforward(report=report)
            Company.update_report_pdf_model(company.id, pdf_model.model_dump_json(by_alias=True))
        except Exception:
            pdf_model = Company.get_report_pdf_model(company.id)
            if not pdf_model:
                raise
        pdf_bytes = build_vector_pdf(pdf_model, strict_layout_fit=False)
        output_pdf.write_bytes(pdf_bytes)
        return output_pdf


    generated = asyncio.run(run_konecta_demo())
    print(f"Generated PDF: {generated.resolve()}")
