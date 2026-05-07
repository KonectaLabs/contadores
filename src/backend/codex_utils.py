"""Async helpers for driving Codex through the Python SDK."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import shutil
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


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
class CodexRuntimeConfig:
    """Runtime configuration for one Codex app-server session."""

    cwd: Path = REPO_ROOT
    codex_home: Path | None = None
    codex_bin: str = DEFAULT_CODEX_BIN
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN
    model: str = DEFAULT_MODEL
    effort: ReasoningEffortName = DEFAULT_EFFORT
    service_tier: ServiceTierName | None = None
    sandbox_writable_roots: list[Path] | None = None

    @classmethod
    def build(
        cls,
        *,
        cwd: str | Path | None = None,
        codex_home: str | Path | None = None,
        codex_bin: str = DEFAULT_CODEX_BIN,
        prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
        model: str = DEFAULT_MODEL,
        effort: ReasoningEffortName = DEFAULT_EFFORT,
        service_tier: ServiceTierName | None = None,
        sandbox_writable_roots: list[str | Path] | None = None,
    ) -> "CodexRuntimeConfig":
        """Build a normalized runtime config from endpoint-friendly values."""
        return cls(
            cwd=Path(cwd).expanduser().resolve() if cwd is not None else REPO_ROOT,
            codex_home=Path(codex_home).expanduser() if codex_home else None,
            codex_bin=codex_bin,
            prefer_chatgpt_login=prefer_chatgpt_login,
            model=model,
            effort=effort,
            service_tier=service_tier,
            sandbox_writable_roots=[
                Path(root).expanduser().resolve()
                for root in (sandbox_writable_roots or [])
            ]
            or None,
        )


@dataclass(frozen=True)
class CodexMention:
    """Structured app/plugin mention for Codex SDK input."""

    name: str
    path: str


@dataclass(frozen=True)
class CodexSkill:
    """Structured skill mention for Codex SDK input."""

    name: str
    path: str


@dataclass(frozen=True)
class CodexInputContext:
    """Input items for one Codex turn."""

    prompt: str
    skills: list[CodexSkill] = field(default_factory=list)
    mentions: list[CodexMention] = field(default_factory=list)
    local_images: list[Path] = field(default_factory=list)
    remote_images: list[str] = field(default_factory=list)

    @classmethod
    def build(
        cls,
        prompt: str,
        *,
        skills: list[CodexSkill] | None = None,
        mentions: list[CodexMention] | None = None,
        local_images: list[str | Path] | None = None,
        remote_images: list[str] | None = None,
    ) -> "CodexInputContext":
        """Build normalized input context for SDK input items."""
        clean_prompt = prompt.strip()
        if not clean_prompt:
            raise ValueError("prompt must not be empty")
        return cls(
            prompt=clean_prompt,
            skills=skills or [],
            mentions=mentions or [],
            local_images=[
                Path(image_path).expanduser().resolve()
                for image_path in (local_images or [])
            ],
            remote_images=[url.strip() for url in (remote_images or []) if url.strip()],
        )


@dataclass(frozen=True)
class CodexThreadRef:
    """A persisted Codex thread reference."""

    thread_id: str
    created: bool


@dataclass(frozen=True)
class CodexTurnResult:
    """Compact result for one Codex turn."""

    final_response: str
    thread_id: str
    turn_id: str
    status: str
    error: str | None
    items_count: int
    usage: Any | None
    model: str
    effort: ReasoningEffortName
    service_tier: ServiceTierName | None
    cwd: Path


@dataclass(frozen=True)
class CodexAppSummary:
    """Small app-list entry returned by app-server."""

    id: str
    name: str
    description: str
    is_enabled: bool
    is_accessible: bool
    mention_path: str


async def run_codex_text(
    prompt: str,
    *,
    thread_id: str | None = None,
    **kwargs: Any,
) -> str:
    """Run one Codex turn and return only the final assistant text."""
    result = await run_codex_with_context(prompt, thread_id=thread_id, **kwargs)
    return result.final_response


async def run_codex_json(
    prompt: str,
    *,
    output_schema: dict[str, Any] | None = None,
    thread_id: str | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], CodexTurnResult]:
    """Run one Codex turn and parse the final response as JSON."""
    result = await run_codex_with_context(
        prompt,
        output_schema=output_schema,
        thread_id=thread_id,
        **kwargs,
    )
    try:
        payload = json.loads(result.final_response)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Expected Codex JSON output, got: {result.final_response!r}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected Codex JSON object, got: {payload!r}")
    return payload, result


async def run_codex_with_context(
    prompt: str,
    *,
    thread_id: str | None = None,
    skills: list[CodexSkill] | None = None,
    mentions: list[CodexMention] | None = None,
    local_images: list[str | Path] | None = None,
    remote_images: list[str] | None = None,
    model: str = DEFAULT_MODEL,
    effort: ReasoningEffortName = DEFAULT_EFFORT,
    service_tier: ServiceTierName | None = None,
    cwd: str | Path | None = None,
    sandbox_writable_roots: list[str | Path] | None = None,
    codex_home: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
    output_schema: dict[str, Any] | None = None,
    personality: Any | None = None,
    summary: Any | None = None,
    on_turn_started: Callable[[Any], Any | Awaitable[Any]] | None = None,
    max_attempts: int = 3,
) -> CodexTurnResult:
    """Run one async Codex turn with optional persisted thread continuity."""
    runtime = CodexRuntimeConfig.build(
        cwd=cwd,
        codex_home=codex_home,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
        model=model,
        effort=effort,
        service_tier=service_tier,
        sandbox_writable_roots=sandbox_writable_roots,
    )
    context = CodexInputContext.build(
        prompt,
        skills=skills,
        mentions=mentions,
        local_images=local_images,
        remote_images=remote_images,
    )
    return await run_turn(
        context,
        runtime=runtime,
        thread_id=thread_id,
        output_schema=output_schema,
        personality=personality,
        summary=summary,
        on_turn_started=on_turn_started,
        max_attempts=max_attempts,
    )


async def start_thread(
    codex: Any,
    runtime: CodexRuntimeConfig,
    *,
    name: str | None = None,
) -> Any:
    """Start one Codex thread using the runtime defaults."""
    sdk = _load_codex_sdk()
    thread = await codex.thread_start(
        model=runtime.model,
        config={"model_reasoning_effort": runtime.effort},
        cwd=str(runtime.cwd),
        service_tier=sdk["ServiceTier"](runtime.service_tier) if runtime.service_tier else None,
    )
    if name:
        await thread.set_name(name)
    return thread


async def resume_thread(
    codex: Any,
    thread_id: str,
    runtime: CodexRuntimeConfig,
) -> Any:
    """Resume one existing Codex thread."""
    sdk = _load_codex_sdk()
    return await codex.thread_resume(
        thread_id,
        model=runtime.model,
        config={"model_reasoning_effort": runtime.effort},
        cwd=str(runtime.cwd),
        service_tier=sdk["ServiceTier"](runtime.service_tier) if runtime.service_tier else None,
    )


async def read_thread(thread: Any, *, include_turns: bool = False) -> Any:
    """Read one SDK thread."""
    return await thread.read(include_turns=include_turns)


async def steer_turn(turn: Any, message: str) -> Any:
    """Steer one active async turn."""
    sdk = _load_codex_sdk()
    result = turn.steer(sdk["TextInput"](message))
    if inspect.isawaitable(result):
        return await result
    return result


async def interrupt_turn(turn: Any) -> Any:
    """Interrupt one active async turn."""
    result = turn.interrupt()
    if inspect.isawaitable(result):
        return await result
    return result


async def stream_turn(turn: Any) -> AsyncIterator[Any]:
    """Yield SDK events for one active async turn."""
    async for event in turn.stream():
        yield event


async def run_turn(
    context: CodexInputContext,
    *,
    runtime: CodexRuntimeConfig,
    thread_id: str | None = None,
    output_schema: dict[str, Any] | None = None,
    personality: Any | None = None,
    summary: Any | None = None,
    on_turn_started: Callable[[Any], Any | Awaitable[Any]] | None = None,
    max_attempts: int = 3,
) -> CodexTurnResult:
    """Run one Codex turn with retry around overload-style errors."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempt = 0
    delay_s = 0.25
    while True:
        attempt += 1
        try:
            return await _run_turn_once(
                context,
                runtime=runtime,
                thread_id=thread_id,
                output_schema=output_schema,
                personality=personality,
                summary=summary,
                on_turn_started=on_turn_started,
            )
        except Exception as error:  # noqa: BLE001
            sdk = _load_codex_sdk()
            if attempt >= max_attempts or not sdk["is_retryable_error"](error):
                raise
            jitter = delay_s * 0.2
            await asyncio.sleep(max(0.0, delay_s + random.uniform(-jitter, jitter)))
            delay_s = min(delay_s * 2, 2.0)


async def list_codex_apps(
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

    client = sdk["AsyncAppServerClient"](config)
    await client.start()
    await client.initialize()
    try:
        cursor = None
        for page_index in range(max_pages):
            response = await client.request(
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
        await client.close()

    return apps


async def find_codex_app(
    name: str,
    *,
    cwd: str | Path | None = None,
    codex_bin: str = DEFAULT_CODEX_BIN,
    prefer_chatgpt_login: bool = DEFAULT_PREFER_CHATGPT_LOGIN,
) -> CodexAppSummary | None:
    """Find the first app whose name exactly matches, case-insensitively."""
    wanted = name.casefold()
    for app in await list_codex_apps(
        query=name,
        cwd=cwd,
        codex_bin=codex_bin,
        prefer_chatgpt_login=prefer_chatgpt_login,
    ):
        if app.name.casefold() == wanted:
            return app
    return None


async def _run_turn_once(
    context: CodexInputContext,
    *,
    runtime: CodexRuntimeConfig,
    thread_id: str | None,
    output_schema: dict[str, Any] | None,
    personality: Any | None,
    summary: Any | None,
    on_turn_started: Callable[[Any], Any | Awaitable[Any]] | None,
) -> CodexTurnResult:
    sdk = _load_codex_sdk()
    env = _build_child_env(
        prefer_chatgpt_login=runtime.prefer_chatgpt_login,
        codex_home=runtime.codex_home,
    )
    config = sdk["AppServerConfig"](
        codex_bin=runtime.codex_bin,
        cwd=str(runtime.cwd),
        env=env,
    )

    async with sdk["AsyncCodex"](config=config) as codex:
        if thread_id:
            thread = await resume_thread(codex, thread_id, runtime)
        else:
            thread = await start_thread(codex, runtime)

        input_items = _build_input_items(sdk, context)
        turn_kwargs = {
            "approval_policy": sdk["AskForApproval"].model_validate("never"),
            "cwd": str(runtime.cwd),
            "effort": sdk["ReasoningEffort"](runtime.effort),
            "model": runtime.model,
            "output_schema": output_schema,
            "personality": personality,
            "sandbox_policy": _build_sandbox_policy(sdk, runtime),
            "service_tier": sdk["ServiceTier"](runtime.service_tier) if runtime.service_tier else None,
            "summary": summary,
        }
        turn = await thread.turn(input_items, **turn_kwargs)
        if on_turn_started is not None:
            callback_result = on_turn_started(turn)
            if inspect.isawaitable(callback_result):
                await callback_result

        run_result = await _collect_turn_result(sdk, turn)
        return CodexTurnResult(
            final_response=run_result["final_response"],
            thread_id=thread.id,
            turn_id=turn.id,
            status=run_result["status"],
            error=run_result["error"],
            items_count=run_result["items_count"],
            usage=run_result["usage"],
            model=runtime.model,
            effort=runtime.effort,
            service_tier=runtime.service_tier,
            cwd=runtime.cwd,
        )


def _build_input_items(sdk: dict[str, Any], context: CodexInputContext) -> list[Any]:
    """Build SDK input items in the exact order callers expect."""
    items = [sdk["TextInput"](context.prompt)]
    items.extend(sdk["SkillInput"](name=skill.name, path=skill.path) for skill in context.skills)
    items.extend(sdk["MentionInput"](name=mention.name, path=mention.path) for mention in context.mentions)
    items.extend(sdk["LocalImageInput"](path=str(path)) for path in context.local_images)
    items.extend(sdk["ImageInput"](url) for url in context.remote_images)
    return items


async def _collect_turn_result(sdk: dict[str, Any], turn: Any) -> dict[str, Any]:
    """Collect final text, status, items, and usage from one turn stream."""
    completed = None
    items = []
    usage = None

    async for event in turn.stream():
        payload = event.payload
        if isinstance(payload, sdk["ItemCompletedNotification"]) and payload.turn_id == turn.id:
            items.append(payload.item)
            continue
        if isinstance(payload, sdk["ThreadTokenUsageUpdatedNotification"]) and payload.turn_id == turn.id:
            usage = payload.token_usage
            continue
        if isinstance(payload, sdk["TurnCompletedNotification"]) and payload.turn.id == turn.id:
            completed = payload

    if completed is None:
        raise RuntimeError("turn completed event not received")

    status = getattr(completed.turn.status, "value", str(completed.turn.status))
    error = _turn_error_text(completed.turn)
    if status == "failed":
        raise RuntimeError(error or "turn failed")

    return {
        "final_response": _final_assistant_response_from_items(items) or "",
        "status": status,
        "error": error,
        "items_count": len(items),
        "usage": usage,
    }


def _final_assistant_response_from_items(items: list[Any]) -> str | None:
    """Return the final assistant message from completed thread items."""
    last_unknown_phase_response: str | None = None
    for item in reversed(items):
        raw_item = item.root if hasattr(item, "root") else item
        if raw_item.__class__.__name__ != "AgentMessageThreadItem":
            continue
        text = getattr(raw_item, "text", None)
        phase = getattr(getattr(raw_item, "phase", None), "value", getattr(raw_item, "phase", None))
        if phase == "final_answer":
            return text
        if phase is None and last_unknown_phase_response is None:
            last_unknown_phase_response = text
    return last_unknown_phase_response


def _turn_error_text(turn: Any) -> str | None:
    error = getattr(turn, "error", None)
    if error is None:
        return None
    message = getattr(error, "message", None)
    return str(message or error)


def _build_sandbox_policy(sdk: dict[str, Any], runtime: CodexRuntimeConfig) -> Any:
    """Build the Codex sandbox policy for one turn."""
    if runtime.sandbox_writable_roots is None:
        return sdk["SandboxPolicy"](
            root=sdk["DangerFullAccessSandboxPolicy"](type="dangerFullAccess")
        )

    return sdk["SandboxPolicy"](
        root=sdk["WorkspaceWriteSandboxPolicy"](
            type="workspaceWrite",
            writable_roots=[str(root) for root in runtime.sandbox_writable_roots],
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
            AppServerConfig,
            AsyncAppServerClient,
            AsyncCodex,
            AskForApproval,
            ImageInput,
            LocalImageInput,
            MentionInput,
            ReasoningEffort,
            SandboxPolicy,
            ServiceTier,
            SkillInput,
            TextInput,
            ThreadTokenUsageUpdatedNotification,
            TurnCompletedNotification,
            is_retryable_error,
        )
        from codex_app_server.generated.v2_all import (
            AppsListResponse,
            DangerFullAccessSandboxPolicy,
            ItemCompletedNotification,
            WorkspaceWriteSandboxPolicy,
        )
    except ImportError as error:
        message = (
            "Codex Python SDK is not installed. Run `uv sync` and make sure "
            "`openai-codex-app-server-sdk` is available in the backend environment."
        )
        raise RuntimeError(message) from error

    return {
        "AppServerConfig": AppServerConfig,
        "AppsListResponse": AppsListResponse,
        "AskForApproval": AskForApproval,
        "AsyncAppServerClient": AsyncAppServerClient,
        "AsyncCodex": AsyncCodex,
        "DangerFullAccessSandboxPolicy": DangerFullAccessSandboxPolicy,
        "ImageInput": ImageInput,
        "ItemCompletedNotification": ItemCompletedNotification,
        "LocalImageInput": LocalImageInput,
        "MentionInput": MentionInput,
        "ReasoningEffort": ReasoningEffort,
        "SandboxPolicy": SandboxPolicy,
        "ServiceTier": ServiceTier,
        "SkillInput": SkillInput,
        "TextInput": TextInput,
        "ThreadTokenUsageUpdatedNotification": ThreadTokenUsageUpdatedNotification,
        "TurnCompletedNotification": TurnCompletedNotification,
        "WorkspaceWriteSandboxPolicy": WorkspaceWriteSandboxPolicy,
        "is_retryable_error": is_retryable_error,
    }
