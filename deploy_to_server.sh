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
  if grep -E -l "konecta-auditor|/root/projects/(cleverapply|clever-apply|konecta-auditor)|cleverapply-gws|@cleverapply\\.com" \
    deploy_to_server.sh .env auth.toml >/tmp/contadores-forbidden-config.txt; then
    echo "Forbidden cross-project credential fallback reference found in:" >&2
    cat /tmp/contadores-forbidden-config.txt >&2
    exit 1
  fi
}

service_json() {
  docker compose ps --format json "$1" 2>/dev/null | tail -n 1
}

require_service() {
  local service="$1"
  local info status health
  info="$(service_json "$service")"
  [ -n "$info" ] || fail "missing required service: $service"
  status="$(printf '%s' "$info" | python -c 'import json,sys; data=json.load(sys.stdin); print((data.get("State") or data.get("Status") or "").lower())' 2>/dev/null || true)"
  health="$(printf '%s' "$info" | python -c 'import json,sys; print((json.load(sys.stdin).get("Health") or "").lower())' 2>/dev/null || true)"
  [ "$status" = "running" ] || fail "$service is not running"
  [ -z "$health" ] || [ "$health" = "healthy" ] || fail "$service health is $health"
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
docker compose build
docker compose up -d
docker compose ps
require_service traefik
require_service backend
require_service bot
check_backend_from_docker_network
check_public_health
EOF
