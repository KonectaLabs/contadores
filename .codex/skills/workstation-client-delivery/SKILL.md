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
- `media/`: uploaded client files such as logos, photos, screenshots, or visual references.

The Workstation UI can also export the same folder as a ZIP, but Codex should
prefer reading the live folder directly when running inside this repo.

## Operating Rules

- Do not call GPT Image or other paid image APIs unless the user explicitly asks.
- If the task is visual, use Codex/local image-generation capability or return
  prompts/assets for manual use.
- Keep generated deliverables inside the same client folder or a clear child
  folder such as `exports/`, `landing-page/`, or `image-directions/`.
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
