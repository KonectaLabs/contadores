"""Binary post-Loom reply classifier for Contadores automation."""

from __future__ import annotations

from typing import Literal

import dspy
from pydantic import BaseModel

from backend.base import Program
from backend.config import gpt_5_4_mini


class PostLoomReplyClassificationResult(BaseModel):
    """Structured binary decision for one post-Loom reply batch."""

    label: Literal["wants_to_proceed", "needs_human"]
    reasoning: str


class PostLoomReplyClassifierSignature(dspy.Signature):
    """Classify whether the lead clearly wants to proceed after the Loom sequence.

    <task>
    Read the full batch of WhatsApp replies received after the Loom video was sent.
    Decide only one of these labels:
    - `wants_to_proceed`
    - `needs_human`
    </task>

    <strict_rules>
    - Use `wants_to_proceed` only when the lead clearly confirms interest, says the proposal is clear,
      or clearly asks to continue / schedule / advance.
    - Any question, objection, hesitation, ambiguity, confusion, price concern, request for clarification,
      negative reply, off-topic reply, or mixed signal must be `needs_human`.
    - If there is any doubt, choose `needs_human`.
    </strict_rules>

    <output>
    Return:
    - `label`: the binary label
    - `reasoning`: one short operator-facing reason in Spanish
    </output>
    """

    loom_context: str = dspy.InputField(desc="Short description of the flow and what was already sent.")
    reply_batch: str = dspy.InputField(desc="Combined lead replies received after the Loom sequence.")
    label: Literal["wants_to_proceed", "needs_human"] = dspy.OutputField()
    reasoning: str = dspy.OutputField()


class PostLoomReplyClassifierProgram(Program):
    """DSPy program that classifies post-Loom replies into proceed vs human review."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or gpt_5_4_mini)
        self.predict = dspy.Predict(PostLoomReplyClassifierSignature)

    async def aforward(
        self,
        *,
        loom_context: str,
        reply_batch: str,
    ) -> PostLoomReplyClassificationResult:
        """Run the binary classifier for one lead reply batch."""
        prediction = self.predict(
            loom_context=loom_context.strip(),
            reply_batch=reply_batch.strip(),
        )
        return PostLoomReplyClassificationResult(
            label=prediction.label,
            reasoning=prediction.reasoning,
        )
