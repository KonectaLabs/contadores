#!/usr/bin/env bash
set -euo pipefail

dry_run=0
include_codex_home=0
output_dir=""

while (($#)); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --include-codex-home) include_codex_home=1 ;;
    --output-dir)
      shift
      output_dir="${1:-}"
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="$repo_root/data"
if [[ ! -d "$data_dir" ]]; then
  echo "missing data directory: $data_dir" >&2
  exit 1
fi

paths=(
  "database.sqlite"
  "database.sqlite-wal"
  "database.sqlite-shm"
  "bot-webhook-inbox.sqlite"
  "funnels.json"
  "client-lead-sources.json"
  "contadores"
  "workstation"
  "platform"
  "agent-runs"
  "agent-memory"
)
if [[ "$include_codex_home" == "1" ]]; then
  paths+=("codex-home")
fi

existing=()
for path in "${paths[@]}"; do
  [[ -e "$data_dir/$path" ]] && existing+=("$path")
done

if [[ "${#existing[@]}" == "0" ]]; then
  echo "no known data paths found under $data_dir" >&2
  exit 1
fi

printf 'data volume paths:\n'
printf '  %s\n' "${existing[@]}"

if [[ "$dry_run" == "1" ]]; then
  exit 0
fi

if [[ -z "$output_dir" ]]; then
  echo "pass --output-dir outside the repo; backup archives are not written into the worktree by default" >&2
  exit 2
fi

mkdir -p "$output_dir"
archive="$output_dir/contadores-data-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
(
  cd "$data_dir"
  tar -czf "$archive" "${existing[@]}"
)
echo "$archive"
