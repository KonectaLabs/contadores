---
name: workstation-solo-page
description: Use when Codex is asked by the Contadores Workstation automation to create or revise a static solo-page website for a pending-payment client.
---

# Workstation Solo Page

Create a fast first draft of a client's professional website from the Workstation
folder. Optimize for a useful preview video quickly, not for a perfect final site.

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

Write only inside the required output folder provided by the prompt:

```text
landing-page/vNNN/index.html
landing-page/vNNN/styles.css
landing-page/vNNN/script.js
landing-page/vNNN/preview-message.txt
landing-page/vNNN/assets/
```

Do not edit source templates, repo files, other client folders, or production
configuration. The automation will render `preview.mp4` after your files exist.

## Professional Photo Gate

Client-provided photos are source material, not final website assets. Never use a
photo from `media/` directly as a portrait on the page.

Before building or revising the page:

- If the client sent photos of people, first make sure there is a generated
  professional-photo asset for every distinct person visible or identified in
  those source photos.
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

## Page Rules

- Build plain static HTML, CSS, and JavaScript. No bundlers.
- Keep code readable, skimmable, and boring.
- Write `preview-message.txt` with the exact WhatsApp caption that should be
  sent with the preview video. Choose the text for the specific client and
  version. Do not rely on a hardcoded generic caption.
- Personalize the page with the client's name, profession, city/country,
  services, WhatsApp contact, and any references they sent.
- Treat `profile.json.client.offer_price_usd` as commercial context only. Do not
  print the discounted price on the public page unless the client explicitly
  asked for pricing to appear there.
- If information is missing, still produce a credible first draft with restrained
  placeholders that can be revised later.
- If no client photos were sent and no professional-photo asset exists, use
  appropriate template assets.
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
