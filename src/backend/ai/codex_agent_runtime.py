"""Autonomous Codex runtime with audited product tools."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.codex_utils import CodexSkill, CodexTurnResult, run_codex_with_context
from backend.config import (
    CONVERSATION_BOT_CODEX_API_KEY_HOME,
    CONVERSATION_BOT_CODEX_CHATGPT_HOME,
    CONVERSATION_BOT_CODEX_EFFORT,
    CONVERSATION_BOT_CODEX_MODEL,
    CONVERSATION_BOT_CODEX_SERVICE_TIER,
    OPENAI_API_KEY,
)
from backend.database import AgentRun, AgentToolCall, DATA_DIR


REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT_RUNS_DIR = DATA_DIR / "agent-runs"
TOOL_RUNNER_MODULE = "backend.ai.codex_agent_runtime"


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
    path = AGENT_RUNS_DIR / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


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
) -> str:
    """Build the employee-style prompt that teaches Codex how to act with tools."""
    manifest = json.dumps(build_tool_manifest(tool_specs), ensure_ascii=True, indent=2)
    return f"""
You are Codex acting as an internal Konecta employee.

Your job is to decide and do the most useful next action for the client or lead.
You are not a JSON classifier. Use judgment. Sometimes the right action is a
short answer, sometimes a clarifying question, sometimes page work, sometimes a
future follow-up, and sometimes a human handoff.

Run id:
{run_id}

Objective:
{objective.strip()}

Context:
{context_md.strip()}

Available product tools:
```json
{manifest}
```

How to use tools:
- Actually call the tool runner when you decide to act.
- Command shape:
  uv run python -m {TOOL_RUNNER_MODULE} call --run-id {run_id} --tool TOOL_NAME --arguments-json 'JSON_OBJECT'
- Tool calls are audited and are the product side effects.
- You may call more than one tool if that is best for the client.
- Use short, natural WhatsApp messages. Avoid spam.
- Use schedule_followup instead of sleeping or creating OS cron jobs.
- If a tool returns an error, adapt using the error. Do not bypass product rules.
- If no side effect is appropriate, do not call a tool and explain briefly why.

Finish with a short internal summary of what you did.
""".strip()


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
    run_id = uuid.uuid4().hex
    context_dir = run_context_dir(run_id)
    context_path = context_dir / "context.md"
    manifest_path = context_dir / "tools.json"
    context_path.write_text(context_md.strip() + "\n", encoding="utf-8")
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
    )
    selected_skills = skills or []
    try:
        try:
            codex_result = await _run_codex_agent_once(
                prompt=prompt,
                skills=selected_skills,
                codex_home=CONVERSATION_BOT_CODEX_CHATGPT_HOME,
                prefer_chatgpt_login=True,
                on_turn_started=on_turn_started,
            )
        except Exception as chatgpt_error:
            if not OPENAI_API_KEY.strip():
                raise
            codex_result = await _run_codex_agent_once(
                prompt=prompt,
                skills=selected_skills,
                codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME,
                prefer_chatgpt_login=False,
                on_turn_started=on_turn_started,
            )
            write_jsonl(
                context_dir / "runtime-events.jsonl",
                {
                    "event": "chatgpt_fallback_to_api_key",
                    "error": f"{chatgpt_error.__class__.__name__}: {chatgpt_error}",
                },
            )
        tool_calls = AgentToolCall.list_by_run(run_id)
        AgentRun.finish(
            run_id,
            status="completed",
            final_response=codex_result.final_response,
            codex_thread_id=codex_result.thread_id,
            codex_turn_id=codex_result.turn_id,
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
            error=f"{error.__class__.__name__}: {error}",
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
    print(json.dumps(result, ensure_ascii=True, default=str))
    return 0 if result.get("ok") else 1


def main() -> int:
    """CLI entrypoint used by Codex during autonomous runs."""
    import sys

    return _call_tool_from_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
