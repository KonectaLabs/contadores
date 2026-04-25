"""Batch input -> company URLs."""

from __future__ import annotations

import dspy
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import grok_4_1_fast_reasoning

INSTRUCTIONS_FOR_BATCH_COMPANY_URL_EXTRACTOR = """
Read the bundled input and return only the company website URLs that should be audited.

Rules:
- Return only company website URLs grounded in the input.
- Prefer the official company homepage/root URL when the input includes multiple URLs for the same company.
- Do not include duplicates.
- Ignore emails, phone numbers, people names, file links, document links, social profile URLs, messaging links, search result links, and map links.
- Examples of URLs to exclude: LinkedIn company/profile pages, Google search links, maps.google.com links, wa.me links, Facebook pages, Instagram profiles, YouTube links.
- The input may contain noisy extraction from PDFs, CSVs, and docs. Use the surrounding context to decide what is the company website and what is not.
- Do not invent URLs that are not clearly supported by the input.
- If no company website URLs are grounded in the input, return an empty list.
"""


class BatchCompanyUrlResult(BaseModel):
    """Structured URL extraction output for batch scan inputs."""

    urls: list[str] = Field(default_factory=list)


class BatchInputToCompanyUrlsProgram(Program):
    """Extract one list of company URLs from freeform batch input."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm or grok_4_1_fast_reasoning)

        class BatchInputToCompanyUrlsSignature(dspy.Signature):
            """Read one bundled text input and return only company website URLs."""

            bundled_input: str = dspy.InputField(
                desc="Freeform text plus extracted attachment text bundled into one string."
            )
            urls: list[str] = dspy.OutputField(
                desc="Unique list of company website URLs."
            )

        self.extractor = dspy.Predict(
            BatchInputToCompanyUrlsSignature.with_instructions(
                INSTRUCTIONS_FOR_BATCH_COMPANY_URL_EXTRACTOR
            )
        )

    async def aforward(self, bundled_input: str) -> BatchCompanyUrlResult:
        """Extract the final URL list directly from the LLM contract."""
        prediction = await self.extractor.acall(bundled_input=bundled_input)
        return BatchCompanyUrlResult(urls=prediction.urls or [])
