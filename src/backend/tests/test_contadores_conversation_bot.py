"""Regression tests for the Contadores conversation bot program."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.ai.contadores_conversation_bot import (
    ContadoresConversationBotProgram,
    ContadoresConversationBotResult,
)


def test_conversation_bot_program_uses_configured_conversation_model() -> None:
    program = ContadoresConversationBotProgram()
    assert program.lm.model in {"openrouter/x-ai/grok-4.3", "openai/gpt-5.4-mini"}


def test_conversation_bot_program_returns_structured_action(monkeypatch) -> None:
    program = ContadoresConversationBotProgram()

    def fake_predict(**kwargs):
        assert kwargs["funnel_id"] == "abogados"
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

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            funnel_id="abogados",
            funnel_label="Abogados",
            lead_name="Ana",
            phone="+59175432222",
            inferred_timezone="America/La_Paz",
            current_stage="awaiting_video_reply",
            latest_inbound="Cuanto cuesta?",
            conversation="LEAD: Cuanto cuesta?",
        )
    )

    assert result == ContadoresConversationBotResult(
        action="send_reply",
        message_text="La inversion es de 300 USD, pago unico.",
        classification_label="answered_price",
        reason="Respondio precio segun playbook.",
    )


def test_conversation_bot_normalizes_unknown_action_to_handoff(monkeypatch) -> None:
    program = ContadoresConversationBotProgram()

    def fake_predict(**kwargs):
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

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            funnel_id="contadores",
            funnel_label="Contadores",
            lead_name="",
            phone="+5491111111111",
            inferred_timezone="America/Argentina/Buenos_Aires",
            current_stage="awaiting_video_reply",
            latest_inbound="[audio]",
            conversation="LEAD: [audio]",
        )
    )

    assert result.action == "handoff_human"
    assert result.missing_fields == ["email", "dia"]


def test_conversation_bot_removes_inverted_opening_punctuation(monkeypatch) -> None:
    program = ContadoresConversationBotProgram()

    def fake_predict(**kwargs):
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

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            funnel_id="abogados",
            funnel_label="Abogados",
            lead_name="",
            phone="+59175432222",
            inferred_timezone="America/La_Paz",
            current_stage="awaiting_video_reply",
            latest_inbound="Si",
            conversation="LEAD: Si",
        )
    )

    assert result.message_text == "Que dia le queda mejor? Perfecto!"
