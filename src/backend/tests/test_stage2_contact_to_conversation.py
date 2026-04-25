"""Tests for Stage 2 conversation planning and orchestration."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from backend.ai.stage1_url_to_contacts import ContactType
from backend.database import ConversationMessage

STAGE2_MODULE_PATH = Path(__file__).resolve().parents[1] / "ai" / "stage2_contact_to_conversation.py"
STAGE2_SPEC = importlib.util.spec_from_file_location(
    "isolated_stage2_contact_to_conversation",
    STAGE2_MODULE_PATH,
)
if STAGE2_SPEC is None or STAGE2_SPEC.loader is None:
    raise RuntimeError(f"Failed loading Stage 2 module from {STAGE2_MODULE_PATH}")
STAGE2_MODULE = importlib.util.module_from_spec(STAGE2_SPEC)
STAGE2_SPEC.loader.exec_module(STAGE2_MODULE)

CONVERSATION_STRATEGY_INSTRUCTIONS = STAGE2_MODULE.CONVERSATION_STRATEGY_INSTRUCTIONS
FIRST_EMAIL_MESSAGE_INSTRUCTIONS = STAGE2_MODULE.FIRST_EMAIL_MESSAGE_INSTRUCTIONS
REPLY_GENERATOR_INSTRUCTIONS = STAGE2_MODULE.REPLY_GENERATOR_INSTRUCTIONS
ContactConversationProgram = STAGE2_MODULE.ContactConversationProgram
ConversationDecision = STAGE2_MODULE.ConversationDecision
ConversationStrategy = STAGE2_MODULE.ConversationStrategy
ConversationTurnResult = STAGE2_MODULE.ConversationTurnResult
FirstMessageDraft = STAGE2_MODULE.FirstMessageDraft
FirstMessageProgram = STAGE2_MODULE.FirstMessageProgram


def test_stage2_prompt_rules_cover_identity_first_and_off_channel_guards() -> None:
    assert "asks who you are or what you need" in CONVERSATION_STRATEGY_INSTRUCTIONS
    assert "exactly one dominant intention" in CONVERSATION_STRATEGY_INSTRUCTIONS
    assert "documents, PDFs, decks, forms, proposals" in CONVERSATION_STRATEGY_INSTRUCTIONS
    assert "software outsourcing" in CONVERSATION_STRATEGY_INSTRUCTIONS
    assert "dealership" in CONVERSATION_STRATEGY_INSTRUCTIONS
    assert "language school" in CONVERSATION_STRATEGY_INSTRUCTIONS


def test_stage2_reply_rules_cover_spanish_style_and_human_vagueness() -> None:
    assert 'somos yo y mi socio' in REPLY_GENERATOR_INSTRUCTIONS
    assert "do not invent searchable company names" in REPLY_GENERATOR_INSTRUCTIONS
    assert "do not use opening ¿ or ¡" in REPLY_GENERATOR_INSTRUCTIONS
    assert "no new questions" in REPLY_GENERATOR_INSTRUCTIONS
    assert "do not ask for docs, PDFs, decks" in REPLY_GENERATOR_INSTRUCTIONS


def test_first_email_prompt_rules_cover_plain_human_email_opening() -> None:
    assert "WhatsApp intro templates are handled elsewhere" in FIRST_EMAIL_MESSAGE_INSTRUCTIONS
    assert 'Espero que estes bien' in FIRST_EMAIL_MESSAGE_INSTRUCTIONS
    assert "one dominant ask only" in FIRST_EMAIL_MESSAGE_INSTRUCTIONS
    assert "do not invent a real company name" in FIRST_EMAIL_MESSAGE_INSTRUCTIONS


def test_contact_conversation_program_orchestrates_strategy_decision_and_reply() -> None:
    strategy_calls: list[dict[str, object]] = []
    decision_calls: list[dict[str, object]] = []
    reply_calls: list[dict[str, object]] = []

    class FakeStrategyProgram:
        async def aforward(self, **kwargs) -> ConversationStrategy:
            strategy_calls.append(kwargs)
            return ConversationStrategy(
                phase="context",
                buyer_setup="somos yo y mi socio",
                next_goal="answer who we are and ask one concrete thing",
                ask_family="identity_reply",
                tone_rules=["lowercase", "one question"],
            )

    class FakeContinuationProgram:
        async def aforward(self, **kwargs) -> ConversationDecision:
            decision_calls.append(kwargs)
            return ConversationDecision(
                continue_conversation=True,
                reason="continue",
            )

    class FakeReplyGenerator:
        async def aforward(self, **kwargs):
            reply_calls.append(kwargs)
            return SimpleNamespace(reply=" no somos una empresa como tal, estamos arrancando... ")

    program = ContactConversationProgram(
        strategy_program=FakeStrategyProgram(),
        continuation_program=FakeContinuationProgram(),
        reply_generator=FakeReplyGenerator(),
    )

    result = asyncio.run(
        program.aforward(
            conversation=[
                ConversationMessage(from_me=True, text="hola"),
                ConversationMessage(from_me=False, text="que necesitais?"),
            ],
            objective="Ask about process and rough pricing",
            company_context="software outsourcing team for europe",
            target_language="es",
            industry="computer_programming_consultancy",
            channel="email",
        )
    )

    assert result == ConversationTurnResult(
        reply="no somos una empresa como tal, estamos arrancando...",
        done=False,
    )
    assert strategy_calls[0]["industry"] == "computer_programming_consultancy"
    assert strategy_calls[0]["channel"] == "email"
    assert decision_calls[0]["strategy"].ask_family == "identity_reply"
    assert reply_calls[0]["decision"].reason == "continue"
    assert reply_calls[0]["target_language"] == "es"


def test_contact_conversation_program_marks_done_when_decision_stops_thread() -> None:
    class FakeStrategyProgram:
        async def aforward(self, **kwargs) -> ConversationStrategy:
            del kwargs
            return ConversationStrategy(
                phase="close",
                buyer_setup="",
                next_goal="close the conversation naturally",
                ask_family="close",
                tone_rules=["brief"],
            )

    class FakeContinuationProgram:
        async def aforward(self, **kwargs) -> ConversationDecision:
            del kwargs
            return ConversationDecision(
                continue_conversation=False,
                reason="bot_detected",
            )

    class FakeReplyGenerator:
        async def aforward(self, **kwargs):
            del kwargs
            return SimpleNamespace(reply=" gracias igual, lo dejo aca ")

    program = ContactConversationProgram(
        strategy_program=FakeStrategyProgram(),
        continuation_program=FakeContinuationProgram(),
        reply_generator=FakeReplyGenerator(),
    )

    result = asyncio.run(
        program.aforward(
            conversation=[ConversationMessage(from_me=False, text="esto parece un bot")],
            objective="Ask for pricing",
            company_context="",
            industry="unknown",
            channel="whatsapp",
        )
    )

    assert result == ConversationTurnResult(reply="gracias igual, lo dejo aca", done=True)


def test_first_message_program_uses_strategy_for_email_opening() -> None:
    strategy_calls: list[dict[str, object]] = []
    generator_calls: list[dict[str, object]] = []

    class FakeStrategyProgram:
        async def aforward(self, **kwargs) -> ConversationStrategy:
            strategy_calls.append(kwargs)
            return ConversationStrategy(
                phase="opening",
                buyer_setup="somos dos y estamos empezando",
                next_goal="ask one narrow process question",
                ask_family="process",
                tone_rules=["lowercase", "plain"],
            )

    class FakeGenerator:
        async def acall(self, **kwargs):
            generator_calls.append(kwargs)
            return SimpleNamespace(
                draft=FirstMessageDraft(
                    first_message=" hola, estamos empezando con algo chico y queria entender como trabajan con equipos asi ",
                    subject=" quick question ",
                )
            )

    program = FirstMessageProgram(strategy_program=FakeStrategyProgram())
    program.generator = FakeGenerator()

    result = asyncio.run(
        program.aforward(
            objective="Ask how they usually work with a small non technical team",
            contact_type=ContactType.EMAIL,
            company_context="custom software outsourcing for europe",
            target_language="es",
            industry="computer_programming_consultancy",
        )
    )

    assert result == FirstMessageDraft(
        first_message="hola, estamos empezando con algo chico y queria entender como trabajan con equipos asi",
        subject="quick question",
    )
    assert strategy_calls[0]["conversation"] == []
    assert strategy_calls[0]["channel"] == ContactType.EMAIL
    assert generator_calls[0]["industry"] == "computer_programming_consultancy"
    assert generator_calls[0]["channel"] == "email"
