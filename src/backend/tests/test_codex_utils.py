"""Tests for Codex SDK helper defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import codex_utils


def test_run_codex_uses_no_approval_and_full_access_by_default(monkeypatch, tmp_path):
    """The local automation helper should be permissive unless callers override it."""
    calls = {}

    class FakeAskForApprovalValue:
        never = "never"

    class FakeAskForApproval:
        def __init__(self, *, root):
            self.root = root

    class FakeDangerFullAccessSandboxPolicy:
        def __init__(self, *, type):
            self.type = type

    class FakeSandboxPolicy:
        def __init__(self, *, root):
            self.root = root

    class FakeReasoningEffort:
        def __init__(self, value):
            self.value = value

    class FakeServiceTier:
        def __init__(self, value):
            self.value = value

    class FakeResult:
        final_response = "done"
        items = ["one", "two"]

    class FakeThread:
        def run(self, prompt, **kwargs):
            calls["prompt"] = prompt
            calls["run_kwargs"] = kwargs
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            calls["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            calls["model"] = model
            return FakeThread()

    class FakeAppServerConfig:
        def __init__(self, *, codex_bin, cwd, env):
            self.codex_bin = codex_bin
            self.cwd = cwd
            self.env = env

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": FakeAppServerConfig,
            "AskForApproval": FakeAskForApproval,
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": FakeDangerFullAccessSandboxPolicy,
            "MentionInput": lambda **kwargs: kwargs,
            "ReasoningEffort": FakeReasoningEffort,
            "SandboxPolicy": FakeSandboxPolicy,
            "ServiceTier": FakeServiceTier,
            "TextInput": lambda text: text,
        },
    )

    result = codex_utils.run_codex(
        "do the thing",
        model="test-model",
        cwd=tmp_path,
        codex_bin="/bin/codex",
    )

    assert result.final_response == "done"
    assert result.items_count == 2
    assert result.model == "test-model"
    assert result.effort == "medium"
    assert result.service_tier is None
    assert result.cwd == tmp_path
    assert calls["config"].codex_bin == "/bin/codex"
    assert calls["config"].cwd == str(tmp_path)
    assert "OPENAI_API_KEY" not in calls["config"].env
    assert calls["model"] == "test-model"
    assert calls["prompt"] == "do the thing"

    run_kwargs = calls["run_kwargs"]
    assert run_kwargs["approval_policy"].root == "never"
    assert run_kwargs["effort"].value == "medium"
    assert run_kwargs["sandbox_policy"].root.type == "dangerFullAccess"
    assert run_kwargs["service_tier"] is None


def test_run_codex_creates_codex_home(monkeypatch, tmp_path):
    """Codex CLI fails on deploy if CODEX_HOME points at a missing volume folder."""
    calls = {}
    codex_home = tmp_path / "data" / "codex-home"

    class FakeAskForApprovalValue:
        never = "never"

    class FakeValue:
        def __init__(self, value):
            self.value = value

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        final_response = "done"
        items = []

    class FakeThread:
        def run(self, prompt, **kwargs):
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            calls["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            return FakeThread()

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": lambda **kwargs: kwargs,
            "AskForApproval": lambda **kwargs: FakeWrapper(**kwargs),
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ReasoningEffort": FakeValue,
            "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ServiceTier": FakeValue,
        },
    )

    codex_utils.run_codex("do the thing", cwd=tmp_path)

    assert codex_home.is_dir()
    assert calls["config"]["env"]["CODEX_HOME"] == str(codex_home)


def test_run_codex_accepts_codex_home_override(monkeypatch, tmp_path):
    """Conversation fallbacks can isolate ChatGPT and API-key auth homes."""
    calls = {}
    env_codex_home = tmp_path / "env-home"
    override_codex_home = tmp_path / "override-home"

    class FakeAskForApprovalValue:
        never = "never"

    class FakeValue:
        def __init__(self, value):
            self.value = value

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        final_response = "done"
        items = []

    class FakeThread:
        def run(self, prompt, **kwargs):
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            calls["config"] = config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            return FakeThread()

    monkeypatch.setenv("CODEX_HOME", str(env_codex_home))
    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": lambda **kwargs: kwargs,
            "AskForApproval": lambda **kwargs: FakeWrapper(**kwargs),
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ReasoningEffort": FakeValue,
            "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ServiceTier": FakeValue,
        },
    )

    codex_utils.run_codex(
        "do the thing",
        cwd=tmp_path,
        codex_home=override_codex_home,
        prefer_chatgpt_login=False,
    )

    assert override_codex_home.is_dir()
    assert calls["config"]["env"]["CODEX_HOME"] == str(override_codex_home)


def test_run_codex_accepts_effort_and_service_tier(monkeypatch, tmp_path):
    """The SDK exposes effort and service tier as run-level controls."""
    calls = {}

    class FakeAskForApprovalValue:
        never = "never"

    class FakeValue:
        def __init__(self, value):
            self.value = value

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        final_response = "done"
        items = []

    class FakeThread:
        def run(self, prompt, **kwargs):
            calls["run_kwargs"] = kwargs
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            return FakeThread()

    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": lambda **kwargs: kwargs,
            "AskForApproval": lambda **kwargs: FakeWrapper(**kwargs),
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "MentionInput": lambda **kwargs: kwargs,
            "ReasoningEffort": FakeValue,
            "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ServiceTier": FakeValue,
            "TextInput": lambda text: text,
        },
    )

    result = codex_utils.run_codex(
        "do the thing",
        effort="xhigh",
        service_tier="fast",
        cwd=tmp_path,
    )

    assert result.effort == "xhigh"
    assert result.service_tier == "fast"
    assert calls["run_kwargs"]["effort"].value == "xhigh"
    assert calls["run_kwargs"]["service_tier"].value == "fast"


def test_run_codex_accepts_workspace_write_sandbox(monkeypatch, tmp_path):
    """Callers can constrain Codex writes to a known work folder."""
    calls = {}

    class FakeAskForApprovalValue:
        never = "never"

    class FakeValue:
        def __init__(self, value):
            self.value = value

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        final_response = "done"
        items = []

    class FakeThread:
        def run(self, prompt, **kwargs):
            del prompt
            calls["run_kwargs"] = kwargs
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            del config

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            del model
            return FakeThread()

    workdir = tmp_path / "client"
    workdir.mkdir()
    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": lambda **kwargs: kwargs,
            "AskForApproval": lambda **kwargs: FakeWrapper(**kwargs),
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ReasoningEffort": FakeValue,
            "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ServiceTier": FakeValue,
            "WorkspaceWriteSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
        },
    )

    codex_utils.run_codex(
        "do the thing",
        cwd=workdir,
        sandbox_writable_roots=[workdir],
    )

    sandbox_root = calls["run_kwargs"]["sandbox_policy"].root
    assert sandbox_root.type == "workspaceWrite"
    assert sandbox_root.writable_roots == [str(workdir.resolve())]
    assert sandbox_root.network_access is True


def test_run_codex_with_mentions_passes_structured_input(monkeypatch, tmp_path):
    """Mentions should be passed as structured SDK input items, not plain @ text."""
    calls = {}

    class FakeAskForApprovalValue:
        never = "never"

    class FakeValue:
        def __init__(self, value):
            self.value = value

    class FakeWrapper:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeResult:
        final_response = "done"
        items = ["item"]

    class FakeThread:
        def run(self, input_value, **kwargs):
            calls["input_value"] = input_value
            return FakeResult()

    class FakeCodex:
        def __init__(self, config):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def thread_start(self, *, model):
            return FakeThread()

    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerConfig": lambda **kwargs: kwargs,
            "AskForApproval": lambda **kwargs: FakeWrapper(**kwargs),
            "AskForApprovalValue": FakeAskForApprovalValue,
            "Codex": FakeCodex,
            "DangerFullAccessSandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "MentionInput": lambda **kwargs: {"type": "mention", **kwargs},
            "ReasoningEffort": FakeValue,
            "SandboxPolicy": lambda **kwargs: FakeWrapper(**kwargs),
            "ServiceTier": FakeValue,
            "TextInput": lambda text: {"type": "text", "text": text},
        },
    )

    result = codex_utils.run_codex_with_mentions(
        "use github",
        [codex_utils.CodexMention(name="GitHub", path="app://connector_123")],
        cwd=tmp_path,
    )

    assert result.final_response == "done"
    assert calls["input_value"] == [
        {"type": "text", "text": "use github"},
        {"type": "mention", "name": "GitHub", "path": "app://connector_123"},
    ]


def test_list_codex_apps_returns_summaries(monkeypatch, tmp_path):
    """App list should expose mention paths without leaking raw SDK details."""
    calls = {}

    class FakeResponse:
        def model_dump(self, **kwargs):
            return {
                "data": [
                    {
                        "id": "connector_123",
                        "name": "GitHub",
                        "description": "Repos and pull requests",
                        "isEnabled": True,
                        "isAccessible": False,
                    },
                    {
                        "id": "asdk_app_456",
                        "name": "Other",
                        "description": "Something else",
                        "isEnabled": True,
                        "isAccessible": True,
                    },
                ]
            }

    class FakeClient:
        def __init__(self, config):
            calls["config"] = config
            calls["closed"] = False

        def start(self):
            calls["started"] = True

        def initialize(self):
            calls["initialized"] = True

        def request(self, method, params, *, response_model):
            calls["request"] = (method, params, response_model)
            return FakeResponse()

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(
        codex_utils,
        "_load_codex_sdk",
        lambda: {
            "AppServerClient": FakeClient,
            "AppServerConfig": lambda **kwargs: kwargs,
            "AppsListResponse": object,
        },
    )

    apps = codex_utils.list_codex_apps(query="github", cwd=tmp_path)

    assert len(apps) == 1
    assert apps[0] == codex_utils.CodexAppSummary(
        id="connector_123",
        name="GitHub",
        description="Repos and pull requests",
        is_enabled=True,
        is_accessible=False,
        mention_path="app://connector_123",
    )
    assert calls["started"] is True
    assert calls["initialized"] is True
    assert calls["closed"] is True
    assert calls["request"][0] == "app/list"


def test_ask_codex_returns_plain_response(monkeypatch):
    """The simple helper should hide metadata for one-line call sites."""
    monkeypatch.setattr(
        codex_utils,
        "run_codex",
        lambda prompt, **kwargs: codex_utils.CodexRunResult(
            final_response=f"response to {prompt}",
            items_count=1,
            model=kwargs["model"],
            effort=kwargs["effort"],
            service_tier=kwargs["service_tier"],
            cwd=Path("/tmp"),
        ),
    )

    assert codex_utils.ask_codex("hello", model="test-model") == "response to hello"


def test_run_codex_rejects_empty_prompt():
    """Empty prompts are almost always caller bugs."""
    with pytest.raises(ValueError, match="prompt"):
        codex_utils.run_codex("   ")
