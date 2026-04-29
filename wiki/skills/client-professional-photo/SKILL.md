---
name: client-professional-photo
description: Use when generating a polished professional portrait/photo for a Workstation client from one or more client-provided reference photos, especially for lawyers, accountants, consultants, or other service professionals.
---

# Client Professional Photo

Use this skill to create a professional portrait from client-provided photos.

The target output is not a casual headshot. It should look like a premium business portrait made by a professional photographer for a lawyer, accountant, consultant, or firm owner.

## Inputs

Expected inputs:

- Client folder under `data/workstation/clients/{client_id}-{client-slug}/`.
- One or more selected source images from the client's `media/` folder.
- Optional context: profession, firm type, desired tone, city/country, and any hard constraints.

Only use photos explicitly selected by the operator or user. Preserve source files.

## Output Convention

Save generated outputs inside the client folder:

```text
data/workstation/clients/{client-folder}/professional-photo/v001/professional-photo.jpg
data/workstation/clients/{client-folder}/professional-photo/v001/metadata.json
```

If `v001` already exists, create the next version:

```text
professional-photo/v002/professional-photo.jpg
professional-photo/v002/metadata.json
```

`metadata.json` should include:

- source image paths;
- output image path;
- creation timestamp;
- operation: `create`;
- profession/context used;
- final image prompt text.

## Identity Rules

- Preserve the client's identity from the source photos.
- Keep facial structure, age range, skin tone, hair, facial hair, and recognizable features consistent.
- Do not beautify into a different person.
- Do not make the client look younger in an unrealistic way.
- Do not add logos, text, watermarks, badges, fake certificates, or fake names.
- Avoid exaggerated luxury, cinematic fantasy, influencer styling, or stock-photo posing.
- If input photos are low quality or inconsistent, choose the most identity-consistent interpretation and mention the uncertainty in metadata.

## Visual Direction

The desired look:

- Medium or three-quarter professional portrait.
- Client wearing a tailored dark suit or professional formal outfit.
- White or light shirt; dark tie if appropriate for the profession.
- Confident, approachable expression; subtle smile; direct eye contact.
- Natural skin tone retained while the environment is mostly desaturated.
- Dark, elegant office background: bookshelves, framed diploma or art, desk, soft lamp, legal/accounting office feel.
- Background softly blurred and mostly black/white or charcoal gray.
- Subject remains in natural color, especially face and hands.
- Soft studio-style key light on face, controlled shadows, premium editorial finish.
- Realistic DSLR photography, 85mm portrait lens feel, shallow depth of field.
- Vertical composition, around 4:5 or 3:4 aspect ratio.

Avoid:

- Corporate stock-photo smiles.
- Over-sharpened skin or plastic retouching.
- Busy offices, visible brand names, readable fake documents.
- Unrealistic body proportions, extra fingers, distorted hands, odd teeth, or mismatched eyes.
- Strong color grading, colorful backgrounds, neon, gradients, or generic AI glow.

## Core Generation Prompt

Use the selected client photos as identity references.

```text
Create a realistic premium professional portrait of the person in the reference photos.

Preserve the person's identity accurately: same facial structure, age range, skin tone, hair, facial hair, and natural expression. Do not make them look like a different person.

Style the person as a high-end professional service provider, suitable for a lawyer, accountant, consultant, or firm owner. The person is wearing a well-fitted dark suit, a clean light shirt, and a dark professional tie if appropriate. The expression is calm, confident, approachable, and trustworthy, with direct eye contact and a subtle natural smile.

Set the portrait inside an elegant private office with dark shelves, books, a framed diploma or abstract black-and-white artwork, a desk, and soft practical lighting. The background should feel refined and professional, mostly desaturated in charcoal, black, white, and gray tones. Keep the person in natural color, especially the face and hands, while the environment remains muted and almost black-and-white.

Composition: vertical three-quarter portrait, waist-up or mid-thigh crop, subject slightly off-center, relaxed posture, one hand possibly in pocket or resting naturally. Use soft studio lighting, shallow depth of field, realistic DSLR photography, 85mm portrait lens, premium editorial retouching, natural skin texture, realistic hands, realistic eyes, realistic clothing fabric.

No text, no logos, no watermark, no fake brand, no fake readable certificates, no exaggerated luxury, no cinematic fantasy, no stock-photo look.
```

## Workflow

1. Locate the client folder and selected source photos.
2. Inspect the source photos enough to understand identity, age, hair, facial hair, skin tone, and usable angle.
3. Build the final prompt from the core prompt plus any profession/context.
4. Use the image generation tool with the selected photos as references.
5. Save the result to the next `professional-photo/vNNN/professional-photo.jpg`.
6. Write `metadata.json`.
7. Return the exact output path and version.

## Workstation Integration Contract

When the Workstation feature calls Codex, it should pass:

- client folder path;
- selected media image paths;
- requested output version or `next`;
- optional context such as `profession`, `tone`, or `notes`.

The Codex task should be: use this skill to generate the professional photo and save it under the output convention above.
