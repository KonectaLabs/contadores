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

Outbound WhatsApp send failures are persisted on `contadores_messages`. The bot
reports send exceptions to the backend, the backend requeues until
`CONTADORES_DELIVERY_MAX_ATTEMPTS`, and after the retry budget is exhausted the
CRM must show the failed message with the stored error. Operators can
acknowledge a failed message from the chat; acknowledged failures keep their
message-level error but no longer count toward the red lead-row alert.
Failed WhatsApp provider webhooks should preserve Meta error fields when
available (`code`, user-facing message, details) and the backend should
normalize common codes such as `131026` (likely invalid/not-on-WhatsApp
recipient) and `131047` (24-hour customer service window closed) into useful
operator-facing explanations.
Historical failed rows can be requeued with:

```bash
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
uv run python src/scripts/requeue_failed_contadores_messages.py
```

## Branch And Deploy Rule

- `ALWAYS_DEPLOY`: product changes are not done until they are committed on
  `main`, pushed, deployed to the real server, and verified there.
- The project is server-first by default.
- Treat `localhost` only as the workbench for development, validation, git, push, and deploy.
- When the user asks for a product change or asks whether it is done, assume the expected end state is deployed on the real server unless they explicitly say local-only.
- If the user asks "quedo?", "esta listo?", or any equivalent status question,
  answer against the deployed server state, not the local checkout.
- `main` is the operational branch.
- If something is meant to run on the server, it should be committed on `main`.
- `docker-compose.yml` should read `.env`.
- While the project uses SQLite, keep the backend at one Uvicorn worker. SQLite
  lives in the persistent `data/` volume and the bot also writes to it, so extra
  backend workers can create avoidable `database is locked` failures.

## Rollout Rule

`ALWAYS_DEPLOY` sequence:

1. Commit the product change on `main`.
2. Push `main`.
3. Deploy the code to the real server.
4. Verify `/api/runtime` readiness on the server.
5. Verify `/api/funnels` on the server.
6. Verify sheet ingestion and WhatsApp flow on the real server when the change touches those surfaces.
   When the change touches the post-video sequence, include the
   simple watched-video confirmation path that queues the recap inside
   `loom_intro`.

For a new niche funnel, create/edit the funnel definition first, deploy code,
then verify that funnel against its configured sheet and WhatsApp routing.

Read [references/rollout.md](references/rollout.md) for the exact env variables and the recommended sequence.
