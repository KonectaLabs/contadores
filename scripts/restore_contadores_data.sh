#!/usr/bin/env bash
set -euo pipefail

archive=""
target_dir=""
yes=0

while (($#)); do
  case "$1" in
    --archive)
      shift
      archive="${1:-}"
      ;;
    --target-dir)
      shift
      target_dir="${1:-}"
      ;;
    --yes) yes=1 ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target_dir="${target_dir:-$repo_root/data}"

if [[ -z "$archive" || ! -f "$archive" ]]; then
  echo "usage: $0 --archive /path/to/contadores-data.tar.gz [--target-dir /path/to/data] [--yes]" >&2
  exit 2
fi

if [[ "$yes" != "1" ]]; then
  echo "Stop backend and bot first. Restore will move current data aside and replace: $target_dir" >&2
  echo "Re-run with --yes when ready." >&2
  exit 2
fi

if [[ -e "$target_dir" ]]; then
  backup_dir="${target_dir}.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
  mv "$target_dir" "$backup_dir"
  echo "moved current data to $backup_dir"
fi

mkdir -p "$target_dir"
tar -xzf "$archive" -C "$target_dir"
echo "restored $archive into $target_dir"
echo "verify ownership, start services, then run server smoke checks"
