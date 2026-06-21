"""Autonomous Codex runtime with audited product tools."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import backend.database as database_module
from backend.codex_utils import CodexSkill, CodexTurnResult, run_codex_with_context
from backend.config import (
    CODEX_BACKEND_ENABLED,
    CODEX_PREFER_CHATGPT_LOGIN,
    CONVERSATION_BOT_CODEX_API_KEY_HOME,
    CONVERSATION_BOT_CODEX_CHATGPT_HOME,
    CONVERSATION_BOT_CODEX_EFFORT,
    CONVERSATION_BOT_CODEX_MODEL,
    CONVERSATION_BOT_CODEX_SERVICE_TIER,
    OPENAI_API_KEY,
)
from backend.database import AgentRun, AgentToolCall
from backend.redaction import redact_json, redact_sensitive_text


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_HARNESS_SKILL = REPO_ROOT / ".codex" / "skills" / "contadores-agent-harness" / "SKILL.md"
TOOL_RUNNER_MODULE = "backend.ai.codex_agent_runtime"
AGENT_CONTEXT_RETENTION_DAYS = 30


def _env_int(name: str) -> int:
    try:
        return max(0, int(os.getenv(name, "0") or "0"))
    except ValueError:
        return 0


def normalize_codex_usage(usage: Any, *, model: str = "", provider: str = "codex") -> dict[str, Any]:
    """Return bounded usage metadata, never prompts or responses."""
    if usage is None:
        return {}
    payload = usage if isinstance(usage, dict) else getattr(usage, "__dict__", {})
    if not isinstance(payload, dict):
        return {}
    keys = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_output_tokens",
        "total",
    }
    normalized = {key: int(value) for key, value in payload.items() if key in keys and isinstance(value, int)}
    if "total_tokens" not in normalized and "total" in normalized:
        normalized["total_tokens"] = normalized["total"]
    if model:
        normalized["model"] = model
    normalized["provider"] = provider
    return normalized


def codex_budget_status(usage: dict[str, Any]) -> str:
    """Classify one run against optional token budget env vars."""
    total = int(usage.get("total_tokens") or 0)
    if total <= 0:
        return "unknown"
    hard = _env_int("CODEX_RUN_HARD_TOKEN_BUDGET")
    soft = _env_int("CODEX_RUN_SOFT_TOKEN_BUDGET")
    if hard and total >= hard:
        return "hard_exceeded"
    if soft and total >= soft:
        return "soft_exceeded"
    return "ok"


@dataclass(frozen=True)
class CodexAgentToolSpec:
    """A tool exposed to an autonomous Codex run."""

    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class CodexAgentRunResult:
    """Compact autonomous run result plus audited tool calls."""

    run_id: str
    final_response: str
    tool_calls: list[AgentToolCall]
    codex_result: CodexTurnResult

    @property
    def side_effect_count(self) -> int:
        """Return how many tools succeeded during this run."""
        return len([call for call in self.tool_calls if call.status == "succeeded"])


def run_context_dir(run_id: str) -> Path:
    """Return the persistent audit folder for one agent run."""
    path = database_module.DATA_DIR / "agent-runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_memory_segment(value: str) -> str:
    """Return a filesystem-safe segment while keeping IDs readable."""
    clean = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value.strip())
    return clean[:160] or "unknown"


def agent_memory_path(target_type: str, target_id: str) -> Path:
    """Return the persistent Markdown memory file for one product target."""
    root = database_module.DATA_DIR / "agent-memory" / _safe_memory_segment(target_type)
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{_safe_memory_segment(target_id)}.md"


def _path_age_days(path: Path, *, now: datetime | None = None) -> float:
    current = now or datetime.now(timezone.utc)
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return (current - modified).total_seconds() / 86400


def agent_artifact_retention_report(*, retention_days: int = AGENT_CONTEXT_RETENTION_DAYS) -> dict[str, Any]:
    """Return a dry-run report for agent artifact retention."""
    runs_root = database_module.DATA_DIR / "agent-runs"
    memory_root = database_module.DATA_DIR / "agent-memory"
    run_dirs = [path for path in runs_root.glob("*") if path.is_dir()] if runs_root.exists() else []
    candidates: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        row = AgentRun.get_by_id(run_dir.name)
        if row is None or row.status not in {"completed", "failed"}:
            continue
        age_days = _path_age_days(run_dir)
        if age_days < retention_days:
            continue
        candidates.append(
            {
                "run_id": run_dir.name,
                "status": row.status,
                "age_days": round(age_days, 1),
                "files": sorted(path.name for path in run_dir.iterdir() if path.name in {"context.md", "memory.md", "tools.json"}),
            }
        )
    return {
        "retention_days": retention_days,
        "classes": {
            "audit_metadata": ["agent_runs", "agent_tool_calls"],
            "sensitive_context": ["data/agent-runs/*/context.md", "memory.md", "tools.json"],
            "durable_memory": ["data/agent-memory/**/*.md"],
        },
        "agent_run_dirs": len(run_dirs),
        "agent_memory_files": len(list(memory_root.glob("**/*.md"))) if memory_root.exists() else 0,
        "prune_candidates": candidates,
    }


def prune_agent_run_artifacts(*, retention_days: int = AGENT_CONTEXT_RETENTION_DAYS, dry_run: bool = True) -> dict[str, Any]:
    """Prune old completed/failed run context files; active runs are preserved."""
    report = agent_artifact_retention_report(retention_days=retention_days)
    removed: list[str] = []
    if not dry_run:
        for candidate in report["prune_candidates"]:
            run_dir = database_module.DATA_DIR / "agent-runs" / candidate["run_id"]
            for name in candidate["files"]:
                path = run_dir / name
                if path.exists():
                    path.unlink()
                    removed.append(str(path))
            summary_path = run_dir / "retention-summary.json"
            summary_path.write_text(
                json.dumps({"retention_days": retention_days, "removed_files": candidate["files"]}, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
    report["dry_run"] = dry_run
    report["removed"] = removed
    return report


def read_agent_memory_text(
    *,
    target_type: str,
    target_id: str,
    limit_chars: int = 12000,
) -> str:
    """Read the latest memory text for one product target."""
    path = agent_memory_path(target_type, target_id)
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit_chars <= 0 or len(text) <= limit_chars:
        return text
    return text[-limit_chars:]


def write_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object to an audit JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")


def build_tool_manifest(tool_specs: list[CodexAgentToolSpec]) -> list[dict[str, Any]]:
    """Serialize tool specs for Codex."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "schema": spec.schema,
        }
        for spec in tool_specs
    ]


def build_agent_prompt(
    *,
    run_id: str,
    objective: str,
    context_md: str,
    tool_specs: list[CodexAgentToolSpec],
    memory_md: str = "",
) -> str:
    """Build the employee-style prompt that teaches Codex how to act with tools."""
    manifest = json.dumps(build_tool_manifest(tool_specs), ensure_ascii=True, indent=2)
    return f"""
You are Codex acting as an internal Konecta employee.

Your job is to decide and do the most useful next action for the client or lead.
You are not a JSON classifier. Use judgment. Sometimes the right action is a
short answer, sometimes a clarifying question, sometimes page work, sometimes a
future follow-up, and sometimes a human handoff.

You are allowed to operate through product tools. The tools below are the hands
of the backend: they send WhatsApp messages, move leads, update state, schedule
future wake-ups, write memory, configure funnels/delivery sources, and create
Workstation deliverables. They also record meeting handoffs, client profiles,
ad campaigns, creative assets, typed Meta publish plans/preflights/attempts,
client updates, and operator questions. If a tool is the right way to act, call it. Do
not merely describe the action for someone else to execute.

Run id:
{run_id}

Objective:
{objective.strip()}

Context:
{context_md.strip()}

Persistent memory for this target:
{memory_md.strip() or "(empty)"}

Available product tools:
```json
{manifest}
```

How to use tools:
- Actually call the tool runner when you decide to act.
- Command shape:
  uv run python -m {TOOL_RUNNER_MODULE} call --run-id {run_id} --tool TOOL_NAME --arguments-json 'JSON_OBJECT'
- Tool calls are audited and are the product side effects.
- Live tool calls that write local state or providers require idempotency_key.
  Use a stable key from run id + target id + action + exact content.
- You may call more than one tool if that is best for the client.
- Use read_agent_memory/write_agent_memory for durable notes that the next run
  should know.
- Use short, natural WhatsApp messages. Avoid spam.
- Use schedule_heartbeat or schedule_followup instead of sleeping or creating
  OS cron jobs.
- If a tool returns an error, adapt using the error. Do not bypass product rules.
- If no side effect is appropriate, do not call a tool and explain briefly why.

Finish with a short internal summary for the audit log. The client only sees
messages or media you actually queued through tools.
""".strip()


def add_agent_harness_skill(skills: list[CodexSkill] | None) -> list[CodexSkill]:
    """Load the agent harness skill before task-specific skills."""
    selected: list[CodexSkill] = []
    if AGENT_HARNESS_SKILL.exists():
        selected.append(
            CodexSkill(
                name="contadores-agent-harness",
                path=str(AGENT_HARNESS_SKILL.resolve()),
            )
        )

    seen_names = {skill.name for skill in selected}
    seen_paths = {Path(skill.path).expanduser().resolve() for skill in selected if skill.path}
    for skill in skills or []:
        skill_path = Path(skill.path).expanduser().resolve() if skill.path else Path()
        if skill.name in seen_names or skill_path in seen_paths:
            continue
        selected.append(skill)
        seen_names.add(skill.name)
        if skill.path:
            seen_paths.add(skill_path)
    return selected


async def _run_codex_agent_once(
    *,
    prompt: str,
    skills: list[CodexSkill],
    codex_home: str | None,
    prefer_chatgpt_login: bool,
    on_turn_started=None,
) -> CodexTurnResult:
    """Run one Codex agent attempt."""
    return await run_codex_with_context(
        prompt,
        skills=skills,
        model=CONVERSATION_BOT_CODEX_MODEL,
        effort=CONVERSATION_BOT_CODEX_EFFORT,  # type: ignore[arg-type]
        service_tier=CONVERSATION_BOT_CODEX_SERVICE_TIER,  # type: ignore[arg-type]
        cwd=REPO_ROOT,
        codex_home=codex_home,
        prefer_chatgpt_login=prefer_chatgpt_login,
        on_turn_started=on_turn_started,
    )


async def run_codex_agent(
    *,
    target_type: str,
    target_id: str,
    objective: str,
    context_md: str,
    tool_specs: list[CodexAgentToolSpec],
    skills: list[CodexSkill] | None = None,
    prompt_version: str = "codex-agent-tools-v1",
    on_turn_started=None,
) -> CodexAgentRunResult:
    """Run Codex as an autonomous employee with audited product tools."""
    if not CODEX_BACKEND_ENABLED:
        raise RuntimeError(
            "Codex SDK desactivado (CODEX_BACKEND_ENABLED no es true). "
            "No se ejecuta el agente Codex ni por API key."
        )
    run_id = uuid.uuid4().hex
    context_dir = run_context_dir(run_id)
    context_path = context_dir / "context.md"
    memory_snapshot_path = context_dir / "memory.md"
    manifest_path = context_dir / "tools.json"
    memory_md = read_agent_memory_text(target_type=target_type, target_id=target_id)
    context_path.write_text(context_md.strip() + "\n", encoding="utf-8")
    memory_snapshot_path.write_text(memory_md.strip() + "\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(build_tool_manifest(tool_specs), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    AgentRun.start(
        run_id=run_id,
        agent_kind="codex",
        target_type=target_type,
        target_id=target_id,
        prompt_version=prompt_version,
        context_path=str(context_path),
    )
    prompt = build_agent_prompt(
        run_id=run_id,
        objective=objective,
        context_md=context_md,
        tool_specs=tool_specs,
        memory_md=memory_md,
    )
    selected_skills = add_agent_harness_skill(skills)
    try:
        if CODEX_PREFER_CHATGPT_LOGIN:
            try:
                codex_result = await _run_codex_agent_once(
                    prompt=prompt,
                    skills=selected_skills,
                    codex_home=CONVERSATION_BOT_CODEX_CHATGPT_HOME or None,
                    prefer_chatgpt_login=True,
                    on_turn_started=on_turn_started,
                )
            except Exception as chatgpt_error:
                if not OPENAI_API_KEY.strip():
                    raise
                codex_result = await _run_codex_agent_once(
                    prompt=prompt,
                    skills=selected_skills,
                    codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME or None,
                    prefer_chatgpt_login=False,
                    on_turn_started=on_turn_started,
                )
                write_jsonl(
                    context_dir / "runtime-events.jsonl",
                    {
                        "event": "chatgpt_fallback_to_api_key",
                        "error": redact_sensitive_text(f"{chatgpt_error.__class__.__name__}: {chatgpt_error}", limit=500),
                    },
                )
        else:
            if not OPENAI_API_KEY.strip():
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured for Codex agent runs "
                    "(CODEX_PREFER_CHATGPT_LOGIN is false)."
                )
            codex_result = await _run_codex_agent_once(
                prompt=prompt,
                skills=selected_skills,
                codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME or None,
                prefer_chatgpt_login=False,
                on_turn_started=on_turn_started,
            )
        tool_calls = AgentToolCall.list_by_run(run_id)
        usage = normalize_codex_usage(codex_result.usage, model=codex_result.model)
        AgentRun.finish(
            run_id,
            status="completed",
            final_response=codex_result.final_response,
            codex_thread_id=codex_result.thread_id,
            codex_turn_id=codex_result.turn_id,
            usage=usage,
            budget_status=codex_budget_status(usage),
        )
        return CodexAgentRunResult(
            run_id=run_id,
            final_response=codex_result.final_response,
            tool_calls=tool_calls,
            codex_result=codex_result,
        )
    except Exception as error:
        AgentRun.finish(
            run_id,
            status="failed",
            error=redact_sensitive_text(f"{error.__class__.__name__}: {error}", limit=12000),
        )
        raise


def _call_tool_from_cli(argv: list[str]) -> int:
    """Execute one audited tool call from Codex's shell."""
    import argparse

    parser = argparse.ArgumentParser(description="Run one approved Codex agent tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    call_parser = subparsers.add_parser("call")
    call_parser.add_argument("--run-id", required=True)
    call_parser.add_argument("--tool", required=True)
    call_parser.add_argument("--arguments-json", required=True)
    args = parser.parse_args(argv)

    if args.command != "call":
        raise SystemExit(2)

    from backend.ai.codex_agent_tools import call_tool

    try:
        payload = json.loads(args.arguments_json)
    except json.JSONDecodeError as error:
        payload = {"_json_error": str(error), "_raw": args.arguments_json}
    result = call_tool(run_id=args.run_id, tool_name=args.tool, arguments=payload)
    print(json.dumps(redact_json(result), ensure_ascii=True, default=str))
    return 0 if result.get("ok") else 1


def main() -> int:
    """CLI entrypoint used by Codex during autonomous runs."""
    import sys

    return _call_tool_from_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
