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

The multi-funnel config file is separate from the runtime switch:

- `FUNNELS_CONFIG_PATH`, usually `data/funnels.json`
- if unset, the app uses `data/funnels.json`

This file stores funnel definitions added from the UI or by Codex. Keep it in
the server data volume when it must persist across deploys.
Click-to-WhatsApp routing also belongs there through
`whatsapp_referral_source_ids`; the default Contadores funnel can be seeded from
`CONTADORES_WHATSAPP_REFERRAL_SOURCE_IDS`.

WhatsApp strategy videos should be referenced by `media_path` under the shared
`data` volume. The bot sends that configured file, and the frontend serves the
same path through one stable media URL. WhatsApp media sent by leads should also
be downloaded into `data/contadores/inbound_media` when available so operators
can inspect images, videos, audio, documents, and stickers from the CRM.

## Branch And Deploy Rule

- The project is server-first by default.
- Treat `localhost` only as the workbench for development, validation, git, push, and deploy.
- When the user asks for a product change or asks whether it is done, assume the expected end state is deployed on the real server unless they explicitly say local-only.
- `main` is the operational branch.
- If something is meant to run on the server, it should be committed on `main`.
- `docker-compose.yml` should read `.env`.
- The server can run production infrastructure while the app still stays in `testing` mode.
- While the project uses SQLite, keep the backend at one Uvicorn worker. SQLite
  lives in the persistent `data/` volume and the bot also writes to it, so extra
  backend workers can create avoidable `database is locked` failures.

## Rollout Rule

1. Deploy the code to the server.
2. Keep `.env` in `testing`.
3. Test with `CONTADORES_TEST_PHONE`; the bot imports that phone as the only synthetic lead.
4. Repeat as many times as needed.
5. Only then switch `.env` to `live`.

For a new niche funnel, create/edit the funnel definition first, deploy code,
test that funnel in `testing`, then promote that funnel to `live`.

Read [references/rollout.md](references/rollout.md) for the exact env variables and the recommended sequence.
