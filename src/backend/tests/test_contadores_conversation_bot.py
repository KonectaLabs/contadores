"""Regression tests for the Contadores conversation bot programs."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import backend.ai.contadores_conversation_bot as conversation_bot_module
from backend.ai.contadores_conversation_bot import (
    ACTIVE_OFFER_REJECTION_REPLY,
    CodexConversationBotProgram,
    ContadoresConversationBotProgram,
    ContadoresConversationBotResult,
    DspyConversationBotProgram,
    REJECTION_SURVEY_REPLY,
)
from backend.ai.contadores_conversation_prompt import build_conversation_bot_prompt
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
    assert program.codex_program.prefer_chatgpt_login is True
    assert program.codex_program.runtime_provider == "codex_chatgpt"
    assert program.codex_api_key_program is not None
    assert program.codex_api_key_program.prefer_chatgpt_login is False
    assert program.codex_api_key_program.runtime_provider == "codex_api_key"
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


def test_active_offer_prompt_overrides_default_offer() -> None:
    """The runtime prompt should tell the bot to follow recent offers/promos."""
    prompt = build_conversation_bot_prompt(
        **bot_kwargs(
            latest_inbound="me interesa",
            conversation=(
                "2026-05-05T20:00:00Z KONECTA step=promo_web_profesional_20260505: "
                "Hola Ana, promo para abogados de Bolivia: Solo 19 USD.\n"
                "2026-05-05T20:02:00Z LEAD: me interesa"
            ),
        )
    )

    assert "active offer" in prompt.lower()
    assert "overrides the default 300 USD offer" in prompt
    assert "Ask for email, day and time" in prompt


def test_prompt_offers_solo_page_promo_for_warm_deferral() -> None:
    """Light post-video interest should have a dedicated promo action."""
    prompt = build_conversation_bot_prompt(
        **bot_kwargs(
            latest_inbound="Si ya lo vi yo les estare comunicando muchas gracias",
            conversation=(
                "2026-05-06T02:17:00Z KONECTA step=loom_intro: Perfecto, te cuento rapido.\n"
                "2026-05-06T02:23:00Z KONECTA step=ai_reply: Perfecto, mirelo tranquilo.\n"
                "2026-05-06T02:24:00Z LEAD: Si ya lo vi yo les estare comunicando muchas gracias"
            ),
        )
    )

    assert "offer_solo_page_promo" in prompt
    assert "warm but not ready to advance" in prompt
    assert "Si ya lo vi yo les estare comunicando muchas gracias" in prompt


def test_active_offer_rejection_does_not_send_default_300_survey() -> None:
    """Rejecting a promo should not receive the default 300 USD rejection survey."""
    program = ContadoresConversationBotProgram(
        codex_program=SimpleNamespace(
            aforward=lambda **kwargs: ContadoresConversationBotResult(
                action="send_reply",
                message_text="Ok",
                classification_label="answered",
                reason="Respondio.",
            )
        )
    )

    async def fake_aforward(**kwargs):
        del kwargs
        return ContadoresConversationBotResult(
            action="send_reply",
            message_text="Ok",
            classification_label="answered",
            reason="Respondio.",
        )

    program.codex_program.aforward = fake_aforward

    result = asyncio.run(
        program.aforward(
            **bot_kwargs(
                latest_inbound="No gracias",
                conversation=(
                    "2026-05-05T20:00:00Z KONECTA step=promo_test: Solo 19 USD.\n"
                    "2026-05-05T20:01:00Z LEAD: No gracias"
                ),
            )
        )
    )

    assert result.action == "close_lead"
    assert result.message_text == ACTIVE_OFFER_REJECTION_REPLY
    assert result.message_text != REJECTION_SURVEY_REPLY


def test_dspy_conversation_bot_removes_inverted_opening_punctuation(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                action="send_reply",
                message_text="Para estar claros: ¿Que dia le queda mejor? ¡Perfecto!",
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


def test_dspy_conversation_bot_forces_rejection_survey(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                action="send_reply",
                message_text="Ok, no hay problema.",
                classification_label="answered_rejection",
                reason="Intento responder el rechazo.",
                missing_fields=[],
                scheduling_email="",
                scheduling_day="",
                scheduling_time="",
                timezone="",
            )

    monkeypatch.setattr(program, "predict", FakePredict())

    result = asyncio.run(
        program.aforward(
            **bot_kwargs(
                latest_inbound="No me interesa, gracias",
                conversation="LEAD: No me interesa, gracias",
            )
        )
    )

    assert result.action == "close_lead"
    assert result.message_text == REJECTION_SURVEY_REPLY
    assert result.classification_label == "service_rejection_survey"


def test_dspy_conversation_bot_does_not_treat_unwatched_video_as_rejection(monkeypatch) -> None:
    program = DspyConversationBotProgram()

    class FakePredict:
        async def acall(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                action="send_reply",
                message_text="Ok no hay problema, mire el video cuando pueda.",
                classification_label="not_watched_video",
                reason="No vio el video todavia.",
                missing_fields=[],
                scheduling_email="",
                scheduling_day="",
                scheduling_time="",
                timezone="",
            )

    monkeypatch.setattr(program, "predict", FakePredict())

    result = asyncio.run(
        program.aforward(
            **bot_kwargs(
                latest_inbound="No pude ver el video todavia",
                conversation="LEAD: No pude ver el video todavia",
            )
        )
    )

    assert result.action == "send_reply"
    assert result.message_text == "Ok no hay problema, mire el video cuando pueda."


def test_prompt_includes_konecta_source_of_truth() -> None:
    prompt = build_conversation_bot_prompt(**bot_kwargs(latest_inbound="De donde son?"))

    assert "KONECTA SOURCE OF TRUTH" in prompt
    assert "KonectaLabs is the trade name of Octopy LLC" in prompt
    assert "Escribo desde Argentina" in prompt
    assert "CURRENT WHATSAPP FUNNEL SERVICE" in prompt
    assert "professional custom page + 3 advertising campaigns" in prompt
    assert "Contadores ICP" in prompt
    assert "Abogados ICP" in prompt
    assert "DELIVERY OPERATION" in prompt
    assert "GUARANTEE AND CLAIM LIMITS" in prompt
    assert "CONSULTATIONS / PROSPECTS DEFINITION" in prompt
    assert "Do not immediately ask for email/day/time" in prompt
    assert "Do not say we are from the lead's country" in prompt


def test_codex_conversation_bot_parses_strict_json(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    async def fake_run_codex_with_context(prompt, **kwargs):
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
    assert result.runtime_provider == "codex_chatgpt"
    assert calls[0]["model"] == CONVERSATION_BOT_CODEX_MODEL
    assert calls[0]["effort"] == CONVERSATION_BOT_CODEX_EFFORT
    assert calls[0]["effort"] == "medium"
    assert calls[0]["prefer_chatgpt_login"] is True
    assert "You may inspect repository files" in str(calls[0]["prompt"])
    assert "Do not inspect or modify repository files" not in str(calls[0]["prompt"])
    assert "do not use tools" not in str(calls[0]["prompt"])
    assert "Return only valid JSON" in str(calls[0]["prompt"])


def test_codex_conversation_bot_overrides_wrong_origin_claim(monkeypatch) -> None:
    async def fake_run_codex_with_context(prompt, **kwargs):
        del prompt, kwargs
        return SimpleNamespace(
            final_response=(
                '{"action":"send_reply","message_text":"Somos de Ecuador. Mire el video.",'
                '"classification_label":"answered_origin","reason":"Respondio origen.",'
                '"missing_fields":[],"scheduling_email":"","scheduling_day":"",'
                '"scheduling_time":"","timezone":""}'
            )
        )

    monkeypatch.setattr(conversation_bot_module, "run_codex_with_context", fake_run_codex_with_context)

    result = asyncio.run(
        CodexConversationBotProgram().aforward(
            **bot_kwargs(
                phone="+593984649452",
                inferred_timezone="America/Guayaquil",
                latest_inbound="De donde son?",
                conversation="LEAD: De donde son?",
            )
        )
    )

    assert result.action == "send_reply"
    assert result.classification_label == "answered_company_origin"
    assert "Escribo desde Argentina" in result.message_text
    assert "clientes potenciales directo a su WhatsApp" in result.message_text
    assert "Ecuador" not in result.message_text


def test_codex_conversation_bot_answers_italian_number_from_source_truth(monkeypatch) -> None:
    async def fake_run_codex_with_context(prompt, **kwargs):
        del prompt, kwargs
        return SimpleNamespace(
            final_response=(
                '{"action":"send_reply","message_text":"Somos de Italia.",'
                '"classification_label":"answered_origin","reason":"Respondio origen.",'
                '"missing_fields":[],"scheduling_email":"","scheduling_day":"",'
                '"scheduling_time":"","timezone":""}'
            )
        )

    monkeypatch.setattr(conversation_bot_module, "run_codex_with_context", fake_run_codex_with_context)

    result = asyncio.run(
        CodexConversationBotProgram().aforward(
            **bot_kwargs(
                latest_inbound="El numero es de Italia?",
                conversation="LEAD: El numero es de Italia?",
            )
        )
    )

    assert result.action == "send_reply"
    assert result.classification_label == "answered_italian_number"
    assert "Alan" in result.message_text
    assert "Yo escribo desde Argentina" in result.message_text


def test_codex_conversation_bot_answers_consultation_definition_without_forcing_schedule(
    monkeypatch,
) -> None:
    async def fake_run_codex_with_context(prompt, **kwargs):
        del prompt, kwargs
        return SimpleNamespace(
            final_response=(
                '{"action":"send_reply",'
                '"message_text":"Para estar claros: las consultas son contactos de gente que necesita servicios contables. Que dia y horario te queda y cual es tu email?",'
                '"classification_label":"answered_consultation","reason":"Respondio definicion.",'
                '"missing_fields":["email","day","time"],"scheduling_email":"",'
                '"scheduling_day":"","scheduling_time":"","timezone":""}'
            )
        )

    monkeypatch.setattr(conversation_bot_module, "run_codex_with_context", fake_run_codex_with_context)

    result = asyncio.run(
        CodexConversationBotProgram().aforward(
            **bot_kwargs(
                funnel_id="contadores",
                funnel_label="Contadores",
                funnel_info="Publico: contadores. Objetivo: mas prospectos para servicios contables.",
                latest_inbound="La consulta sería entonces alguien que pregunte por los servicios, aunque no haya un cierre?",
                conversation=(
                    "LEAD: Para estar claros, las consultas como las defines?\n"
                    "KONECTA: Para estar claros: las consultas son contactos de gente que necesita servicios contables\n"
                    "LEAD: La consulta sería entonces alguien que pregunte por los servicios, aunque no haya un cierre?"
                ),
            )
        )
    )

    assert result.action == "send_reply"
    assert result.classification_label == "answered_consultation_definition"
    assert "No lo contamos como cliente cerrado" in result.message_text
    assert "oportunidad real" in result.message_text
    assert "likes ni visitas vacias" in result.message_text
    assert "Para estar claros" not in result.message_text
    assert "Que dia" not in result.message_text
    assert "email" not in result.message_text.lower()
    assert result.missing_fields == []


def test_orchestrator_uses_codex_api_key_fallback_when_chatgpt_codex_fails() -> None:
    class FailingCodex:
        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("chatgpt auth down")

    class FakeApiKeyCodex:
        async def aforward(self, **kwargs):
            assert kwargs["latest_inbound"] == "Cuanto cuesta?"
            return ContadoresConversationBotResult(
                action="send_reply",
                message_text="La inversion es de 300 USD, pago unico.",
                classification_label="answered_price",
                reason="API key Codex respondio precio.",
                runtime_provider="codex_api_key",
            )

    result = asyncio.run(
        ContadoresConversationBotProgram(
            codex_program=FailingCodex(),
            codex_api_key_program=FakeApiKeyCodex(),
        ).aforward(**bot_kwargs())
    )

    assert result.action == "send_reply"
    assert result.runtime_provider == "codex_api_key_fallback"
    assert "Codex ChatGPT failed" in result.runtime_error
    assert "https://auth.openai.com/codex/device" in result.runtime_error


def test_orchestrator_uses_dspy_fallback_when_both_codex_auth_paths_fail() -> None:
    class FailingChatgptCodex:
        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("chatgpt auth down")

    class FailingApiKeyCodex:
        async def aforward(self, **kwargs):
            del kwargs
            raise RuntimeError("api key down")

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
            codex_program=FailingChatgptCodex(),
            codex_api_key_program=FailingApiKeyCodex(),
            dspy_program=FakeDspy(),
        ).aforward(**bot_kwargs())
    )

    assert result.action == "send_reply"
    assert result.runtime_provider == "dspy_fallback"
    assert "Codex ChatGPT failed" in result.runtime_error
    assert "Codex API key failed" in result.runtime_error


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
            codex_api_key_program=FailingCodex(),
            dspy_program=FailingDspy(),
        ).aforward(**bot_kwargs())
    )

    assert result.action == "handoff_human"
    assert result.classification_label == "needs_human"
    assert result.runtime_provider == "failed"
    assert "Codex ChatGPT failed" in result.runtime_error
    assert "Codex API key failed" in result.runtime_error
    assert "DSPy failed" in result.runtime_error
