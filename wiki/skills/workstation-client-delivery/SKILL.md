---
name: workstation-client-delivery
description: Use when creating manual deliverables for a paid converted client stored in the Contadores Workstation. Covers where to find client notes, CRM transcript, uploaded media, and how Codex should use those files without calling image APIs by default.
---

# Workstation Client Delivery

Use this skill when the user asks to create or inspect deliverables for a client
that was converted from the CRM into Workstation.

## Source Of Truth

Each converted client has a folder under:

```text
data/workstation/clients/{client_id_corto}-{nombre-slug}/
```

Read these files first:

- `profile.json`: client, lead, folder, and media metadata.
- `notes.txt`: operator meeting notes and client requirements.
- `conversation.txt`: CRM/WhatsApp transcript.
- `media/`: uploaded client files such as logos, photos, screenshots, or visual references. Operators can add these from the Workstation file selector, by dropping a file on the `Media` panel, or by pasting a clipboard file while that panel is active. Images sent by the client in the WhatsApp conversation are mirrored here automatically when a Workstation client exists, and existing conversation images are mirrored when the lead is converted. Operators can rename the media title and download filename from the UI; the physical stored filename remains stable.
- `landing-page/vNNN/`: versioned static page drafts for `work_type=solo_pagina`,
  including `index.html`, `styles.css`, `script.js`, `assets/`, `preview.mp4`,
  optional `outbound-messages.json`, and `metadata.json`.
- `progress.md`: operator-visible progress log for solo-page drafts, revisions,
  preview rendering, and WhatsApp preview queueing.

The Workstation UI can also export the same folder as a ZIP, but Codex should
prefer reading the current folder directly when running inside this repo.

When Workstation is running with `CODEX_AGENT_TOOLS_ENABLED=true` and
`CODEX_AGENT_TOOLS_WORKSTATION_ENABLED=true`, Codex acts through approved tools
instead of only writing files and letting the backend infer intent. It may send
short text replies, schedule DB-backed follow-ups, generate/revise a page,
queue deliverables, mark approval, or hand off to a human. Every tool call is
validated and audited; direct DB writes are not part of the employee contract.

Professional portraits are started from the Workstation client's `Actions`
button. The UI opens a media-selection modal, starts an async backend job, then
polls the job until the generated version appears under `professional-photo/`.

Workstation automation failures are never silent. A failed solo-page automation
must create a pending runtime alert for email notification and the client detail
payload must expose `runtime_alerts`; the UI shows the failure state, error, and
email notification status directly on the Workstation client page.
Only alert when delivery is blocked before the preview is generated or queued.
Errors after a preview exists, such as ping-loop or secondary state issues,
should stay in `progress.md` and leave the client waiting for review.

Solo-page automation waits for 20 minutes of silence after the latest inbound
message before drafting, revising, or treating the preview as approved. This
gives clients time to send photos, audio, and business details in multiple
messages.

The Workstation detail API exposes `automation_state` with the current logical
state (`idle`, backoff wait, Codex working, ready for next tick, failed, or human
handoff) plus the latest `progress.md` content. The frontend polls the selected
client every few seconds and shows that progress without overwriting notes in
progress. If a draft or revision stays in a working state for more than 2
hours, the detail marks it stale and the next tick creates the visible failure
alert/email instead of leaving it silent. The Workstation tick endpoint has a
process lock: while a long Codex generation tick is still running, retry ticks
return `status=busy` and do not evaluate stale working clients.

If a client replies after the no-response `workstation_handoff`, and the handoff
was not caused by explicit approval, Workstation resumes preview review: it shows
the 20-minute backoff and then starts a Codex revision on the next tick. Handoffs
caused by approval stay human-owned.

Operators can stop a running solo-page Codex draft or revision from the
Workstation `Actions` menu. Stop interrupts the active Codex turn for that
client, moves the client to `needs_human`, and records the stop in `progress.md`
without creating a failure alert.

Operators can also steer a running solo-page Codex draft or revision from the
same menu. Steer sends a short instruction to the active Codex turn without
restarting the job, and records the instruction in `progress.md`.

## Operating Rules

- Do not call GPT Image or other paid image APIs unless the user explicitly asks.
- If the task is visual, use Codex/local image-generation capability or return
  prompts/assets for manual use.
- Keep generated deliverables inside the same client folder or a clear child
  folder such as `exports/`, `landing-page/`, or `image-directions/`.
- Professional portrait outputs belong under `professional-photo/vNNN/` with
  `professional-photo.jpg` and `metadata.json`.
- Static page drafts belong under `landing-page/vNNN/`. Do not overwrite prior
  page versions; create the next version and let the automation render
  `preview.mp4` from that folder.
- Static page structure is fixed. Put `index.html`, `styles.css`, and
  `script.js` at the root of the page version. Put every page-owned asset under
  `assets/`. Reference them only as `./styles.css`, `./script.js`, and
  `./assets/...`. Never reference `/data`, `../`, absolute filesystem paths,
  source-template files, or another client folder from public HTML.
- `preview.mp4` and `metadata.json` are backend-owned files. Do not create or
  edit them manually.
- After a valid page version exists, the backend keeps one stable public trial
  URL for the client under `/p/{token}/`. That URL always points to the latest
  generated version and is for review/testing, not final custom-domain hosting.
- Do not revise public pages from vague factual/copy requests. If the client
  says something like "hacer la trayectoria mas amplia", "poner algo mas
  completo", or "mejorar la experiencia" without giving the facts, ask five
  compact questions and wait. Collect timeframe, main areas/services,
  credentials or roles, clients/cases/logros that can be mentioned without
  sensitive details, and preferred tone. Do not invent trajectory, cases,
  awards, credentials, services, legal facts, or accounting facts.
- If the client should receive more than the page preview, create
  `outbound-messages.json` in the page version with an ordered `messages` array.
  Use it for separate text/media sends. When there is a professional photo,
  send that image first as its own useful deliverable and ask if they like it,
  then send the page preview video in the same delivery cycle. If the file is
  absent, Workstation sends the default delivery plan.
- Encourage clients to send any face photo when one is missing. It does not need
  to be professional; a profile photo, social media photo, or any casual photo
  where the face is visible is enough because Konecta improves it with AI.
- Preserve the original `notes.txt`, `conversation.txt`, and uploaded `media/`
  files; create new files instead of overwriting source material.
- When a client is ambiguous, list matching folders and ask for the exact one.

## Basic Workflow

1. Locate the client folder in `data/workstation/clients/`.
2. Read `profile.json`, `notes.txt`, and `conversation.txt`.
3. Inspect `media/` for logos, photos, screenshots, and references.
4. Build the deliverable from those inputs.
5. Save outputs in a named child folder inside the client folder.
6. Report the exact output paths back to the user.
