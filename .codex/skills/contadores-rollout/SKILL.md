---
name: contadores-rollout
description: Use when changing deployment flow, Docker Compose, .env handling, or server rollout for the Contadores project.
---

# Contadores Rollout

Use this skill when the task touches deploy, server config, `main`, Docker Compose, or `.env` handling.

## Canonical Rule

Contadores has no runtime mode switch. Do not reintroduce alternate runtime
branches, synthetic leads, or source-mode fields.

The multi-funnel config file stores funnel-specific sheet and WhatsApp routing:

- `FUNNELS_CONFIG_PATH`, usually `data/funnels.json`
- if unset, the app uses `data/funnels.json`

This file stores funnel definitions added from the UI or by Codex. Keep it in
the server data volume when it must persist across deploys.
Click-to-WhatsApp routing also belongs there through
`whatsapp_referral_source_ids`; keep Contadores empty when it has no real
campaign source.
The approved Abogados prefilled proposal text can route to `abogados` when no
reply/referral route is usable. Other unmatched WhatsApp inbounds are saved in
the built-in `general` inbox. Inbox funnels do not run automation or sheet sync.
When Meta includes the sender profile name, the inbound flow stores it on the
lead when the lead came from WhatsApp or when an existing matched lead had no
name yet.

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
- While the project uses SQLite, keep the backend at one Uvicorn worker. SQLite
  lives in the persistent `data/` volume and the bot also writes to it, so extra
  backend workers can create avoidable `database is locked` failures.

## Rollout Rule

1. Deploy the code to the server.
2. Verify `/api/runtime` readiness.
3. Verify `/api/funnels`.
4. Verify sheet ingestion and WhatsApp flow on the real server.

For a new niche funnel, create/edit the funnel definition first, deploy code,
then verify that funnel against its configured sheet and WhatsApp routing.

Read [references/rollout.md](references/rollout.md) for the exact env variables and the recommended sequence.
