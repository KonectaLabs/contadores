"""Tests for lazy AI provider configuration."""

from __future__ import annotations

import importlib

import dspy

import backend.config as backend_config


def test_backend_config_import_does_not_construct_model_clients(monkeypatch) -> None:
    """Plain config imports should not initialize provider clients."""
    calls: list[tuple[object, object]] = []

    def fail_lm(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("dspy.LM should not be constructed during config import")

    monkeypatch.setattr(dspy, "LM", fail_lm)

    reloaded_config = importlib.reload(backend_config)

    assert reloaded_config.AUDIO_TRANSCRIPTION_MODEL
    assert calls == []
