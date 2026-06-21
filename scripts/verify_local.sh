#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "== duplicate pytest test names =="
python scripts/check_duplicate_test_names.py src/backend/tests src/bot/tests

echo "== backend import smoke =="
AUTH_DISABLE=true PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  uv run python -c "from backend.main import app; print('backend-import-ok')"

echo "== backend tests =="
AUTH_DISABLE=true PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  uv run --group dev pytest -p no:cacheprovider src/backend/tests -q

echo "== bot tests =="
PYTHONPATH=src:src/bot PYTHONDONTWRITEBYTECODE=1 \
  uv run --project src/bot --group dev pytest -p no:cacheprovider src/bot/tests -q

echo "== frontend build =="
(cd src/frontend && npm run build)
