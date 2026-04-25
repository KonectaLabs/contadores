"""Regression tests for the Contadores post-Loom classifier."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from backend.ai.contadores_post_loom_classifier import (
    PostLoomReplyClassificationResult,
    PostLoomReplyClassifierProgram,
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
