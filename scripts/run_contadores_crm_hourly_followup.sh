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

SNAPSHOT_URL="${CONTADORES_RUNNER_SNAPSHOT_URL:-https://crm.fgoiriz.com/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12}"
RUNNER_SERVER_HOST="${CONTADORES_RUNNER_SERVER_HOST:-${CONTADORES_RUNNER_STATUS_HOST:-crm.fgoiriz.com}}"
RUNNER_ALLOW_INSECURE_HTTP="${CONTADORES_RUNNER_ALLOW_INSECURE_HTTP:-0}"
RUNNER_REPORT_RETENTION_DAYS="${CONTADORES_RUNNER_REPORT_RETENTION_DAYS:-30}"
RUNNER_RUN_RECORD_KEEP="${CONTADORES_RUNNER_RUN_RECORD_KEEP:-72}"
RUNNER_PRUNE_DRY_RUN="${CONTADORES_RUNNER_PRUNE_DRY_RUN:-0}"
PRUNE_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --prune-only)
      PRUNE_ONLY=1
      ;;
    --dry-run)
      RUNNER_PRUNE_DRY_RUN=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$REPORT_DIR" "$LOCK_PARENT" "$RUN_RECORD_DIR"
cd "$ROOT_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

cleanup() {
  if [ "$(cat "$LOCK_DIR/pid" 2>/dev/null || true)" = "$$" ]; then
    rm -rf "$LOCK_DIR"
  fi
  if [ -n "${CONTADORES_CRM_RUNNER_TEMP:-}" ]; then
    rm -f "$CONTADORES_CRM_RUNNER_TEMP"
  fi
}

echo "== Contadores CRM follow-up run =="
echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "root=$ROOT_DIR"
echo "log=$LOG_FILE"

if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
fi

export INTERNAL_API_TOKEN="${INTERNAL_API_TOKEN:-}"
export CONTADORES_RUNNER_STATUS_URL="${CONTADORES_RUNNER_STATUS_URL:-https://crm.fgoiriz.com/api/contadores/followup/runner/status}"
export CONTADORES_RUNNER_SERVER_HOST="$RUNNER_SERVER_HOST"
export CONTADORES_RUNNER_ALLOW_INSECURE_HTTP="$RUNNER_ALLOW_INSECURE_HTTP"

is_local_http_url() {
  case "$1" in
    http://127.0.0.1/*|http://localhost/*|http://0.0.0.0/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

require_safe_runner_url() {
  local url="$1"
  local label="$2"
  if [ -z "$url" ]; then
    echo "Blocked: $label is empty." >&2
    exit 1
  fi
  case "$url" in
    https://*)
      return
      ;;
    http://*)
      if is_local_http_url "$url" || [ "$RUNNER_ALLOW_INSECURE_HTTP" = "1" ]; then
        echo "runner_target_warning=$label uses HTTP; insecure override/local target accepted."
        return
      fi
      echo "Blocked: $label uses non-local HTTP. Set CONTADORES_RUNNER_ALLOW_INSECURE_HTTP=1 only for emergency raw-IP routing." >&2
      exit 1
      ;;
    *)
      echo "Blocked: $label must start with https:// or http://." >&2
      exit 1
      ;;
  esac
}

prune_runner_artifacts() {
  local dry_run="$1"
  local retention_days="$2"
  local keep_runs="$3"
  local action="delete"
  if [ "$dry_run" = "1" ]; then
    action="dry-run"
  fi
  echo "runner_prune=$action retention_days=$retention_days keep_run_records=$keep_runs"

  find "$REPORT_DIR" -maxdepth 1 -type f \
    \( -name 'contadores-crm-followup-*.log' -o -name 'contadores-crm-followup-delta-remote-*.json' -o -name 'contadores-crm-followup-remote-*.log' \) \
    -mtime +"$retention_days" -print | while IFS= read -r old_file; do
      if [ "$dry_run" = "1" ]; then
        echo "would_prune=$old_file"
      else
        rm -f "$old_file"
      fi
    done

  find "$ROOT_DIR/data/tmp" -maxdepth 1 -type f -name 'contadores-crm-runner.*.sh' -mtime +1 -print 2>/dev/null | while IFS= read -r temp_file; do
    if [ "$dry_run" = "1" ]; then
      echo "would_prune=$temp_file"
    else
      rm -f "$temp_file"
    fi
  done

  ls -1t "$RUN_RECORD_DIR"/* 2>/dev/null | awk "NR>$keep_runs" | while IFS= read -r run_file; do
    if [ "$dry_run" = "1" ]; then
      echo "would_prune=$run_file"
    else
      rm -f "$run_file"
    fi
  done

  if [ "$dry_run" != "1" ] && [ -f "$HISTORY_FILE" ]; then
    tail -c 200000 "$HISTORY_FILE" > "$HISTORY_FILE.tmp"
    mv "$HISTORY_FILE.tmp" "$HISTORY_FILE"
  fi
}

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
    env -i \
      HOME="$HOME" \
      PATH="$PATH" \
      INTERNAL_API_TOKEN="$INTERNAL_API_TOKEN" \
      CONTADORES_RUNNER_STATUS_URL="$CONTADORES_RUNNER_STATUS_URL" \
      CONTADORES_RUNNER_SERVER_HOST="$RUNNER_SERVER_HOST" \
      CONTADORES_RUNNER_ALLOW_INSECURE_HTTP="$RUNNER_ALLOW_INSECURE_HTTP" \
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
  local host_args=()
  if [ -n "$RUNNER_SERVER_HOST" ]; then
    host_args=(-H "Host: $RUNNER_SERVER_HOST")
  fi
  env -i PATH="$PATH" curl -fsS \
    "${host_args[@]}" \
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

require_safe_runner_url "$SNAPSHOT_URL" "CONTADORES_RUNNER_SNAPSHOT_URL"
require_safe_runner_url "$CONTADORES_RUNNER_STATUS_URL" "CONTADORES_RUNNER_STATUS_URL"
echo "snapshot_url=$SNAPSHOT_URL"
echo "runner_status_url=$CONTADORES_RUNNER_STATUS_URL"

if [ "$PRUNE_ONLY" = "1" ]; then
  prune_runner_artifacts "$RUNNER_PRUNE_DRY_RUN" "$RUNNER_REPORT_RETENTION_DAYS" "$RUNNER_RUN_RECORD_KEEP"
  exit 0
fi

if [ -d "$LOCK_DIR" ]; then
  lock_age_seconds=$(( "$(date +%s)" - "$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)" ))
  lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
    if [ "$lock_age_seconds" -ge 21600 ]; then
      echo "Another CRM follow-up run is overdue but still live under pid $lock_pid; leaving lock in place."
    else
      echo "Another CRM follow-up run is still active under pid $lock_pid."
    fi
    exit 0
  fi
  echo "Clearing stale CRM follow-up lock age_seconds=$lock_age_seconds pid=${lock_pid:-missing}."
  rm -rf "$LOCK_DIR"
fi

if ! mkdir "$LOCK_DIR"; then
  echo "Another CRM follow-up run acquired the lock first; skipping this run."
  exit 0
fi
trap cleanup EXIT
printf '%s\n' "$$" > "$LOCK_DIR/pid"
date -u +%Y-%m-%dT%H:%M:%SZ > "$LOCK_DIR/started_at"

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

# LaunchAgent has no interactive approval surface, so keep the bypass but do not pass the full .env.
env -i \
  HOME="$HOME" \
  CODEX_HOME="$CODEX_HOME" \
  PATH="$PATH" \
  INTERNAL_API_TOKEN="$INTERNAL_API_TOKEN" \
  CONTADORES_CRM_FOLLOWUP_RUNNER="$CONTADORES_CRM_FOLLOWUP_RUNNER" \
  CONTADORES_CRM_FOLLOWUP_LOCK_DIR="$CONTADORES_CRM_FOLLOWUP_LOCK_DIR" \
  CONTADORES_CRM_FOLLOWUP_LOG_FILE="$CONTADORES_CRM_FOLLOWUP_LOG_FILE" \
  CONTADORES_CRM_FOLLOWUP_DELTA_FILE="$CONTADORES_CRM_FOLLOWUP_DELTA_FILE" \
  codex exec \
  -C "$ROOT_DIR" \
  -m gpt-5.5 \
  --dangerously-bypass-approvals-and-sandbox \
  -o "$LAST_MESSAGE_FILE" \
  "$PROMPT" &

codex_pid=$!
(
  sleep 3300
  if kill -0 "$codex_pid" 2>/dev/null; then
    echo "Codex run exceeded 55 minutes; stopping pid $codex_pid." >&2
    kill -TERM "$codex_pid" 2>/dev/null || true
    sleep 20
    if kill -0 "$codex_pid" 2>/dev/null; then
      echo "Codex pid $codex_pid did not stop after TERM; sending KILL." >&2
      kill -KILL "$codex_pid" 2>/dev/null || true
    fi
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
prune_runner_artifacts "$RUNNER_PRUNE_DRY_RUN" "$RUNNER_REPORT_RETENTION_DAYS" "$RUNNER_RUN_RECORD_KEEP"
