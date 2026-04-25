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

1. Use `localhost` only to develop and validate the change.
2. Merge or commit the code into `main`.
3. Push `main`.
4. Deploy the server from `main`.
5. Keep runtime in `testing`.
6. Verify the flow with the synthetic lead created from `CONTADORES_TEST_PHONE`.
7. When the test flow is correct, change `.env` to `live`.
8. Restart the containers.

## Important nuance

Deploy target and runtime mode are different things.

It is valid to:

- deploy the newest code on the real server;
- keep the system in `testing`;
- promote to `live` later with only an env change plus restart.

For this repo, deployed-on-server is the default definition of done for product changes. A local-only run is just a development checkpoint.

`/api/runtime` should show the active source mode and readiness state after each restart.
