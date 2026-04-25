"""Stage 2: conversation -> next reply."""

from typing import Literal

import dspy
from pydantic import BaseModel, Field

from backend.ai.stage1_url_to_contacts import ContactType
from backend.base import Program
from backend.database import ConversationMessage, normalize_company_industry

DEFAULT_OBJECTIVE = "General sales inquiry"
DEFAULT_INDUSTRY = "unknown"

StrategyPhase = Literal["opening", "context", "probe", "proof", "close"]
AskFamily = Literal["identity_reply", "need_reply", "fit", "pricing", "process", "proof", "timing", "close"]
DecisionReason = Literal[
    "continue",
    "objective_answered",
    "enough_signal",
    "bot_detected",
    "hostile",
    "looping",
    "dead_end",
]


class FirstMessageDraft(BaseModel):
    """Structured first outbound draft for one contact."""

    first_message: str
    subject: str


class ReplyDraft(BaseModel):
    """Structured reply draft for one conversation turn."""

    reply: str


class ConversationTurnResult(BaseModel):
    """Structured Stage 2 turn output."""

    reply: str
    done: bool = False


class ConversationStrategy(BaseModel):
    """Planner output for the next turn."""

    phase: StrategyPhase = "context"
    buyer_setup: str = ""
    next_goal: str = ""
    ask_family: AskFamily = "fit"
    tone_rules: list[str] = Field(default_factory=list)


class ConversationDecision(BaseModel):
    """Decision about whether the automated conversation should continue."""

    continue_conversation: bool = True
    reason: DecisionReason = "continue"


CONVERSATION_STRATEGY_INSTRUCTIONS = """
Plan the next buyer move for an audited seller conversation.

You are not writing the final message. You are deciding the best next move so a separate writer can draft it.

Core principles distilled from strong discovery conversations:
- make it a dialogue, not an interrogation,
- spread questions over the conversation instead of front-loading them,
- ask one high-signal thing at a time,
- let the seller's latest answer/question guide the next move,
- create enough evidence for an audit without dragging the chat.

Use `objective`, `company_context`, `industry`, `channel`, and `conversation`.
Infer the right play from the context. Do not create hard industry playbooks.

Conversation rules:
- exactly one dominant intention for the next turn,
- if the latest seller turn asks who you are or what you need, answer that first instead of repeating your previous question,
- keep the buyer setup vague, human, and non-verifiable,
- allowed buyer setup examples: solo founder, building with a partner, early project, non technical, comparing options,
- forbidden setup claims: real company names, real client names, exact country if sensitive, logos, precise budgets, precise headcount, or anything easily searchable,
- prefer questions that reveal seller quality: fit/recommendation, rough pricing, process, one concrete proof point, timing/scope,
- avoid low-value asks: documents, PDFs, decks, forms, proposals, calendars, availability ping-pong, or stacked questionnaires,
- if the same process question was already pushed recently, choose a different ask family.

Industry examples for inference only:
- software outsourcing: process, communication rhythm, rough pricing, timing, similar case, delivery clarity,
- dealership: availability, recommendation between options, rough range, what they would suggest for a budget,
- language school: level fit, recommended plan, monthly fee range, group vs private recommendation.

Phase guidance:
- opening: no prior transcript yet,
- context: answer a seller question or establish believable buyer context,
- probe: test discovery depth or seller usefulness,
- proof: ask for one concrete example, range, process detail, or recommendation,
- close: no more questions; prepare a short natural exit.

Output contract:
- `phase`: one of opening/context/probe/proof/close,
- `buyer_setup`: short buyer context the writer may imply,
- `next_goal`: one sentence saying what the next message must accomplish,
- `ask_family`: one of identity_reply/need_reply/fit/pricing/process/proof/timing/close,
- `tone_rules`: 2-4 short writing rules.
"""


CONVERSATION_CONTINUATION_INSTRUCTIONS = """
Decide whether this automated buyer conversation should continue.

Use the transcript plus the planned strategy.

Keep the conversation length variable. Do not chase a fixed turn count.
Continue only when one more short buyer turn is likely to produce new diagnostic signal.

Stop when any of these is true:
- the seller already answered the objective well enough,
- the transcript already has enough signal for the audit,
- the seller suspects a bot, automation, glitch, or repeated-script behavior,
- the seller is hostile, explicitly refuses, or makes further progress unrealistic,
- the thread is looping or mirroring previous wording,
- there is no realistic high-signal next move left.

Looping examples:
- same ask repeated again,
- seller repeats the buyer wording back,
- both sides are stuck in clarification without new substance.

Decision rules:
- if you stop, set `continue_conversation=false`,
- if the latest seller turn asks who the buyer is or what they need, that alone is not a reason to stop,
- prefer `objective_answered` when the seller gave the useful answer,
- prefer `enough_signal` when the audit already has enough evidence even if the objective is only partially answered,
- prefer `bot_detected` when the seller implies bot/script/glitch/repetition,
- prefer `hostile` when the seller becomes combative or blocks the interaction,
- prefer `looping` when the transcript is repeating,
- prefer `dead_end` when the seller is not hostile but no useful next move remains.
"""


REPLY_GENERATOR_INSTRUCTIONS = """
Write the next buyer message for this audited seller conversation.

You receive:
- the transcript so far,
- the strategic plan for the next move,
- the continue/stop decision.

If `decision.continue_conversation` is true:
- write one short human message with one dominant intention,
- follow the strategy,
- if the latest seller turn asks who you are or what you need, answer that first in a vague human way before any follow-up,
- keep the buyer context believable but non-verifiable,
- allowed vague identity patterns: "somos yo y mi socio", "estamos empezando", "no somos tecnicos", "estamos mirando opciones",
- do not invent searchable company names, real clients, exact countries, logos, or concrete numbers not provided in context,
- ask at most one question,
- do not repeat the same process question twice in a row,
- do not ask for docs, PDFs, decks, brochures, forms, proposals, attachments, emails, meetings, demos, agenda, slots, timezone, or calendar coordination.

If `decision.continue_conversation` is false:
- write one short closing message,
- no new questions,
- no new asks,
- sound natural and brief,
- accept the stop reason and exit cleanly.

Style rules:
- 1-2 short sentences,
- human, casual, imperfect, not corporate,
- if `target_language` is provided, write in that language,
- if the language is Spanish, default to lowercase, do not use opening ¿ or ¡, and keep accents light when the sentence still reads naturally,
- no markdown, no bullets, no signatures, no role labels.

Audit-quality rules:
- the best message is a dialogue move, not a checklist,
- do not bombard the seller with multi-part questions,
- ask only for things that help evaluate seller usefulness, clarity, judgment, and momentum,
- if the seller already gave the answer, close instead of squeezing more.

Return only the final buyer message in `draft.reply`.
"""


FIRST_EMAIL_MESSAGE_INSTRUCTIONS = """
Write the first freeform outreach email body for the audited buyer persona.

This applies to email only. WhatsApp intro templates are handled elsewhere.

Use the provided strategy as the opening plan.

Goals:
- sound like one real person reaching out,
- create believable buyer context without using searchable claims,
- ask one narrow, useful thing,
- start a thread that can reveal seller quality quickly.

Rules:
- 1-2 short sentences,
- one dominant ask only,
- the buyer setup may be vague and non-verifiable: small team, early project, with a partner, not technical, comparing options,
- do not invent a real company name, real client, exact country, exact budget, or other searchable facts,
- do not ask for documents, decks, forms, proposals, attachments, calls, demos, or meeting logistics,
- do not sound polished, corporate, or like a template,
- avoid filler like "Espero que estes bien", "Queria consultarte", or other canned intros unless the wording still feels natural,
- if `target_language` is Spanish, bias toward lowercase, no opening ¿ or ¡, and light accents when natural.

Subject rules:
- short and plain,
- human-sounding,
- non-salesy,
- aligned with the body,
- no clickbait and no formal boilerplate.

Return a typed `draft` with `first_message` and `subject`.
"""


class ConversationStrategySignature(dspy.Signature):
    """Return the next-turn strategy for one conversation."""

    objective: str = dspy.InputField(desc="Buyer objective for the audited thread.")
    company_context: str = dspy.InputField(desc="Optional company context for grounding.")
    industry: str = dspy.InputField(desc="Normalized company industry slug.")
    channel: str = dspy.InputField(desc="Current channel: email or whatsapp.")
    conversation: str = dspy.InputField(desc="Role-tagged transcript so far; empty means opening turn.")
    strategy: ConversationStrategy = dspy.OutputField(desc="Structured plan for the next move.")


class ConversationContinuationSignature(dspy.Signature):
    """Return whether the conversation should continue."""

    objective: str = dspy.InputField(desc="Buyer objective for the audited thread.")
    company_context: str = dspy.InputField(desc="Optional company context for grounding.")
    industry: str = dspy.InputField(desc="Normalized company industry slug.")
    channel: str = dspy.InputField(desc="Current channel: email or whatsapp.")
    conversation: str = dspy.InputField(desc="Role-tagged transcript so far.")
    strategy: ConversationStrategy = dspy.InputField(desc="Structured plan for the next move.")
    decision: ConversationDecision = dspy.OutputField(desc="Continue-or-stop decision with reason.")


class ReplyGeneratorSignature(dspy.Signature):
    """Return the next buyer reply draft."""

    objective: str = dspy.InputField(desc="Buyer objective for the audited thread.")
    company_context: str = dspy.InputField(desc="Optional company context for grounding.")
    industry: str = dspy.InputField(desc="Normalized company industry slug.")
    channel: str = dspy.InputField(desc="Current channel: email or whatsapp.")
    conversation: str = dspy.InputField(desc="Role-tagged transcript so far.")
    strategy: ConversationStrategy = dspy.InputField(desc="Structured plan for the next move.")
    decision: ConversationDecision = dspy.InputField(desc="Continue-or-stop decision with reason.")
    target_language: str | None = dspy.InputField(
        desc="Optional target language code. If missing, infer from the transcript."
    )
    draft: ReplyDraft = dspy.OutputField(desc="Typed buyer reply draft.")


class FirstMessageSignature(dspy.Signature):
    """Return the first email body and subject."""

    objective: str = dspy.InputField(desc="Buyer objective for the audited thread.")
    company_context: str = dspy.InputField(desc="Optional company context for grounding.")
    industry: str = dspy.InputField(desc="Normalized company industry slug.")
    channel: str = dspy.InputField(desc="Current channel: email or whatsapp.")
    strategy: ConversationStrategy = dspy.InputField(desc="Structured opening strategy.")
    target_language: str | None = dspy.InputField(desc="Optional target language code.")
    draft: FirstMessageDraft = dspy.OutputField(desc="Typed first-message draft with subject.")


def build_conversation_text(conversation: list[ConversationMessage] | str | None) -> str:
    """Build a role-tagged transcript from conversation objects."""
    if isinstance(conversation, str):
        return conversation.strip()
    if not conversation:
        return ""
    return "\n".join(
        f"{'auditor' if message.from_me else 'sales_agent'}: {message.text}"
        for message in conversation
    )


def resolve_objective(objective: str | None) -> str:
    """Resolve objective to a stable default when not provided."""
    normalized = (objective or "").strip()
    return normalized or DEFAULT_OBJECTIVE


def resolve_company_context(company_context: str | None) -> str:
    """Resolve optional company context to a stable string."""
    return (company_context or "").strip()


def resolve_industry(industry: str | None) -> str:
    """Resolve industry slug to a stable default."""
    normalized = normalize_company_industry(industry)
    return normalized or DEFAULT_INDUSTRY


def resolve_channel(channel: ContactType | str | None) -> str:
    """Resolve channel to one of the supported Stage 2 values."""
    raw_value = channel.value if isinstance(channel, ContactType) else (channel or "")
    normalized = str(raw_value).strip().lower()
    if normalized in {ContactType.EMAIL.value, ContactType.WHATSAPP.value}:
        return normalized
    return ContactType.EMAIL.value


class ConversationStrategyProgram(Program):
    """Plan the next conversational move."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm)
        signature = ConversationStrategySignature.with_instructions(CONVERSATION_STRATEGY_INSTRUCTIONS)
        self.planner = dspy.ChainOfThought(signature)

    async def aforward(
        self,
        *,
        objective: str | None,
        company_context: str | None = None,
        industry: str | None = None,
        channel: ContactType | str | None = None,
        conversation: list[ConversationMessage] | str | None = None,
    ) -> ConversationStrategy:
        """Plan the next turn from the current transcript and context."""
        prediction = await self.planner.acall(
            objective=resolve_objective(objective),
            company_context=resolve_company_context(company_context),
            industry=resolve_industry(industry),
            channel=resolve_channel(channel),
            conversation=build_conversation_text(conversation),
        )
        return prediction.strategy


class ConversationContinuationProgram(Program):
    """Decide whether the conversation should continue."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm)
        signature = ConversationContinuationSignature.with_instructions(CONVERSATION_CONTINUATION_INSTRUCTIONS)
        self.decider = dspy.ChainOfThought(signature)

    async def aforward(
        self,
        *,
        objective: str | None,
        company_context: str | None = None,
        industry: str | None = None,
        channel: ContactType | str | None = None,
        conversation: list[ConversationMessage] | str | None = None,
        strategy: ConversationStrategy,
    ) -> ConversationDecision:
        """Decide whether one more automated turn is worthwhile."""
        prediction = await self.decider.acall(
            objective=resolve_objective(objective),
            company_context=resolve_company_context(company_context),
            industry=resolve_industry(industry),
            channel=resolve_channel(channel),
            conversation=build_conversation_text(conversation),
            strategy=strategy,
        )
        return prediction.decision


class ReplyGeneratorProgram(Program):
    """Write the next buyer message from a strategy and a decision."""

    def __init__(self, lm: dspy.LM = None):
        super().__init__(lm=lm)
        signature = ReplyGeneratorSignature.with_instructions(REPLY_GENERATOR_INSTRUCTIONS)
        self.generator = dspy.ChainOfThought(signature)

    async def aforward(
        self,
        *,
        objective: str | None,
        company_context: str | None = None,
        industry: str | None = None,
        channel: ContactType | str | None = None,
        conversation: list[ConversationMessage] | str | None = None,
        strategy: ConversationStrategy,
        decision: ConversationDecision,
        target_language: str | None = None,
    ) -> ReplyDraft:
        """Generate the next buyer reply."""
        prediction = await self.generator.acall(
            objective=resolve_objective(objective),
            company_context=resolve_company_context(company_context),
            industry=resolve_industry(industry),
            channel=resolve_channel(channel),
            conversation=build_conversation_text(conversation),
            strategy=strategy,
            decision=decision,
            target_language=target_language,
        )
        return ReplyDraft(reply=prediction.draft.reply.strip())


class FirstMessageProgram(Program):
    """Generate the first auditor message to initiate a conversation."""

    def __init__(
        self,
        lm: dspy.LM = None,
        strategy_program: ConversationStrategyProgram | None = None,
    ):
        super().__init__(lm=lm)
        self.strategy_program = strategy_program or ConversationStrategyProgram(lm=self.lm)
        signature = FirstMessageSignature.with_instructions(FIRST_EMAIL_MESSAGE_INSTRUCTIONS)
        self.generator = dspy.ChainOfThought(signature)

    async def aforward(
        self,
        objective: str | None,
        contact_type: ContactType,
        company_context: str | None = None,
        target_language: str | None = None,
        industry: str | None = None,
    ) -> FirstMessageDraft:
        """Generate the first message from objective, channel, and company context."""
        strategy = await self.strategy_program.aforward(
            objective=objective,
            company_context=company_context,
            industry=industry,
            channel=contact_type,
            conversation=[],
        )
        prediction = await self.generator.acall(
            objective=resolve_objective(objective),
            company_context=resolve_company_context(company_context),
            industry=resolve_industry(industry),
            channel=resolve_channel(contact_type),
            strategy=strategy,
            target_language=target_language,
        )
        return FirstMessageDraft(
            first_message=prediction.draft.first_message.strip(),
            subject=prediction.draft.subject.strip(),
        )


class ContactConversationProgram(Program):
    """Stage 2 program orchestrating strategy, continuation, and reply generation."""

    def __init__(
        self,
        lm: dspy.LM = None,
        strategy_program: ConversationStrategyProgram | None = None,
        continuation_program: ConversationContinuationProgram | None = None,
        reply_generator: ReplyGeneratorProgram | None = None,
    ):
        super().__init__(lm=lm)
        self.strategy_program = strategy_program or ConversationStrategyProgram(lm=self.lm)
        self.continuation_program = continuation_program or ConversationContinuationProgram(lm=self.lm)
        self.reply_generator = reply_generator or ReplyGeneratorProgram(lm=self.lm)

    async def aforward(
        self,
        conversation: list[ConversationMessage],
        objective: str | None,
        company_context: str | None = None,
        target_language: str | None = None,
        industry: str | None = None,
        channel: ContactType | str | None = None,
    ) -> ConversationTurnResult:
        """Generate a single reply for the current conversation turn."""
        resolved_channel = resolve_channel(channel)
        strategy = await self.strategy_program.aforward(
            objective=objective,
            company_context=company_context,
            industry=industry,
            channel=resolved_channel,
            conversation=conversation,
        )
        decision = await self.continuation_program.aforward(
            objective=objective,
            company_context=company_context,
            industry=industry,
            channel=resolved_channel,
            conversation=conversation,
            strategy=strategy,
        )
        draft = await self.reply_generator.aforward(
            objective=objective,
            company_context=company_context,
            industry=industry,
            channel=resolved_channel,
            conversation=conversation,
            strategy=strategy,
            decision=decision,
            target_language=target_language,
        )
        return ConversationTurnResult(
            reply=draft.reply.strip(),
            done=not decision.continue_conversation,
        )
