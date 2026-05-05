"""Legacy Post-Loom classifiers kept for regression tests and old snapshots.

The active automation uses `ContadoresConversationBotProgram`, which answers
known questions directly and only hands off true unknowns or scheduling details.
"""

from __future__ import annotations

from typing import Literal

import dspy
from pydantic import BaseModel

from backend.base import Program
from backend.config import gpt_5_4_mini


class PostLoomReplyClassificationResult(BaseModel):
    """Structured decision for one post-Loom reply batch."""

    label: Literal["wants_to_proceed", "watched_video_confirmation", "needs_human"]
    reasoning: str


class PostLoomServiceRecapResult(BaseModel):
    """Generated recap message for a lead that only confirmed watching the video."""

    message_text: str


class PostLoomReplyClassifierSignature(dspy.Signature):
    """Classify the lead's reply after the Loom sequence.

    <task>
    Read the full batch of WhatsApp replies received after the Loom video was sent.
    Decide only one of these labels:
    - `wants_to_proceed`
    - `watched_video_confirmation`
    - `needs_human`
    </task>

    <strict_rules>
    - Use `wants_to_proceed` only when the lead clearly confirms interest, says the proposal is clear,
      or clearly asks to continue / schedule / advance.
    - Use `watched_video_confirmation` only when the lead merely confirms they watched or saw the video,
      such as a short "si", "ya lo vi", "lo vi", "ok", or equivalent, and does not ask a
      question, give an objection, request information, provide a date, or clearly ask to advance.
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
    label: Literal["wants_to_proceed", "watched_video_confirmation", "needs_human"] = dspy.OutputField()
    reasoning: str = dspy.OutputField()


class PostLoomReplyClassifierProgram(Program):
    """DSPy program that classifies post-Loom replies."""

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


class PostLoomServiceRecapSignature(dspy.Signature):
    """Write the next WhatsApp message after a simple video-watched confirmation.

    <task>
    The lead only confirmed they watched the sales video. Write the next operator-style WhatsApp
    message that restates what the service does for them and asks for a day to talk.
    </task>

    <inputs>
    - `funnel_id`: niche/funnel slug, for example contadores, abogados, mecanicos, negocios.
    - `funnel_label`: human funnel name.
    - `phone`: lead phone number. Use its country code to infer the country when it is clear.
    - `reply_batch`: what the lead said after the video.
    </inputs>

    <style_rules>
    - Spanish only.
    - Natural Latin American WhatsApp tone.
    - Use usted.
    - Be persuasive but not exaggerated.
    - Write 3 or 4 short paragraphs separated by blank lines.
    - Restate that Konecta helps them get more potential client inquiries directly to WhatsApp.
    - Mention a modern professional website and tailored advertising campaigns.
    - Adapt the niche from the funnel. For contadores say contador/estudio contable. For abogados
      say abogado/estudio juridico. For mecanicos say taller mecanico. For generic negocios say negocio.
    - Adapt the location from the phone country code. If the country is unclear, say "su zona" or "su pais".
    - End by asking what day this week works best for a short call.
    - Do not include a Calendly link.
    - Do not invent results, guarantees, prices, or client counts.
    </style_rules>

    <example>
    Input:
    funnel_id: abogados
    funnel_label: Abogados
    phone: +59175432222
    reply_batch: Si

    Good output:
    Perfecto.
    Nosotros lo que hacemos es ayudarle a conseguir mas consultas de potenciales clientes en Bolivia,
    directo a su WhatsApp.

    Para eso le armamos una pagina web moderna y profesional, y ademas campanas publicitarias enfocadas
    en personas de Bolivia que puedan necesitar sus servicios legales.

    La idea es que usted tenga una presencia mucho mas fuerte y que le lleguen oportunidades reales de
    clientes, sin tener que estar buscando manualmente.

    Para avanzar, lo mejor seria una llamada corta donde le explicamos como se aplicaria a su caso.
    Que dia le queda mejor esta semana?
    </example>
    """

    funnel_id: str = dspy.InputField(desc="Current funnel slug, such as contadores, abogados, mecanicos, negocios.")
    funnel_label: str = dspy.InputField(desc="Human-readable funnel label.")
    phone: str = dspy.InputField(desc="Lead phone number, including country code when available.")
    reply_batch: str = dspy.InputField(desc="Combined lead replies received after the Loom sequence.")
    message_text: str = dspy.OutputField(desc="One WhatsApp message with short paragraphs separated by blank lines.")


class PostLoomServiceRecapProgram(Program):
    """DSPy program that writes the post-video service recap message."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or gpt_5_4_mini)
        self.predict = dspy.Predict(PostLoomServiceRecapSignature)

    async def aforward(
        self,
        *,
        funnel_id: str,
        funnel_label: str,
        phone: str,
        reply_batch: str,
    ) -> PostLoomServiceRecapResult:
        """Generate one recap message for a simple watched-video confirmation."""
        prediction = self.predict(
            funnel_id=funnel_id.strip(),
            funnel_label=funnel_label.strip(),
            phone=phone.strip(),
            reply_batch=reply_batch.strip(),
        )
        return PostLoomServiceRecapResult(message_text=prediction.message_text.strip())
