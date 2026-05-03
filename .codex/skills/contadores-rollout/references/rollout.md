# Rollout Reference

## Runtime Source

There is no runtime mode switch for Contadores. The app always reads from the
configured sheet for each enabled campaign funnel.

Funnel definitions are stored in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
That file is the shared UI/Codex config surface for niche funnels.

Click-to-WhatsApp routing uses each funnel's `whatsapp_referral_source_ids`.
These values are Meta webhook `referral.source_id` values. Do not add broad
text routing because the user can edit the prefilled WhatsApp message. The
approved exception is the normalized Abogados proposal text, which routes to
`abogados` when no reply/referral route is usable.
When no referral or approved text fallback matches, the backend stores the
inbound WhatsApp message in the built-in `general` inbox. Inbox funnels do not
run automation or sheet sync.
If Meta sends `contacts.profile.name`, the inbound handler passes that profile
name through the bot and stores it on WhatsApp-created leads, or fills it on an
existing matched lead that still only had a phone number.

WhatsApp strategy videos should be stored under the shared `data` volume and be
referenced by funnel `media_path`. The bot sends the configured file and the
frontend serves that same file by stable path. Media sent by leads is downloaded
into `data/contadores/inbound_media` when available and served through the same
protected media endpoint for CRM review.

## Minimum Config

- `CONTADORES_ENABLED=true`
- `CONTADORES_SHEET_URL=...`
- `CONTADORES_SHEET_GID=...`
- Calendly fijo del producto: `https://calendly.com/facundogoiriz/crecimiento`
- `FUNNELS_CONFIG_PATH=data/funnels.json`

## Safe release sequence

`ALWAYS_DEPLOY`: a product change is not finished at local build, local tests,
or pushed code. It is finished only after the real server is updated and
verified.

1. Use `localhost` only to develop and validate the change.
2. Merge or commit the code into `main`.
3. Push `main`.
4. Deploy the server from `main`.
5. Verify `/api/runtime` readiness.
6. Verify `/api/funnels`.
7. Verify sheet ingestion and WhatsApp flow on the server.
8. If the post-video sequence changed, verify the simple watched-video
   confirmation path queues `post_loom_service_recap`.

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

For this repo, deployed-on-server is the default definition of done for product
changes. A local-only run is just a development checkpoint. If the user asks
whether a product change is done, check and answer against the real server.

`/api/runtime` should show readiness state after each restart.
