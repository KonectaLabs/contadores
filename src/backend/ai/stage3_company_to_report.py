"""Stage 3: company info + language -> synthesized expert knowledge + structured report."""

from __future__ import annotations

import dspy
from pydantic import BaseModel, Field
from typing import Literal

from backend.base import Program
from backend.database import Company, CompanyLLMInfo


class ContactObjectiveAssessment(BaseModel):
    """Structured seller evaluation against one contact objective."""

    contact_value: str
    contact_type: str
    objective: str
    goal_status: Literal["achieved", "partial", "not_achieved", "unknown"]
    goal_assessment: str
    seller_assessment: str


class CompanyReport(BaseModel):
    """Final structured report artifact persisted by prepare-report."""

    company_info: CompanyLLMInfo
    language: str
    experts_knowledge: str
    contact_assessments: list[ContactObjectiveAssessment] = Field(default_factory=list)
    report_text: str


class CompanyReportProgram(Program):
    """Build one structured Stage 3 report from company context and language."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm)

        class ExpertCritiqueSignature(dspy.Signature):
            """Write one leadership-ready sales audit report from structured evidence.

            <role>
            You are a strict commercial auditor writing for founders/leadership.
            Prioritize diagnostic clarity, business impact, and actionable guidance.
            Audit seller-side commercial execution only.
            </role>

            <objective>
            Generate one complete report using:
            - `company_info`: company context + contacts + full conversations + contact stats.
            - each contact may include a concrete objective and whether the automated buyer stopped after resolving it.
            </objective>

            <input_interpretation>
            Treat `company_info` as the source of truth for factual evidence.
            Contact-level stats are part of the evidence, not optional decoration.
            Buyer/potential-customer/bot-authored turns are test stimuli and context, not the object of evaluation.
            </input_interpretation>

            <analysis_method>
            1) Evaluate each contact thread independently, focusing on seller behavior triggered by the inquiry.
            2) Detect cross-thread patterns (systemic strengths/gaps).
            3) Synthesize what recognized sales/conversion experts would critique for this exact evidence.
            4) Write that synthesis into `experts_knowledge`.
            5) Map findings to that synthesized expert criteria and convert into prioritized actions.
            </analysis_method>

            <evidence_rules>
            - Ground claims in concrete seller behavior (what the seller asked, answered, skipped, delayed, escalated, or failed to do).
            - Reference evidence in plain language (no URL citations, no bibliography).
            - Distinguish observed facts vs. inferred interpretation.
            - Use buyer/bot messages only to explain the opportunity the seller received or missed; never praise, blame, critique, or rewrite the buyer/bot message itself.
            </evidence_rules>

            <required_coverage>
            Cover at minimum:
            - seller discovery depth and question quality,
            - seller clarity of value communication,
            - seller objection handling quality,
            - seller momentum/progression toward next steps,
            - seller follow-up discipline and responsiveness patterns,
            - whether the seller helped the buyer achieve the stated objective for each contact.
            </required_coverage>

            <report_structure>
            Use clear section headings in {language}. Include:
            - Executive summary.
            - What is working (strengths).
            - Critical gaps and risks.
            - Contact-level critique of seller performance (brief per contact/channel), explicitly including:
              - Objective tested
              - Goal result
              - Seller usefulness/clarity/speed/commercial handling
            - Prioritized action plan (immediate and short-term).
            - Suggested seller-message improvements/examples.
            </report_structure>

            <prioritization_policy>
            Prioritize by expected business impact and urgency.
            Recommend few high-leverage actions over many low-value tips.
            </prioritization_policy>

            <edge_cases>
            - If evidence volume is low, state confidence limits explicitly.
            - If threads are one-sided/unanswered, diagnose the seller non-response or missing coverage, not the buyer prompt.
            - Never fabricate missing transcript details.
            </edge_cases>

            <language_rules>
            - Write all narrative text in {language}.
            - Keep technical names/brands as needed.
            </language_rules>

            <style_rules>
            - Executive, direct, specific.
            - Avoid motivational fluff and generic consulting clichés.
            - Prefer concrete recommendations with implementation intent.
            </style_rules>

            <contact_objective_assessment_contract>
            Also return one structured assessment per contact in `contact_assessments`.

            Rules:
            - include exactly one assessment per contact in `company_info.contacts`,
            - copy the contact's `objective` when present,
            - if objective is missing, use a short fallback based on the conversation context,
            - `goal_status` must be one of: achieved, partial, not_achieved, unknown,
            - `goal_assessment` must answer whether the seller helped resolve the buyer objective,
            - `seller_assessment` must evaluate seller usefulness, clarity, speed, and commercial judgment.
            - keep each assessment concise and grounded in transcript evidence.
            </contact_objective_assessment_contract>

            <forbidden>
            - No JSON output.
            - No XML output.
            - No raw citations list or links section.
            - Do not critique, score, or improve buyer/bot-authored messages except as neutral context for seller evaluation.
            </forbidden>

            <output_contract>
            Return both:
            - `experts_knowledge`: concise expert-criteria synthesis derived from company evidence.
            - `contact_assessments`: structured per-contact objective evaluations.
            - `report_text`: one complete leadership-ready free-form report grounded in evidence.
            </output_contract>
            """

            language: str = dspy.InputField(desc="Target report language. All output must be in this language")
            company_info: CompanyLLMInfo = dspy.InputField(
                desc="Company context with contacts, stats, and conversations"
            )
            experts_knowledge: str = dspy.OutputField(
                desc="Synthesized expert criteria in target language, derived from conversation + company context"
            )
            contact_assessments: list[ContactObjectiveAssessment] = dspy.OutputField(
                desc=(
                    "One structured assessment per contact covering the objective, whether it was achieved, and how "
                    "the seller performed against that objective"
                )
            )
            report_text: str = dspy.OutputField(desc="Complete final report in target language")

        self.extractor = dspy.ChainOfThought(ExpertCritiqueSignature)

    async def aforward(
        self,
        company: Company,
        *,
        language: str,
        include_archived_contacts: bool = False,
    ) -> CompanyReport:
        """Build one structured report payload for one company."""
        company_info = company.to_llm_info(include_archived=include_archived_contacts)

        critique = await self.extractor.acall(
            language=language,
            company_info=company_info,
        )

        return CompanyReport(
            company_info=company_info,
            language=language,
            experts_knowledge=critique.experts_knowledge,
            contact_assessments=critique.contact_assessments,
            report_text=critique.report_text,
        )
