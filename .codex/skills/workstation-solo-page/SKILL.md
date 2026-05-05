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
landing-page/vNNN/assets/
```

Do not edit source templates, repo files, other client folders, or production
configuration. The automation will render `preview.mp4` after your files exist.

## Page Rules

- Build plain static HTML, CSS, and JavaScript. No bundlers.
- Keep code readable, skimmable, and boring.
- Personalize the page with the client's name, profession, city/country,
  services, WhatsApp contact, and any references they sent.
- If information is missing, still produce a credible first draft with restrained
  placeholders that can be revised later.
- If a professional photo exists, use it. If not, use appropriate template assets.
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
