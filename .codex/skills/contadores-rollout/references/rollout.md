# Rollout Reference

## What controls the mode

The switch is:

- `CONTADORES_SOURCE_MODE=testing|live`

This must come from `.env`, and `docker-compose.yml` must consume `.env`.

## Minimum testing config

- `CONTADORES_ENABLED=true`
- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_TEST_PHONE=...`
- `CONTADORES_LOOM_URL=...`
- `CONTADORES_CALENDLY_BASE_URL=...`

## Minimum live config

- `CONTADORES_ENABLED=true`
- `CONTADORES_SOURCE_MODE=live`
- `CONTADORES_SHEET_URL=...`
- `CONTADORES_SHEET_GID=...`
- `CONTADORES_LOOM_URL=...`
- `CONTADORES_CALENDLY_BASE_URL=...`

## Safe release sequence

1. Merge or commit the code into `main`.
2. Deploy the server from `main`.
3. Keep runtime in `testing`.
4. Verify the flow with the synthetic lead created from `CONTADORES_TEST_PHONE`.
5. When the test flow is correct, change `.env` to `live`.
6. Restart the containers.

## Important nuance

Deploy target and runtime mode are different things.

It is valid to:

- deploy the newest code on the real server;
- keep the system in `testing`;
- promote to `live` later with only an env change plus restart.

`/api/runtime` should show the active source mode and readiness state after each restart.
