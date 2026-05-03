"""Regression tests for the Contadores post-Loom classifier."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.ai.contadores_post_loom_classifier import (
    PostLoomReplyClassificationResult,
    PostLoomReplyClassifierProgram,
    PostLoomServiceRecapProgram,
    PostLoomServiceRecapResult,
)


def test_post_loom_classifier_program_defaults_to_gpt_5_4_mini() -> None:
    program = PostLoomReplyClassifierProgram()
    assert program.lm.model == "openai/gpt-5.4-mini"


def test_post_loom_classifier_program_returns_flat_signature_output(monkeypatch) -> None:
    program = PostLoomReplyClassifierProgram()

    def fake_predict(*, loom_context: str, reply_batch: str):
        assert "loom" in loom_context.lower()
        assert "si" in reply_batch.lower()
        return SimpleNamespace(
            label="wants_to_proceed",
            reasoning="Respuesta afirmativa clara.",
        )

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            loom_context="Loom ya enviado.",
            reply_batch="- si",
        )
    )

    assert result == PostLoomReplyClassificationResult(
        label="wants_to_proceed",
        reasoning="Respuesta afirmativa clara.",
    )


def test_post_loom_classifier_can_return_watched_video_confirmation(monkeypatch) -> None:
    program = PostLoomReplyClassifierProgram()

    def fake_predict(*, loom_context: str, reply_batch: str):
        assert "vio el video" in loom_context.lower()
        assert "si" in reply_batch.lower()
        return SimpleNamespace(
            label="watched_video_confirmation",
            reasoning="Solo confirmo que vio el video.",
        )

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            loom_context="Clasifica si solo vio el video.",
            reply_batch="- Si",
        )
    )

    assert result == PostLoomReplyClassificationResult(
        label="watched_video_confirmation",
        reasoning="Solo confirmo que vio el video.",
    )


def test_post_loom_service_recap_program_uses_funnel_and_phone(monkeypatch) -> None:
    program = PostLoomServiceRecapProgram()

    def fake_predict(*, funnel_id: str, funnel_label: str, phone: str, reply_batch: str):
        assert funnel_id == "abogados"
        assert funnel_label == "Abogados"
        assert phone == "+59175432222"
        assert reply_batch == "- Si"
        return SimpleNamespace(
            message_text=(
                "Perfecto.\n\n"
                "Nosotros lo ayudamos a conseguir consultas de potenciales clientes en Bolivia, "
                "directo a su WhatsApp.\n\n"
                "Para avanzar, que dia le queda mejor esta semana?"
            ),
        )

    monkeypatch.setattr(program, "predict", fake_predict)

    result = asyncio.run(
        program.aforward(
            funnel_id="abogados",
            funnel_label="Abogados",
            phone="+59175432222",
            reply_batch="- Si",
        )
    )

    assert result == PostLoomServiceRecapResult(
        message_text=(
            "Perfecto.\n\n"
            "Nosotros lo ayudamos a conseguir consultas de potenciales clientes en Bolivia, "
            "directo a su WhatsApp.\n\n"
            "Para avanzar, que dia le queda mejor esta semana?"
        )
    )
