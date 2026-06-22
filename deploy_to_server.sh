#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
ssh -p 5389 root@149.50.136.121 'bash -s' <<'EOF'
set -euo pipefail

cd /root/projects/contadores

fail() {
  echo "Deploy failed: $*" >&2
  echo "docker compose ps:" >&2
  docker compose ps >&2 || true
  echo "recent backend logs:" >&2
  docker compose logs --tail=80 backend >&2 || true
  echo "recent bot logs:" >&2
  docker compose logs --tail=80 bot >&2 || true
  exit 1
}

require_clean_worktree() {
  local status
  status="$(git status --porcelain)"
  if [ -n "$status" ]; then
    echo "Server worktree is dirty; refusing to deploy."
    echo "git status --short:"
    git status --short
    exit 1
  fi
}

require_file() {
  local path="$1"
  local label="$2"
  if [ ! -f "$path" ]; then
    echo "Missing /root/projects/contadores/$path. Provision Contadores/Konecta $label before deploy." >&2
    exit 1
  fi
}

reject_cross_project_fallbacks() {
  local matches
  matches="$(grep -E -l "konecta-auditor|/root/projects/(cleverapply|clever-apply|konecta-auditor)|cleverapply-gws|@cleverapply\\.com" \
    .env auth.toml || true)"
  if [ -n "$matches" ]; then
    echo "Forbidden cross-project credential fallback reference found in:" >&2
    printf '%s\n' "$matches" >&2
    exit 1
  fi
}

prune_docker_disk() {
  docker image prune --all --force >/dev/null
  docker buildx prune --all --force >/dev/null
}

require_free_disk_for_build() {
  local available_kb
  available_kb="$(df -Pk / | awk 'NR == 2 { print $4 }')"
  if [ "${available_kb:-0}" -lt 5242880 ]; then
    fail "server disk has less than 5GB free after Docker prune"
  fi
}

service_json() {
  docker compose ps --format json "$1" 2>/dev/null | tail -n 1
}

wait_for_service() {
  local service="$1"
  local deadline=$((SECONDS + 180))
  local info status health
  while true; do
    info="$(service_json "$service")"
    if [ -n "$info" ]; then
      status="$(printf '%s' "$info" | python -c 'import json,sys; data=json.load(sys.stdin); print((data.get("State") or data.get("Status") or "").lower())' 2>/dev/null || true)"
      health="$(printf '%s' "$info" | python -c 'import json,sys; print((json.load(sys.stdin).get("Health") or "").lower())' 2>/dev/null || true)"
      if [ "$status" = "running" ] && { [ -z "$health" ] || [ "$health" = "healthy" ]; }; then
        return
      fi
      if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
        fail "$service is $status"
      fi
    fi
    [ "$SECONDS" -lt "$deadline" ] || fail "$service did not become healthy before timeout"
    sleep 2
  done
}

check_backend_from_docker_network() {
  docker compose exec -T backend python -c \
    "import urllib.request; urllib.request.urlopen('http://backend:8000/health', timeout=5)" \
    || fail "backend health failed from Docker network"
}

check_public_health() {
  curl -fsS https://crm.fgoiriz.com/health >/dev/null \
    || fail "public health failed: https://crm.fgoiriz.com/health"
}

require_clean_worktree
git checkout main
git pull --ff-only
require_clean_worktree
require_file .env "environment config"
require_file auth.toml "auth config"
reject_cross_project_fallbacks
prune_docker_disk
require_free_disk_for_build
docker compose build
docker compose up -d
docker compose ps
wait_for_service traefik
wait_for_service backend
wait_for_service bot
check_backend_from_docker_network
check_public_health
prune_docker_disk
EOF
