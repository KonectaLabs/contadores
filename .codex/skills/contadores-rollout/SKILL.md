---
name: contadores-rollout
description: Use when changing deployment flow, runtime mode, Docker Compose, .env handling, or the safe rollout from testing to live for the Contadores project.
---

# Contadores Rollout

Use this skill when the task touches deploy, server config, `main`, Docker Compose, or the `testing/live` switch.

## Canonical Rule

The runtime mode is controlled by environment, not by hardcoded logic and not by hidden local state.

Use:

- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_SOURCE_MODE=live`

## Branch And Deploy Rule

- `main` is the operational branch.
- If something is meant to run on the server, it should be committed on `main`.
- `docker-compose.yml` should read `.env`.
- The server can run production infrastructure while the app still stays in `testing` mode.

## Rollout Rule

1. Deploy the code to the server.
2. Keep `.env` in `testing`.
3. Test with `CONTADORES_TEST_PHONE`.
4. Repeat as many times as needed.
5. Only then switch `.env` to `live`.

Read [references/rollout.md](references/rollout.md) for the exact env variables and the recommended sequence.
