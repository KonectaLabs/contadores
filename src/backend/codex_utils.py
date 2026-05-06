"""Small helpers for driving Codex through the Python SDK."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CODEX_BIN = os.getenv(
    "CODEX_BIN",
    shutil.which("codex") or "/opt/homebrew/bin/codex",
)
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_EFFORT = "medium"
DEFAULT_PREFER_CHATGPT_LOGIN = os.getenv("CODEX_PREFER_CHATGPT_LOGIN", "true").lower() not in {
    "0",
    "false",
    "no",
}

ReasoningEffortName = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
ServiceTierName = Literal["fast", "flex"]


@dataclass(frozen=True)
class CodexRunResult:
    """Compact result for a Codex SDK run."""

    final_response: str
    items_count: int
    model: str
    effort: ReasoningEffortName
    service_tier: ServiceTierName | None
    cwd: Path


@dataclass(frozen=True)
class CodexMention:
    """Structured app/plugin mention for Codex SDK runs."""

    name: str
    path: str


@dataclass(frozen=True)
class CodexSkill:
    """Structured skill mention for Codex SDK runs."""

    name: str
    path: str


@dataclass(frozen=True)
class CodexAppSummary:
    """Small app-list entry returned by app-server."""

    id: str
    name: str
    description: str
    is_enabled: bool
    is_accessible: bool
    mention_path: str


def ask_codex(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> str:
    """Run Codex with full local access and return only the final response."""
    return run_codex(
        prompt,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
    ).final_response


def ask_codex_with_mentions(
    prompt: str,
    mentions: list[CodexMention],
    *,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> str:
    """Run Codex with structured app mentions and return only the final response."""
    return run_codex_with_mentions(
        prompt,
        mentions,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
    ).final_response


def ask_codex_with_context(
    prompt: str,
    *,
    skills: list[CodexSkill] | None = None,
    mentions: list[CodexMention] | None = None,
    local_images: list[str | Path] | None = None,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> str:
    """Run Codex with optional skills, app mentions, and local image inputs."""
    return run_codex_with_context(
        prompt,
        skills=skills,
        mentions=mentions,
        local_images=local_images,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
    ).final_response


def run_codex(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    sandbox_writable_roots: list[str | Path] | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
    on_turn_started: Callable[[Any], None] | None = None,
) -> CodexRunResult:
    """
    Run Codex through app-server with no approval prompts and full filesystem access.

    Defaults are intentionally permissive for local automation:
    - approval policy: never ask;
    - sandbox policy: dangerFullAccess;
    - model: gpt-5.5;
    - reasoning effort: medium;
    - auth preference: ChatGPT login, by removing OPENAI_API_KEY from the child env.
    """
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    sdk = _load_codex_sdk()
    return _run_codex_input(
        sdk,
        prompt,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        sandbox_writable_roots=sandbox_writable_roots,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
        on_turn_started=on_turn_started,
    )


def run_codex_with_mentions(
    prompt: str,
    mentions: list[CodexMention],
    *,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    sandbox_writable_roots: list[str | Path] | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
    on_turn_started: Callable[[Any], None] | None = None,
) -> CodexRunResult:
    """Run Codex with app mentions such as app://connector_... paths."""
    if not mentions:
        return run_codex(
            prompt,
            model=model,
            effort=effort,
            service_tier=service_tier,
            cwd=cwd,
            sandbox_writable_roots=sandbox_writable_roots,
            codex_home=codex_home,
            codex_bin=codex_bin,
            prefer_chatgpt_login=prefer_chatgpt_login,
            on_turn_started=on_turn_started,
        )

    sdk = _load_codex_sdk()
    input_items = [sdk["TextInput"](prompt)]
    input_items.extend(
        sdk["MentionInput"](name=mention.name, path=mention.path)
        for mention in mentions
    )

    return _run_codex_input(
        sdk,
        input_items,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        sandbox_writable_roots=sandbox_writable_roots,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
        on_turn_started=on_turn_started,
    )


def run_codex_with_context(
    prompt: str,
    *,
    skills: list[CodexSkill] | None = None,
    mentions: list[CodexMention] | None = None,
    local_images: list[str | Path] | None = None,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    sandbox_writable_roots: list[str | Path] | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
    on_turn_started: Callable[[Any], None] | None = None,
) -> CodexRunResult:
    """Run Codex with structured skill, mention, and local image input items."""
    if not prompt.strip():
        raise ValueError("prompt must not be empty")

    sdk = _load_codex_sdk()
    input_items = [sdk["TextInput"](prompt)]
    input_items.extend(
        sdk["SkillInput"](name=skill.name, path=skill.path)
        for skill in (skills or [])
    )
    input_items.extend(
        sdk["MentionInput"](name=mention.name, path=mention.path)
        for mention in (mentions or [])
    )
    input_items.extend(
        sdk["LocalImageInput"](path=str(Path(image_path).expanduser().resolve()))
        for image_path in (local_images or [])
    )

    return _run_codex_input(
        sdk,
        input_items,
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=cwd,
        sandbox_writable_roots=sandbox_writable_roots,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
        on_turn_started=on_turn_started,
    )


def list_codex_apps(
    *,
    query: str | None = None,
    limit: int = 100,
    max_pages: int = 10,
    cwd: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> list[CodexAppSummary]:
    """List apps/connectors known to the Codex app-server."""
    sdk = _load_codex_sdk()
    run_cwd = Path(cwd).expanduser().resolve() if cwd is not None else REPO_ROOT
    env = _build_child_env(prefer_chatgpt_login=prefer_chatgpt_login)
    config = sdk["AppServerConfig"](
        codex_bin=codex_bin,
        cwd=str(run_cwd),
        env=env,
        experimental_api=True,
    )

    query_text = query.casefold() if query else None
    apps: list[CodexAppSummary] = []

    client = sdk["AppServerClient"](config)
    client.start()
    client.initialize()
    try:
        cursor = None
        for page_index in range(max_pages):
            response = client.request(
                "app/list",
                {
                    "cursor": cursor,
                    "limit": limit,
                    "forceRefetch": page_index == 0,
                },
                response_model=sdk["AppsListResponse"],
            )
            payload = response.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            for item in payload.get("data", []):
                app = _app_summary_from_payload(item)
                haystack = f"{app.name} {app.description} {app.id}".casefold()
                if query_text is None or query_text in haystack:
                    apps.append(app)

            cursor = payload.get("nextCursor")
            if not cursor:
                break
    finally:
        client.close()

    return apps


def find_codex_app(
    name: str,
    *,
    cwd: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> CodexAppSummary | None:
    """Find the first app whose name exactly matches, case-insensitively."""
    wanted = name.casefold()
    for app in list_codex_apps(
        query=name,
        cwd=cwd,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
    ):
        if app.name.casefold() == wanted:
            return app
    return None


def _run_codex_input(
    sdk: dict[str, Any],
    input_value: Any,
    *,
    model: str,
    effort: ReasoningEffortName,
    service_tier: ServiceTierName | None,
    cwd: str | Path | None,
    sandbox_writable_roots: list[str | Path] | None,
    codex_home: str | Path | None,
    codex_bin: str,
    prefer_chatgpt_login: bool,
    on_turn_started: Callable[[Any], None] | None,
) -> CodexRunResult:
    run_cwd = Path(cwd).expanduser().resolve() if cwd is not None else REPO_ROOT
    env = _build_child_env(
        prefer_chatgpt_login=prefer_chatgpt_login,
        codex_home=codex_home,
    )

    config = sdk["AppServerConfig"](
        codex_bin=codex_bin,
        cwd=str(run_cwd),
        env=env,
    )

    with sdk["Codex"](config) as codex:
        thread = codex.thread_start(model=model)
        run_kwargs = {
            "approval_policy": sdk["AskForApproval"](
                root=sdk["AskForApprovalValue"].never
            ),
            "effort": sdk["ReasoningEffort"](effort),
            "sandbox_policy": _build_sandbox_policy(sdk, sandbox_writable_roots=sandbox_writable_roots),
            "service_tier": sdk["ServiceTier"](service_tier) if service_tier else None,
        }
        if on_turn_started is None:
            result = thread.run(input_value, **run_kwargs)
        else:
            turn = thread.turn(input_value, **run_kwargs)
            on_turn_started(turn)
            stream = turn.stream()
            try:
                result = sdk["collect_run_result"](stream, turn_id=turn.id)
            finally:
                stream.close()

    return CodexRunResult(
        final_response=result.final_response or "",
        items_count=len(result.items),
        model=model,
        effort=effort,
        service_tier=service_tier,
        cwd=run_cwd,
    )


def _build_sandbox_policy(
    sdk: dict[str, Any],
    *,
    sandbox_writable_roots: list[str | Path] | None,
) -> Any:
    """Build the Codex sandbox policy for one run."""
    if sandbox_writable_roots is None:
        return sdk["SandboxPolicy"](
            root=sdk["DangerFullAccessSandboxPolicy"](type="dangerFullAccess")
        )

    workspace_policy = sdk.get("WorkspaceWriteSandboxPolicy")
    if workspace_policy is None:
        raise RuntimeError("Codex SDK does not expose WorkspaceWriteSandboxPolicy")
    writable_roots = [
        str(Path(root).expanduser().resolve())
        for root in sandbox_writable_roots
    ]
    return sdk["SandboxPolicy"](
        root=workspace_policy(
            type="workspaceWrite",
            writable_roots=writable_roots,
            network_access=True,
        )
    )


def _build_child_env(
    *,
    prefer_chatgpt_login: bool,
    codex_home: str | Path | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    if codex_home is not None:
        clean_codex_home = str(codex_home).strip()
        if clean_codex_home:
            env["CODEX_HOME"] = clean_codex_home
    resolved_codex_home = env.get("CODEX_HOME")
    if resolved_codex_home:
        Path(resolved_codex_home).expanduser().mkdir(parents=True, exist_ok=True)
    if prefer_chatgpt_login:
        env.pop("OPENAI_API_KEY", None)
    return env


def _app_summary_from_payload(payload: dict[str, Any]) -> CodexAppSummary:
    app_id = str(payload.get("id", ""))
    return CodexAppSummary(
        id=app_id,
        name=str(payload.get("name", "")),
        description=str(payload.get("description", "")),
        is_enabled=bool(payload.get("isEnabled", False)),
        is_accessible=bool(payload.get("isAccessible", False)),
        mention_path=f"app://{app_id}",
    )


def _load_codex_sdk() -> dict[str, Any]:
    try:
        from codex_app_server import (
            AppServerClient,
            AppServerConfig,
            AskForApproval,
            Codex,
            LocalImageInput,
            MentionInput,
            SandboxPolicy,
            SkillInput,
            TextInput,
        )
        from codex_app_server.api import _collect_run_result
        from codex_app_server import ReasoningEffort, ServiceTier
        from codex_app_server.generated.v2_all import (
            AppsListResponse,
            AskForApprovalValue,
            DangerFullAccessSandboxPolicy,
            WorkspaceWriteSandboxPolicy,
        )
    except ImportError as error:
        message = (
            "Codex Python SDK is not installed. Run `uv sync` and make sure "
            "`openai-codex-app-server-sdk` is available in the backend environment."
        )
        raise RuntimeError(message) from error

    return {
        "AppServerClient": AppServerClient,
        "AppServerConfig": AppServerConfig,
        "AppsListResponse": AppsListResponse,
        "AskForApproval": AskForApproval,
        "AskForApprovalValue": AskForApprovalValue,
        "Codex": Codex,
        "collect_run_result": _collect_run_result,
        "DangerFullAccessSandboxPolicy": DangerFullAccessSandboxPolicy,
        "WorkspaceWriteSandboxPolicy": WorkspaceWriteSandboxPolicy,
        "LocalImageInput": LocalImageInput,
        "MentionInput": MentionInput,
        "ReasoningEffort": ReasoningEffort,
        "SandboxPolicy": SandboxPolicy,
        "ServiceTier": ServiceTier,
        "SkillInput": SkillInput,
        "TextInput": TextInput,
    }
