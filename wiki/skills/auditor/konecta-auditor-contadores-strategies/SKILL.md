---
name: konecta-auditor-contadores-strategies
description: Add or adjust Contadores sequence strategies, weights, media payloads, and strategy stats without cluttering the operator UI.
---

# Konecta Auditor Contadores Strategies

## Purpose
Use this skill when adding a new Contadores sequence strategy, changing rollout weights, or debugging strategy assignment/statistics.

## Strategy Location
Strategies live in:
- `/Users/fgoiriz/private/repos/contadores/src/backend/contadores_strategies/__init__.py`

Each strategy is a small class extending `ContadoresSequenceStrategy`:
- `step`: stable sequence step family, for example `loom`
- `id`: stable machine id, for example `loom_mp4`
- `label`: short operator-facing label
- `weight`: default integer traffic weight, overridden by Contadores config when present
- `build_messages(lead, config)`: returns `ContadoresOutboundDraft` rows

## Add A Strategy
1. Create a new class in `backend/contadores_strategies/__init__.py`.
2. Return one or more `ContadoresOutboundDraft` objects.
3. Add the strategy instance to `STRATEGIES`.
4. Keep code weights as defaults; change live rollout through `strategy_weights` in Contadores config.
5. If the strategy sends media, set:
   - `media_type`, currently `video`
   - `media_path`, usually under `data/contadores/videos/`
   - optional `media_caption`

## Runtime Contract
- `backend/endpoints/contadores.py` chooses one strategy when a sequence is queued.
- The assignment is persisted in `contadores_strategy_assignments`.
- Each outbound row stores `strategy_step`, `strategy_id`, `strategy_label`, and optional media metadata.
- The bot consumes `/api/contadores/messages/pending-delivery` and dispatches media in `bot/`, not in backend startup.

## Stats
Strategy stats are exposed at:
- `GET /api/contadores/strategy-stats`

Stats count:
- assigned strategy buckets,
- sent/delivered assignment rows,
- leads that reached Calendly after assignment,
- leads converted after assignment; old storage may still expose the legacy
  booked milestone name.

## Validation
Run:
```bash
uv run --with pytest pytest backend/tests/test_contadores.py -q
cd bot && uv run --with pytest pytest tests/test_contadores_flow.py -q
node --check frontend/static/js/app.js
uv run python -m py_compile backend/database.py backend/endpoints/contadores.py backend/contadores_strategies/__init__.py
```

## Guardrails
- Use the Settings drawer when operators ask for editable rollout weights.
- Keep strategy IDs stable once traffic has been assigned.
- Do not rewrite old assignments when weights change.
- Keep media files under `data/` so both backend and bot Docker services can see them.
