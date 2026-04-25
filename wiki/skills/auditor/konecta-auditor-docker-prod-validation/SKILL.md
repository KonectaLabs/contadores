---
name: konecta-auditor-docker-prod-validation
description: Production-like Docker validation for agnostic Konecta Auditor backend. Use when verifying containerized API behavior and persisted data volume before closing work.
---

# Konecta Auditor Docker Validation

## Validate In Containerized Mode
Run Docker Compose checks against the backend service.

## Run Baseline Docker Checks
1. Confirm Docker daemon is available.
2. Build and start stack.
3. Confirm `backend` service is healthy/running.
4. Run API requests through exposed port.

Typical commands:
```bash
docker compose down
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 backend
```

## Verify Runtime Behavior Through API
- call health endpoint,
- scan company from URL (`POST /api/companies/scan`),
- verify initial outbound seeding happens in scan task (no separate first-message trigger),
- ingest multi-turn inbound messages,
- fetch transcript and verify persisted outbound replies,
- prepare layered report JSON,
- build PDF model JSON via `build-report-pdf-model`,
- verify host-side `data/` receives DB updates/artifacts via mounted volume.

## Enforce Docker Completion Gate
Before ending work, confirm all:
1. stack is running
2. endpoint E2E succeeds against Dockerized app
3. DB rows are persisted on host disk
4. no critical backend errors in logs

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
