from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any

from backend.codex_utils import DEFAULT_EFFORT, DEFAULT_MODEL, run_codex_with_context


REPO_ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = REPO_ROOT / "codex_sdk_plugin_probe_result.json"


async def main() -> None:
    prompt = """
We are testing whether a Codex Python SDK/app-server run has access to account
plugins/connectors/apps such as GitHub or Cloudflare.

Safety rules:
- Read-only only.
- Do not create, update, delete, deploy, push, comment, open PRs, change DNS,
  change Workers, change repositories, or mutate any external service.
- Do not print tokens, account IDs, private repo lists, Cloudflare zone IDs, or
  other secrets.
- Do not infer plugin availability from local config files or shell commands.
  This test is about tools visible inside this Codex run.

Task:
1. Check whether this run exposes any plugin/app/connector tool discovery.
2. Check whether GitHub tools are visible. If a harmless authenticated read-only
   GitHub check is available, use it and only report whether it succeeded.
3. Check whether Cloudflare tools are visible. If a harmless authenticated
   read-only Cloudflare check is available, use it and only report whether it
   succeeded.
4. If no such tools are available, say so clearly.

Return only JSON with this shape:
{
  "tool_discovery_available": true_or_false_or_unknown,
  "github_tools_visible": true_or_false_or_unknown,
  "github_authenticated_read_succeeded": true_or_false_or_null,
  "cloudflare_tools_visible": true_or_false_or_unknown,
  "cloudflare_authenticated_read_succeeded": true_or_false_or_null,
  "evidence": ["short sanitized bullets"],
  "conclusion": "one sentence"
}
""".strip()

    result = await run_codex_with_context(
        prompt,
        model=DEFAULT_MODEL,
        effort=DEFAULT_EFFORT,
        cwd=REPO_ROOT,
    )

    payload = {
        "final_response": result.final_response,
        "items_count": result.items_count,
    }
    RESULT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _summarize_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        dumped = item.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        dumped = {"repr": repr(item)}

    return _sanitize_item(dumped)


def _sanitize_item(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, child in value.items():
            lower_key = str(key).lower()
            if any(secret in lower_key for secret in ("token", "secret", "key", "auth")):
                sanitized[key] = "[redacted]"
            elif key in {"text", "content", "result", "output"}:
                sanitized[key] = _shorten(child)
            else:
                sanitized[key] = _sanitize_item(child)
        return sanitized

    if isinstance(value, list):
        return [_sanitize_item(item) for item in value[:20]]

    return _shorten(value)


def _shorten(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= 500:
        return value
    return value[:500] + "...[truncated]"


if __name__ == "__main__":
    asyncio.run(main())
