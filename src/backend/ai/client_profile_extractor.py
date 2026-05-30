"""DSPy program for post-conversion client profile extraction."""

from __future__ import annotations

import json
from typing import Any, Literal

import dspy
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import SMART_MODEL


class ClientProfileSourceSnippet(BaseModel):
    """Transcript evidence used by downstream operators and agents."""

    topic: str = ""
    quote: str = Field(default="", max_length=800)
    use_for: str = ""


class ClientProfileObjection(BaseModel):
    """One buyer objection or sales friction point from the conversion call."""

    objection: str = ""
    evidence: str = Field(default="", max_length=800)
    response_angle: str = ""


class ClientProfileSegment(BaseModel):
    """One target segment for campaign planning."""

    name: str = ""
    description: str = ""
    geo: str = ""
    meta_targeting_notes: str = ""
    exclusions: list[str] = Field(default_factory=list)


class ClientProfileAdAngle(BaseModel):
    """One direct-response ad angle grounded in the transcript."""

    hook: str = ""
    problem: str = ""
    desired_outcome: str = ""
    without_objection: str = ""
    evidence: str = Field(default="", max_length=800)


class ClientProfileExtractionResult(BaseModel):
    """Structured client knowledge extracted from a conversion transcript."""

    business_summary: str = Field(default="", max_length=8000)
    offer_summary: str = Field(default="", max_length=8000)
    market_summary: str = Field(default="", max_length=8000)
    objections: list[ClientProfileObjection] = Field(default_factory=list)
    segments: list[ClientProfileSegment] = Field(default_factory=list)
    ad_angles: list[ClientProfileAdAngle] = Field(default_factory=list)
    meta_planning: dict[str, Any] = Field(default_factory=dict)
    delivery_notes: dict[str, Any] = Field(default_factory=dict)
    unresolved_questions: list[str] = Field(default_factory=list)
    source_snippets: list[ClientProfileSourceSnippet] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"

    def to_profile_payload(self) -> dict[str, Any]:
        """Return fields accepted by PlatformClientProfile.upsert."""
        return {
            "business_summary": self.business_summary,
            "offer_summary": self.offer_summary,
            "market_summary": self.market_summary,
            "objections": [item.model_dump(mode="json") for item in self.objections],
            "segments": [item.model_dump(mode="json") for item in self.segments],
            "knowledge": {
                "schema_version": "konecta.client_profile_extraction.v1",
                "ad_angles": [item.model_dump(mode="json") for item in self.ad_angles],
                "meta_planning": self.meta_planning,
                "delivery_notes": self.delivery_notes,
                "unresolved_questions": self.unresolved_questions,
                "source_snippets": [item.model_dump(mode="json") for item in self.source_snippets],
                "confidence": self.confidence,
            },
        }

    def to_meeting_profile_payload(self, *, profile_id: str) -> dict[str, Any]:
        """Return the extraction snapshot stored back on the meeting."""
        payload = self.to_profile_payload()
        return {
            "schema_version": "konecta.client_profile_extraction.v1",
            "profile_id": profile_id,
            "business_summary": payload["business_summary"],
            "offer_summary": payload["offer_summary"],
            "market_summary": payload["market_summary"],
            "objections": payload["objections"],
            "segments": payload["segments"],
            "knowledge": payload["knowledge"],
        }


class ClientProfileExtractorSignature(dspy.Signature):
    """Extract ad-ready client knowledge from a paid-client meeting transcript.

    The output must stay grounded in the transcript. If a required ads, Meta
    publishing, delivery, or client-update fact is missing, put it in
    unresolved_questions instead of inventing it.
    """

    transcript_text: str = dspy.InputField(desc="Conversion call transcript after the client paid or agreed to start.")
    existing_context_json: str = dspy.InputField(desc="Known lead, funnel, meeting, and operator context as JSON.")
    result: ClientProfileExtractionResult = dspy.OutputField(desc="Structured client profile and Meta planning inputs.")


class ClientProfileExtractorProgram(Program):
    """DSPy program that turns conversion transcripts into client profiles."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or SMART_MODEL)
        self.predict = dspy.Predict(ClientProfileExtractorSignature)

    def forward(
        self,
        *,
        transcript_text: str,
        existing_context: dict[str, Any] | None = None,
    ) -> ClientProfileExtractionResult:
        """Run the extraction program."""
        prediction = self.predict(
            transcript_text=str(transcript_text or "").strip()[:50000],
            existing_context_json=json.dumps(existing_context or {}, ensure_ascii=True, default=str),
        )
        return ClientProfileExtractionResult.model_validate(prediction.result)


client_profile_extractor_program = ClientProfileExtractorProgram()


def run_client_profile_extraction(
    *,
    transcript_text: str,
    existing_context: dict[str, Any] | None = None,
    program: ClientProfileExtractorProgram | None = None,
) -> ClientProfileExtractionResult:
    """Extract a client profile from one transcript."""
    runner = program or client_profile_extractor_program
    return runner(transcript_text=transcript_text, existing_context=existing_context)
