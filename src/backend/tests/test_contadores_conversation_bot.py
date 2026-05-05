"""Regression tests for the Contadores conversation bot programs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.ai.contadores_conversation_bot as conversation_bot_module
from backend.ai.contadores_conversation_bot import (
    CodexConversationBotProgram,
    ContadoresConversationBotProgram,
    ContadoresConversationBotResult,
    DspyConversationBotProgram,
)
from backend.config import CONVERSATION_BOT_CODEX_EFFORT, CONVERSATION_BOT_CODEX_MODEL


def bot_kwargs(**overrides):
    """Return a complete minimal bot input payload."""
    payload = {
        "funnel_id": "abogados",
        "funnel_label": "Abogados",
        "funnel_info": "Publico: abogados. Objetivo: mas consultas a WhatsApp.",
        "lead_name": "Ana",
        "phone": "+59175432222",
        "inferred_timezone": "America/La_Paz",
        "current_stage": "awaiting_video_reply",
        "latest_inbound": "Cuanto cuesta?",
        "conversation": "LEAD: Cuanto cuesta?",
    }
    payload.update(overrides)
    return payload


def test_conversation_bot_program_uses_codex_primary_and_configured_fallback_model() -> None:
    program = ContadoresConversationBotProgram()

    assert program.codex_program.model == CONVERSATION_BOT_CODEX_MODEL
    assert program.codex_program.effort == CONVERSATION_BOT_CODEX_EFFORT
    assert program.lm.model in {"openrouter/x-ai/grok-4.3", "openai/gpt-5.4-mini"}


def test_dspy_conversation_bot_returns_structured_action(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            assert kwargs["funnel_id"] == "abogados"
            assert kwargs["funnel_info"].startswith("Publico: abogados")
            assert "Cuanto cuesta" in kwargs["latest_inbound"]
            return SimpleNamespace(
                action="send_reply",
                message_text="La inversion es de 300 USD, pago unico.",
                classification_label="answered_price",
                reason="Respondio precio segun playbook.",
                missing_fields=[],
                scheduling_email="",
                scheduling_day="",
                scheduling_time="",
                timezone="",
            )

    monkeypatch.setattr(program, "predict", FakePredict())

    result = asyncio.run(program.aforward(**bot_kwargs()))

    assert result == ContadoresConversationBotResult(
        action="send_reply",
        message_text="La inversion es de 300 USD, pago unico.",
        classification_label="answered_price",
        reason="Respondio precio segun playbook.",
        runtime_provider="dspy",
    )


def test_dspy_conversation_bot_normalizes_unknown_action_to_handoff(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                action="invented_action",
                message_text="",
                classification_label="",
                reason="No sabe contestar.",
                missing_fields="email, dia",
                scheduling_email="",
                scheduling_day="",
                scheduling_time="",
                timezone="",
            )

    monkeypatch.setattr(program, "predict", FakePredict())

    result = asyncio.run(
        program.aforward(
            **bot_kwargs(
                funnel_id="contadores",
                funnel_label="Contadores",
                latest_inbound="[audio]",
                conversation="LEAD: [audio]",
            )
        )
    )

    assert result.action == "handoff_human"
    assert result.missing_fields == ["email", "dia"]


def test_dspy_conversation_bot_removes_inverted_opening_punctuation(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                action="send_reply",
                message_text="¿Que dia le queda mejor? ¡Perfecto!",
                classification_label="answered",
                reason="Respondio con estilo de WhatsApp.",
                missing_fields=[],
                scheduling_email="",
                scheduling_day="",
                scheduling_time="",
                timezone="",
            )

    monkeypatch.setattr(program, "predict", FakePredict())

    result = asyncio.run(program.aforward(**bot_kwargs(latest_inbound="Si", conversation="LEAD: Si")))

    assert result.message_text == "Que dia le queda mejor? Perfecto!"


def test_codex_conversation_bot_parses_strict_json(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run_codex_with_context(prompt, **kwargs):
        calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            final_response=(
                '```json\n{"action":"send_reply","message_text":"Son 300 USD, pago unico.",'
                '"classification_label":"answered_price","reason":"Respondio precio.",'
                '"missing_fields":[],"scheduling_email":"","scheduling_day":"",'
                '"scheduling_time":"","timezone":""}\n```'
            )
        )

    monkeypatch.setattr(conversation_bot_module, "run_codex_with_context", fake_run_codex_with_context)

    result = asyncio.run(CodexConversationBotProgram().aforward(**bot_kwargs()))

    assert result.action == "send_reply"
    assert result.message_text == "Son 300 USD, pago unico."
    assert result.runtime_provider == "codex"
    assert calls[0]["model"] == CONVERSATION_BOT_CODEX_MODEL
    assert calls[0]["effort"] == CONVERSATION_BOT_CODEX_EFFORT
    assert "Return only valid JSON" in str(calls[0]["prompt"])


def test_orchestrator_uses_dspy_fallback_when_codex_fails() -> None:
    class FailingCodex:
        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("codex down")

    class FakeDspy:
        lm = None

        async def aforward(self, **kwargs):
            assert kwargs["latest_inbound"] == "Cuanto cuesta?"
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text="La inversion es de 300 USD, pago unico.",
                classification_label="answered_price",
                reason="Fallback respondio precio.",
                runtime_provider="dspy",
            )

    result = asyncio.run(
        ContadoresConversationBotProgram(
            codex_program=FailingCodex(),
            dspy_program=FakeDspy(),
        ).aforward(**bot_kwargs())
    )

    assert result.action == "send_reply"
    assert result.runtime_provider == "dspy_fallback"
    assert "Codex failed" in result.runtime_error


def test_orchestrator_handoff_when_codex_and_fallback_fail() -> None:
    class FailingCodex:
        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("codex down")

    class FailingDspy:
        lm = None

        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("fallback down")

    result = asyncio.run(
        ContadoresConversationBotProgram(
            codex_program=FailingCodex(),
            dspy_program=FailingDspy(),
        ).aforward(**bot_kwargs())
    )

    assert result.action == "handoff_human"
    assert result.classification_label == "needs_human"
    assert result.runtime_provider == "failed"
    assert "DSPy failed" in result.runtime_error
