#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/Users/fgoiriz/private/repos/contadores"
export HOME="/Users/fgoiriz"
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

if [ "${CONTADORES_CRM_RUNNER_STABLE_COPY:-}" != "1" ]; then
  mkdir -p "$ROOT_DIR/data/tmp"
  stable_runner="$(mktemp "$ROOT_DIR/data/tmp/contadores-crm-runner.XXXXXX.sh")"
  cp "$0" "$stable_runner"
  chmod +x "$stable_runner"
  export CONTADORES_CRM_RUNNER_STABLE_COPY=1
  export CONTADORES_CRM_RUNNER_TEMP="$stable_runner"
  exec "$stable_runner" "$@"
fi

REPORT_DIR="$ROOT_DIR/data/reports"
LOCK_PARENT="$ROOT_DIR/data/locks"
LOCK_DIR="$LOCK_PARENT/contadores-crm-hourly-followup.lock"
LOG_FILE="$REPORT_DIR/contadores-crm-followup-$(date -u +%Y%m%dT%H%M%SZ).log"
LAST_MESSAGE_FILE="$REPORT_DIR/contadores-crm-followup-latest.md"
PROMPT_FILE="$ROOT_DIR/.codex/skills/contadores-crm-followup-automation/references/automation-prompt.md"

SNAPSHOT_URL="http://149.50.136.121/api/contadores/followup/snapshot?limit=1&messages_per_lead=1"

mkdir -p "$REPORT_DIR" "$LOCK_PARENT"
cd "$ROOT_DIR"

if [ -d "$LOCK_DIR" ]; then
  lock_age_seconds=$(( "$(date +%s)" - "$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)" ))
  lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null && [ "$lock_age_seconds" -lt 21600 ]; then
    echo "Another CRM follow-up run is still active under pid $lock_pid."
    exit 0
  fi
  rm -rf "$LOCK_DIR"
fi

cleanup() {
  rm -rf "$LOCK_DIR"
  if [ -n "${CONTADORES_CRM_RUNNER_TEMP:-}" ]; then
    rm -f "$CONTADORES_CRM_RUNNER_TEMP"
  fi
}

mkdir "$LOCK_DIR"
trap cleanup EXIT
printf '%s\n' "$$" > "$LOCK_DIR/pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK_DIR/started_at"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "== Contadores CRM follow-up run =="
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "root=$ROOT_DIR"
echo "log=$LOG_FILE"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

if [ -z "${INTERNAL_API_TOKEN:-}" ]; then
  echo "Blocked: INTERNAL_API_TOKEN is missing from $ROOT_DIR/.env or environment."
  exit 1
fi

PROMPT="$(python3 - "$PROMPT_FILE" <<'PY'
from pathlib import Path
import sys

text = Path(sys.argv[1]).read_text()
start = text.find("```text")
if start == -1:
    raise SystemExit("prompt fence not found")
start = text.find("\n", start) + 1
end = text.find("```", start)
if end == -1:
    raise SystemExit("prompt fence end not found")
print(text[start:end].strip())
PY
)"

curl -fsS \
  -H "Host: contadores.fgoiriz.com" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "$SNAPSHOT_URL" >/dev/null

echo "preflight_snapshot=ok"

export CONTADORES_CRM_FOLLOWUP_RUNNER=1
export CONTADORES_CRM_FOLLOWUP_LOCK_DIR="$LOCK_DIR"
export CONTADORES_CRM_FOLLOWUP_LOG_FILE="$LOG_FILE"

codex exec \
  -C "$ROOT_DIR" \
  -m gpt-5.5 \
  --dangerously-bypass-approvals-and-sandbox \
  -c shell_environment_policy.inherit=all \
  -o "$LAST_MESSAGE_FILE" \
  "$PROMPT" &

codex_pid=$!
(
  sleep 3300
  if kill -0 "$codex_pid" 2>/dev/null; then
    echo "Codex run exceeded 55 minutes; stopping pid $codex_pid." >&2
    kill "$codex_pid" 2>/dev/null || true
  fi
) &
watchdog_pid=$!

set +e
wait "$codex_pid"
codex_status=$?
set -e
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true

if [ "$codex_status" -ne 0 ]; then
  echo "Codex run failed with status $codex_status."
  exit "$codex_status"
fi

echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "last_message=$LAST_MESSAGE_FILE"
