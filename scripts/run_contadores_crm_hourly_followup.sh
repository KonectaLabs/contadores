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
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$REPORT_DIR/contadores-crm-followup-$RUN_ID.log"
LAST_MESSAGE_FILE="$REPORT_DIR/contadores-crm-followup-latest.md"
HISTORY_FILE="$REPORT_DIR/contadores-crm-followup-history.md"
RUN_RECORD_DIR="$REPORT_DIR/contadores-crm-followup-runs"
LATEST_SNAPSHOT_FILE="$REPORT_DIR/contadores-crm-followup-snapshot-latest.json"
PREVIOUS_SNAPSHOT_FILE="$REPORT_DIR/contadores-crm-followup-snapshot-previous.json"
SNAPSHOT_BEFORE_FILE="$RUN_RECORD_DIR/$RUN_ID-before.json"
SNAPSHOT_AFTER_FILE="$RUN_RECORD_DIR/$RUN_ID-after.json"
DELTA_CURRENT_FILE="$REPORT_DIR/contadores-crm-followup-delta-current.json"
DELTA_CURRENT_MARKDOWN_FILE="$REPORT_DIR/contadores-crm-followup-delta-current.md"
DELTA_LATEST_FILE="$REPORT_DIR/contadores-crm-followup-delta-latest.json"
DELTA_LATEST_MARKDOWN_FILE="$REPORT_DIR/contadores-crm-followup-delta-latest.md"
DELTA_RUN_FILE="$RUN_RECORD_DIR/$RUN_ID-delta.json"
DELTA_RUN_MARKDOWN_FILE="$RUN_RECORD_DIR/$RUN_ID-delta.md"
PROMPT_FILE="$ROOT_DIR/.codex/skills/contadores-crm-followup-automation/references/automation-prompt.md"
RUNNER_STATUS_SYNC_SCRIPT="$ROOT_DIR/scripts/sync_contadores_crm_runner_status.py"
RUNNER_DASHBOARD_SCRIPT="$ROOT_DIR/scripts/render_contadores_crm_runner_dashboard.py"
RUNNER_DELTA_SCRIPT="$ROOT_DIR/scripts/build_contadores_crm_runner_delta.py"

SNAPSHOT_URL="http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"

mkdir -p "$REPORT_DIR" "$LOCK_PARENT" "$RUN_RECORD_DIR"
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

sync_runner_status() {
  local status="$1"
  append_runner_history "$status"
  if [ -x "$RUNNER_DASHBOARD_SCRIPT" ]; then
    python3 "$RUNNER_DASHBOARD_SCRIPT" \
      --root "$ROOT_DIR" \
      --status "$status" \
      --active-log "$LOG_FILE" || true
  fi
  if [ -x "$RUNNER_STATUS_SYNC_SCRIPT" ]; then
    python3 "$RUNNER_STATUS_SYNC_SCRIPT" \
      --root "$ROOT_DIR" \
      --status "$status" \
      --active-log "$LOG_FILE" || true
  fi
}

append_runner_history() {
  local status="$1"
  if [ "$status" = "running" ]; then
    return
  fi
  local marker="<!-- runner-log:$LOG_FILE:$status -->"
  if [ -f "$HISTORY_FILE" ] && grep -Fq "$marker" "$HISTORY_FILE"; then
    return
  fi
  {
    if [ -s "$HISTORY_FILE" ]; then
      printf '\n\n'
    fi
    printf '%s\n\n' "$marker"
    printf '## %s - %s\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$status"
    if [ -s "$LAST_MESSAGE_FILE" ]; then
      cat "$LAST_MESSAGE_FILE"
    else
      printf 'No final summary was written for this run.\n'
    fi
    printf '\n'
  } >> "$HISTORY_FILE"
}

fetch_followup_snapshot() {
  local output_file="$1"
  curl -fsS \
    -H "Host: crm.fgoiriz.com" \
    -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
    "$SNAPSHOT_URL" \
    -o "$output_file"
}

build_runner_delta() {
  local current_snapshot="$1"
  local status="$2"
  local output_json="$3"
  local output_md="$4"
  if [ ! -x "$RUNNER_DELTA_SCRIPT" ] && [ ! -f "$RUNNER_DELTA_SCRIPT" ]; then
    return
  fi
  local previous_arg=()
  if [ -s "$LATEST_SNAPSHOT_FILE" ]; then
    previous_arg=(--previous "$LATEST_SNAPSHOT_FILE")
  fi
  python3 "$RUNNER_DELTA_SCRIPT" \
    "${previous_arg[@]}" \
    --current "$current_snapshot" \
    --summary "$LAST_MESSAGE_FILE" \
    --status "$status" \
    --output-json "$output_json" \
    --output-md "$output_md" || true
}

promote_latest_snapshot() {
  local current_snapshot="$1"
  if [ -s "$LATEST_SNAPSHOT_FILE" ]; then
    cp "$LATEST_SNAPSHOT_FILE" "$PREVIOUS_SNAPSHOT_FILE"
  fi
  cp "$current_snapshot" "$LATEST_SNAPSHOT_FILE"
}

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

sync_runner_status running

if ! fetch_followup_snapshot "$SNAPSHOT_BEFORE_FILE"; then
  echo "preflight_snapshot=failed"
  sync_runner_status failed
  exit 1
fi

echo "preflight_snapshot=ok"
build_runner_delta "$SNAPSHOT_BEFORE_FILE" running "$DELTA_CURRENT_FILE" "$DELTA_CURRENT_MARKDOWN_FILE"
if [ -s "$DELTA_CURRENT_FILE" ]; then
  cp "$DELTA_CURRENT_FILE" "$DELTA_LATEST_FILE"
fi
if [ -s "$DELTA_CURRENT_MARKDOWN_FILE" ]; then
  cp "$DELTA_CURRENT_MARKDOWN_FILE" "$DELTA_LATEST_MARKDOWN_FILE"
fi
sync_runner_status running

export CONTADORES_CRM_FOLLOWUP_RUNNER=1
export CONTADORES_CRM_FOLLOWUP_LOCK_DIR="$LOCK_DIR"
export CONTADORES_CRM_FOLLOWUP_LOG_FILE="$LOG_FILE"
export CONTADORES_CRM_FOLLOWUP_DELTA_FILE="$DELTA_CURRENT_MARKDOWN_FILE"

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
  if fetch_followup_snapshot "$SNAPSHOT_AFTER_FILE"; then
    build_runner_delta "$SNAPSHOT_AFTER_FILE" failed "$DELTA_RUN_FILE" "$DELTA_RUN_MARKDOWN_FILE"
    cp "$DELTA_RUN_FILE" "$DELTA_LATEST_FILE" 2>/dev/null || true
    cp "$DELTA_RUN_MARKDOWN_FILE" "$DELTA_LATEST_MARKDOWN_FILE" 2>/dev/null || true
    promote_latest_snapshot "$SNAPSHOT_AFTER_FILE"
  fi
  sync_runner_status failed
  exit "$codex_status"
fi

echo "finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "last_message=$LAST_MESSAGE_FILE"
if fetch_followup_snapshot "$SNAPSHOT_AFTER_FILE"; then
  build_runner_delta "$SNAPSHOT_AFTER_FILE" completed "$DELTA_RUN_FILE" "$DELTA_RUN_MARKDOWN_FILE"
  cp "$DELTA_RUN_FILE" "$DELTA_LATEST_FILE" 2>/dev/null || true
  cp "$DELTA_RUN_MARKDOWN_FILE" "$DELTA_LATEST_MARKDOWN_FILE" 2>/dev/null || true
  promote_latest_snapshot "$SNAPSHOT_AFTER_FILE"
else
  echo "post_run_snapshot=failed"
fi
sync_runner_status completed
