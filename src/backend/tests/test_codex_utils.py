"""Tests for async Codex SDK helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend import codex_utils


class FakeValue:
    def __init__(self, value):
        self.value = value


class FakeWrapper:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeAskForApproval:
    @classmethod
    def model_validate(cls, value):
        return FakeValue(value)


class AgentMessageThreadItem:
    def __init__(self, text: str):
        self.text = text
        self.phase = FakeValue("final_answer")


class FakeItemCompletedNotification:
    def __init__(self, *, turn_id, item):
        self.turn_id = turn_id
        self.item = item


class FakeUsageNotification:
    def __init__(self, *, turn_id):
        self.turn_id = turn_id
        self.token_usage = {"total": 10}


class FakeTurnCompletedNotification:
    def __init__(self, *, turn):
        self.turn = turn


class FakeEvent:
    def __init__(self, payload):
        self.payload = payload


class FakeCompletedTurn:
    def __init__(self, *, status="completed", error=None):
        self.id = "turn-123"
        self.status = FakeValue(status)
        self.error = error


class FakeTurn:
    id = "turn-123"

    def __init__(self, calls):
        self.calls = calls
        self.steered = []
        self.interrupted = False

    async def stream(self):
        yield FakeEvent(FakeItemCompletedNotification(turn_id=self.id, item=AgentMessageThreadItem("done")))
        yield FakeEvent(FakeUsageNotification(turn_id=self.id))
        yield FakeEvent(FakeTurnCompletedNotification(turn=FakeCompletedTurn()))

    async def steer(self, input_value):
        self.steered.append(input_value)
        return {"steered": True}

    async def interrupt(self):
        self.interrupted = True
        return {"interrupted": True}


class FakeThread:
    def __init__(self, calls, thread_id="thread-123"):
        self.calls = calls
        self.id = thread_id

    async def turn(self, input_value, **kwargs):
        self.calls["input_value"] = input_value
        self.calls["turn_kwargs"] = kwargs
        turn = FakeTurn(self.calls)
        self.calls["turn"] = turn
        return turn

    async def read(self, *, include_turns=False):
        return {"thread_id": self.id, "include_turns": include_turns}

    async def set_name(self, name):
        self.calls["thread_name"] = name


class FakeAsyncCodex:
    def __init__(self, *, config):
        self.config = config
        self.calls = config["calls"]

    async def __aenter__(self):
        self.calls["config"] = self.config
        return self

    async def __aexit__(self, *args):
        self.calls["closed"] = True

    async def thread_start(self, **kwargs):
        self.calls["thread_start"] = kwargs
        return FakeThread(self.calls)

    async def thread_resume(self, thread_id, **kwargs):
        self.calls["thread_resume"] = (thread_id, kwargs)
        return FakeThread(self.calls, thread_id=thread_id)


def fake_sdk(calls):
    return {
        "AppServerConfig": lambda **kwargs: {**kwargs, "calls": calls},
        "AskForApproval": FakeAskForApproval,
        "AsyncCodex": FakeAsyncCodex,
        "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
        "ImageInput": lambda url: {"type": "image", "url": url},
        "ItemCompletedNotification": FakeItemCompletedNotification,
        "LocalImageInput": lambda **kwargs: {"type": "local_image", **kwargs},
        "MentionInput": lambda **kwargs: {"type": "mention", **kwargs},
        "ReasoningEffort": FakeValue,
        "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
        "ServiceTier": FakeValue,
        "SkillInput": lambda **kwargs: {"type": "skill", **kwargs},
        "TextInput": lambda text: {"type": "text", "text": text},
        "ThreadTokenUsageUpdatedNotification": FakeUsageNotification,
        "TurnCompletedNotification": FakeTurnCompletedNotification,
        "WorkspaceWriteSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
        "is_retryable_error": lambda error: False,
    }


def test_run_codex_with_context_starts_thread_and_passes_defaults(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(codex_utils, "_load_codex_sdk", lambda: fake_sdk(calls))

    result = asyncio.run(
        codex_utils.run_codex_with_context(
            "do the thing",
            model="test-model",
            cwd=tmp_path,
            codex_bin="/bin/codex",
        )
    )

    assert result.final_response == "done"
    assert result.thread_id == "thread-123"
    assert result.turn_id == "turn-123"
    assert result.items_count == 1
    assert result.cwd == tmp_path
    assert calls["config"]["codex_bin"] == "/bin/codex"
    assert calls["config"]["cwd"] == str(tmp_path)
    assert "OPENAI_API_KEY" not in calls["config"]["env"]
    assert calls["thread_start"]["model"] == "test-model"
    assert calls["input_value"] == [{"type": "text", "text": "do the thing"}]

    turn_kwargs = calls["turn_kwargs"]
    assert turn_kwargs["approval_policy"].value == "never"
    assert turn_kwargs["effort"].value == "medium"
    assert turn_kwargs["sandbox_policy"].root.type == "dangerFullAccess"
    assert turn_kwargs["service_tier"] is None


def test_run_codex_with_context_resumes_thread_and_passes_structured_items(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(codex_utils, "_load_codex_sdk", lambda: fake_sdk(calls))

    result = asyncio.run(
        codex_utils.run_codex_with_context(
            "use context",
            thread_id="existing-thread",
            skills=[codex_utils.CodexSkill(name="skill", path="/skill/SKILL.md")],
            mentions=[codex_utils.CodexMention(name="GitHub", path="app://connector_123")],
            local_images=[tmp_path / "image.png"],
            remote_images=["https://example.com/image.png"],
            effort="xhigh",
            service_tier="fast",
            cwd=tmp_path,
        )
    )

    assert result.thread_id == "existing-thread"
    assert calls["thread_resume"][0] == "existing-thread"
    assert calls["input_value"] == [
        {"type": "text", "text": "use context"},
        {"type": "skill", "name": "skill", "path": "/skill/SKILL.md"},
        {"type": "mention", "name": "GitHub", "path": "app://connector_123"},
        {"type": "local_image", "path": str((tmp_path / "image.png").resolve())},
        {"type": "image", "url": "https://example.com/image.png"},
    ]
    assert calls["turn_kwargs"]["effort"].value == "xhigh"
    assert calls["turn_kwargs"]["service_tier"].value == "fast"


def test_run_codex_with_context_accepts_workspace_write_sandbox(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(codex_utils, "_load_codex_sdk", lambda: fake_sdk(calls))

    asyncio.run(
        codex_utils.run_codex_with_context(
            "do the thing",
            cwd=tmp_path,
            sandbox_writable_roots=[tmp_path],
        )
    )

    sandbox_root = calls["turn_kwargs"]["sandbox_policy"].root
    assert sandbox_root.type == "workspaceWrite"
    assert sandbox_root.writable_roots == [str(tmp_path.resolve())]
    assert sandbox_root.network_access is True


def test_run_codex_with_context_exposes_active_turn(monkeypatch, tmp_path):
    calls = {}
    seen_turns = []
    monkeypatch.setattr(codex_utils, "_load_codex_sdk", lambda: fake_sdk(calls))

    asyncio.run(
        codex_utils.run_codex_with_context(
            "do the thing",
            cwd=tmp_path,
            on_turn_started=seen_turns.append,
        )
    )

    assert len(seen_turns) == 1
    asyncio.run(codex_utils.steer_turn(seen_turns[0], "shorter"))
    asyncio.run(codex_utils.interrupt_turn(seen_turns[0]))
    assert seen_turns[0].steered == [{"type": "text", "text": "shorter"}]
    assert seen_turns[0].interrupted is True


def test_run_codex_with_context_rejects_empty_prompt():
    with pytest.raises(ValueError, match="prompt"):
        asyncio.run(codex_utils.run_codex_with_context("   "))


def test_run_codex_text_returns_plain_response(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(codex_utils, "_load_codex_sdk", lambda: fake_sdk(calls))

    response = asyncio.run(codex_utils.run_codex_text("hello", cwd=tmp_path))

    assert response == "done"
