#!/usr/bin/env python3
"""Sync local CRM follow-up runner status to the production backoffice."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_STATUS_URL = "https://crm.fgoiriz.com/api/contadores/followup/runner/status"
DEFAULT_HOST_HEADER = "crm.fgoiriz.com"
TEXT_FIELD_LIMIT = 12000
LOG_FIELD_LIMIT = 8000
DELTA_TEXT_LIMIT = 24000
DELTA_EVENT_LIMIT = 80

SECRET_RE = re.compile(
    r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]+|"
    r"\b([a-z0-9_]*(?:token|secret|api[_-]?key)[a-z0-9_]*=)[^&\s'\"<>]+"
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
URL_QUERY_RE = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\\s\"'<>]+")
LOCAL_PATH_RE = re.compile(r"(?<!\w)/(?:Users|private|tmp|var|app|data)/[^\s\"'<>]+")


def read_text(path: Path) -> str:
    """Read a local text artifact if it exists."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_tail(path: Path, max_lines: int) -> str:
    """Read the last lines of a local text artifact."""
    text = read_text(path)
    if not text:
        return ""
    return "\n".join(text.splitlines()[-max_lines:])


def read_json(path: Path) -> dict[str, object] | None:
    """Read a JSON object artifact if it exists."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    suffix = digits[-4:] if len(digits) >= 4 else digits
    return f"[phone:*{suffix}]"


def redact_text(value: object) -> str:
    """Redact obvious secrets and contact details from synced diagnostics."""
    text = str(value or "")
    text = URL_QUERY_RE.sub(r"\1?[redacted]", text)
    text = SECRET_RE.sub(lambda m: f"{m.group(1) or m.group(2)}[redacted]", text)
    text = EMAIL_RE.sub("[email:redacted]", text)
    text = PHONE_RE.sub(_mask_phone, text)
    text = LOCAL_PATH_RE.sub("[local-path:redacted]", text)
    return text


def limit_text(value: object, limit: int) -> str:
    """Return redacted text capped to a predictable size."""
    text = redact_text(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[truncated]"


def sanitize_json(value: object, *, limit: int = DELTA_TEXT_LIMIT) -> dict[str, object] | None:
    """Redact and bound one JSON object through a simple JSON round-trip."""
    if not isinstance(value, dict):
        return None
    clean = dict(value)
    events = clean.get("events")
    if isinstance(events, list):
        clean["events"] = events[:DELTA_EVENT_LIMIT]
        if len(events) > DELTA_EVENT_LIMIT:
            clean["events_truncated"] = len(events) - DELTA_EVENT_LIMIT
    text = limit_text(json.dumps(clean, ensure_ascii=True, default=str), limit)
    try:
        decoded = json.loads(text.removesuffix("\n[truncated]"))
    except json.JSONDecodeError:
        return {"summary": text}
    if text.endswith("\n[truncated]"):
        decoded["_truncated"] = True
    return decoded if isinstance(decoded, dict) else {"summary": text}


def parse_pid(path: Path) -> int | None:
    """Read a positive integer pid from a file."""
    raw_value = read_text(path).strip()
    if not raw_value:
        return None
    try:
        pid = int(raw_value)
    except ValueError:
        return None
    return pid if pid > 0 else None


def lock_age_seconds(lock_dir: Path) -> int | None:
    """Return the lock age if the lock exists."""
    if not lock_dir.exists():
        return None
    try:
        return max(0, int(datetime.now(timezone.utc).timestamp() - lock_dir.stat().st_mtime))
    except OSError:
        return None


def utc_now_seconds() -> str:
    """Return a compact UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_payload(root: Path, status: str, active_log: Path | None, tail_lines: int) -> dict[str, object]:
    """Build the status payload from the runner artifacts."""
    reports_dir = root / "data" / "reports"
    lock_dir = root / "data" / "locks" / "contadores-crm-hourly-followup.lock"
    latest_summary_path = reports_dir / "contadores-crm-followup-latest.md"
    latest_delta_path = reports_dir / "contadores-crm-followup-delta-latest.json"
    latest_log_path = active_log if active_log and active_log.exists() else latest_timestamped_log(reports_dir)
    return {
        "status": status,
        "source": "local_launchd",
        "generated_at": utc_now_seconds(),
        "running": status == "running",
        "pid": parse_pid(lock_dir / "pid") if lock_dir.exists() else None,
        "started_at": read_text(lock_dir / "started_at").strip() or None,
        "lock_age_seconds": lock_age_seconds(lock_dir),
        "latest_summary": limit_text(read_text(latest_summary_path), TEXT_FIELD_LIMIT),
        "runner_delta": sanitize_json(read_json(latest_delta_path)),
        "latest_log_tail": limit_text(read_tail(latest_log_path, tail_lines), LOG_FIELD_LIMIT) if latest_log_path else "",
        "launchd_out_tail": limit_text(read_tail(reports_dir / "launchd-contadores-crm-followup.out.log", tail_lines), LOG_FIELD_LIMIT),
        "launchd_err_tail": limit_text(read_tail(reports_dir / "launchd-contadores-crm-followup.err.log", tail_lines), LOG_FIELD_LIMIT),
    }


def latest_timestamped_log(reports_dir: Path) -> Path | None:
    """Return the newest timestamped runner log."""
    if not reports_dir.exists():
        return None
    log_paths = sorted(
        reports_dir.glob("contadores-crm-followup-*.log"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    return log_paths[0] if log_paths else None


def post_status(payload: dict[str, object], *, url: str, host_header: str, token: str, timeout: int) -> None:
    """POST the status payload to the production API."""
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Token": token,
    }
    if host_header:
        headers["Host"] = host_header
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status >= 400:
            raise RuntimeError(f"status sync failed with HTTP {response.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/Users/fgoiriz/private/repos/contadores")
    parser.add_argument("--status", default="completed", choices=["running", "completed", "failed"])
    parser.add_argument("--active-log", default="")
    parser.add_argument("--tail-lines", type=int, default=120)
    parser.add_argument("--url", default=os.getenv("CONTADORES_RUNNER_STATUS_URL", DEFAULT_STATUS_URL))
    parser.add_argument(
        "--host",
        default=os.getenv("CONTADORES_RUNNER_SERVER_HOST", os.getenv("CONTADORES_RUNNER_STATUS_HOST", DEFAULT_HOST_HEADER)),
    )
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args()


def unsafe_http_url(url: str) -> bool:
    """Return True for non-local plain HTTP runner sync targets."""
    if not url.startswith("http://"):
        return False
    return not url.startswith(("http://127.0.0.1/", "http://localhost/", "http://0.0.0.0/"))


def main() -> int:
    args = parse_args()
    token = (os.getenv("INTERNAL_API_TOKEN") or "").strip()
    if not token:
        print("runner_status_sync=skipped reason=missing_internal_token")
        return 0
    if unsafe_http_url(args.url) and os.getenv("CONTADORES_RUNNER_ALLOW_INSECURE_HTTP") != "1":
        print("runner_status_sync=skipped reason=insecure_http_target")
        return 0
    active_log = Path(args.active_log) if args.active_log else None
    payload = build_payload(Path(args.root), args.status, active_log, max(1, args.tail_lines))
    try:
        post_status(payload, url=args.url, host_header=args.host, token=token, timeout=args.timeout)
    except (OSError, urllib.error.URLError, RuntimeError) as exc:
        print(f"runner_status_sync=failed reason={type(exc).__name__}")
        return 0
    print(f"runner_status_sync=ok status={args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
