# Rollout Reference

## What controls the mode

The switch is:

- `CONTADORES_SOURCE_MODE=testing|live`

This must come from `.env`, and `docker-compose.yml` must consume `.env`.

Funnel definitions live in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
That file is the shared UI/Codex config surface for niche funnels. It is not the
runtime mode switch.

Inbound WhatsApp media lives in `data/contadores/inbound_media` by default. If
`WA_INBOUND_MEDIA_DIR` is set, it must still be a persistent directory shared by
the bot that downloads files and the backend that serves them.

## Minimum testing config

- `CONTADORES_ENABLED=true`
- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_TEST_PHONE=...`
- `CONTADORES_LOOM_URL=...`
- `CONTADORES_CALENDLY_BASE_URL=...`
- `FUNNELS_CONFIG_PATH=data/funnels.json`
- optional: `WA_INBOUND_MEDIA_DIR=...`

## Minimum live config

- `CONTADORES_ENABLED=true`
- `CONTADORES_SOURCE_MODE=live`
- `CONTADORES_SHEET_URL=...`
- `CONTADORES_SHEET_GID=...`
- `CONTADORES_LOOM_URL=...`
- `CONTADORES_CALENDLY_BASE_URL=...`
- optional: `WA_INBOUND_MEDIA_DIR=...`

## Safe release sequence

1. Use `localhost` only to develop and validate the change.
2. Merge or commit the code into `main`.
3. Push `main`.
4. Deploy the server from `main`.
5. Keep runtime in `testing`.
6. Verify the flow with the synthetic lead created from `CONTADORES_TEST_PHONE`.
7. When the test flow is correct, change `.env` to `live`.
8. Restart the containers.

For new funnels, keep their definition in the same persistent config file used
by the UI. Do not rely on local-only edits that are absent from the server
volume.

## SQLite runtime guardrail

The backend should run with one Uvicorn worker while the repo uses SQLite. The
database file lives in `data/database.sqlite`, which is mounted into both the
backend and bot containers. The backend engine enables WAL and a busy timeout,
but extra backend workers still add unnecessary write contention.

Only raise the worker count after moving persistence to Postgres or after adding
a deliberate SQLite concurrency plan.

## Important nuance

Deploy target and runtime mode are different things.

It is valid to:

- deploy the newest code on the real server;
- keep the system in `testing`;
- promote to `live` later with only an env change plus restart.

For this repo, deployed-on-server is the default definition of done for product changes. A local-only run is just a development checkpoint.

`/api/runtime` should show the active source mode and readiness state after each restart.
