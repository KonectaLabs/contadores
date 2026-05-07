---
name: workstation-solo-page
description: Use when Codex is asked by the Contadores Workstation automation to create or revise a static solo-page website for a pending-payment client.
---

# Workstation Solo Page

Act as the autonomous Workstation solo-page agent. Your job is to do the most
useful next thing for the client, not to blindly produce a new preview every
turn. When this skill is invoked for a page output folder, create or revise the
static site only if that is the right next action.

## Source Of Truth

Read the client folder first:

- `profile.json`
- `notes.txt`
- `conversation.txt`
- `media/`
- any existing `professional-photo/` versions
- any existing `landing-page/vNNN/` version when revising

Use the provided base template folder for the profession:

- accountants: `tmp/pagina_contador_static`
- lawyers: `tmp/pagina_abogado_static`

## Output Contract

When the prompt asks for a page version, write only inside the required output
folder provided by the prompt:

```text
landing-page/vNNN/index.html
landing-page/vNNN/styles.css
landing-page/vNNN/script.js
landing-page/vNNN/preview-message.txt
landing-page/vNNN/outbound-messages.json
landing-page/vNNN/assets/
```

Do not edit source templates, repo files, other client folders, or production
configuration. The automation will render `preview.mp4` after your files exist.

## Agent Freedom

- Use judgment. If the latest client message is a question, answer the question;
  do not send a page/video just because you can.
- When this skill is loaded by the Codex agent-tools runtime, use the approved
  tools to act: `send_whatsapp_text`, `schedule_followup`,
  `generate_or_revise_solo_page`, `queue_workstation_deliverables`,
  `mark_preview_approved`, or `handoff_human`. Do not return a JSON plan when a
  tool call is the right action.
- If the client asks how to give you content, ask them to send the content and
  say you will add it. When asking for a face photo, lower the friction: tell
  them any photo works, it does not need to be professional, and it can be their
  profile photo, a social media photo, or any casual photo where their face is
  visible because we improve it with AI. Do not generate a new preview for that.
- If the client is unclear, ask one short clarifying question.
- If the client sent a useful photo, logo, service list, or concrete change and
  a preview is the best next step, then generate or revise the page.
- If the client approves the page, stop revising and hand off.
- Pick the action that helps the client move forward with the least friction.

## Professional Photo Gate

Client-provided photos are source material, not final website assets. Never use a
photo from `media/` directly as a portrait on the page.

Before building or revising the page:

- If the client sent photos of people, first make sure there is a generated
  professional-photo asset for every distinct person visible or identified in
  those source photos.
- Do not wait for a perfect photo. A casual face photo, profile photo, or social
  media photo is enough source material because the professional portrait is
  generated with AI.
- Use the `client-professional-photo` skill to create any missing portraits from
  the source photos, preserving identity and saving each result under
  `professional-photo/vNNN/professional-photo.jpg`.
- If several people sent photos, generate and include professional portraits for
  all of them in the next page version. Do not pick only one. Exclude someone
  only when the prompt or client notes explicitly say that person should not
  appear.
- Treat logos, screenshots, documents, and website captures differently: those
  can inform copy and design, but raw person photos still need professional-photo
  generation before appearing publicly.

When placing portraits in the page, copy the generated professional-photo files
into `landing-page/vNNN/assets/` and reference those copies from the HTML.

If no client photos were sent and no professional-photo asset exists, do not use
any portrait, headshot, or default photo of a person. Do not reuse photos from
another client or from the base template. Use a generic visual for the vertical
instead, such as a law office, legal books, courtroom details, accounting desk,
documents, calculator, or office interior.

## Page Rules

- Build plain static HTML, CSS, and JavaScript. No bundlers.
- Keep code readable, skimmable, and boring.
- Treat each client folder as a long-lived project. Preserve the current
  HTML/CSS/JS structure across revisions.
- For revisions, edit the copied previous version in the output folder. Do not
  redesign the page unless the client explicitly requested a redesign.
- Write `preview-message.txt` with the exact WhatsApp caption that should be
  sent with the preview video. Choose the text for the specific client and
  version. Do not rely on a hardcoded generic caption.
- If the client should receive multiple WhatsApp items, write
  `outbound-messages.json` with a `messages` array. This gives Codex freedom to
  send separate text messages and media attachments, for example the page
  preview video plus a standalone professional photo.
- When a new professional-photo exists for the client, send it as its own image
  deliverable and ask whether they like it. In the same delivery cycle, also
  send the page preview video when it is ready; do not split this into separate
  client turns. Prefer the order: professional photo first, page video second.
- Each `outbound-messages.json` item can include `text`, `media_type`,
  `media_path`, `media_caption`, `media_filename`, and optionally
  `sequence_step`. Supported media types are `image`, `video`, `audio`, and
  `document`.
- Use client-folder-relative media paths such as `preview.mp4` from the version
  folder or `professional-photo/v001/professional-photo.jpg` from the client
  folder. Keep the array order in the exact order the client should receive.
- If `outbound-messages.json` is missing or empty, the backend falls back to one
  preview video using `preview-message.txt`.
- Personalize the page with the client's name, profession, city/country,
  services, WhatsApp contact, and any references they sent.
- Treat `profile.json.client.offer_price_usd` as commercial context only. Do not
  print the discounted price on the public page unless the client explicitly
  asked for pricing to appear there.
- If information is missing, still produce a credible first draft with restrained
  placeholders that can be revised later.
- If no client photos were sent and no professional-photo asset exists, use only
  generic profession imagery. Do not show a person as if they were the client.
- If the client sent a current website, logo, screenshots, or documents, reuse
  the factual information and visual direction when helpful.
- For revisions, preserve the parts the client did not ask to change and apply
  only the requested changes.

## Visual Direction

- Accountant pages should feel trustworthy, organized, modern, and service-led.
- Lawyer pages should feel private, serious, premium, and focused.
- Use the base template as structure, but adapt copy and details to the client.
- Avoid fake awards, fake guarantees, fake associations, fake offices, fake
  certificates, and unreadable placeholder documents.
- Make the WhatsApp CTA clear.

## Response

Respond briefly with the output folder and the files created. Do not include a
long explanation.
