#!/usr/bin/env bash
set -euo pipefail

SSH_TARGET="${CONTADORES_SSH_TARGET:-root@149.50.136.121}"
SSH_PORT="${CONTADORES_SSH_PORT:-5389}"
SERVER_DIR="${CONTADORES_SERVER_DIR:-/root/projects/contadores}"
PUBLIC_BASE_URL="${CONTADORES_PUBLIC_BASE_URL:-https://crm.fgoiriz.com}"

quote_remote() {
  printf "'%s'" "$(printf "%s" "$1" | sed "s/'/'\\\\''/g")"
}

REMOTE_DIR="$(quote_remote "$SERVER_DIR")"
ssh_cmd=(ssh -p "$SSH_PORT" "$SSH_TARGET")

run_check() {
  local label="$1"
  shift
  printf '\n== %s ==\n' "$label"
  "$@"
}

run_remote() {
  "${ssh_cmd[@]}" "cd $REMOTE_DIR && $*"
}

run_check "remote git state" run_remote \
  'git branch --show-current && git rev-parse --short HEAD && git status --short'

run_check "container status" run_remote \
  'docker compose ps'

run_check "backend docker health" run_remote \
  'docker compose exec -T backend python -c "import urllib.request; print(urllib.request.urlopen(\"http://localhost:8000/health\", timeout=5).read().decode())"'

run_check "bot docker health" run_remote \
  'docker compose exec -T bot python -c "import urllib.request; print(urllib.request.urlopen(\"http://localhost:8100/health\", timeout=5).read().decode())"'

run_check "public health" curl -fsS "$PUBLIC_BASE_URL/health"

run_check "runtime and funnels via internal token" run_remote \
  'docker compose exec -T backend python - <<'"'"'PY'"'"'
import json
import os
import urllib.request

token = os.environ.get("INTERNAL_API_TOKEN", "")
if not token:
    raise SystemExit("INTERNAL_API_TOKEN missing in backend env")


def get_json(path):
    request = urllib.request.Request(
        f"http://localhost:8000{path}",
        headers={"X-Internal-Token": token},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


runtime = get_json("/api/runtime")
funnels = get_json("/api/funnels")
print("runtime-ready=", runtime.get("ready"))
print("funnels-count=", len(funnels.get("funnels", [])))
PY'

run_check "recent backend/bot errors" run_remote '
docker compose logs --since 10m backend bot 2>&1 |
  grep -Ei "error|exception|traceback|critical" |
  tail -80 || true
'
