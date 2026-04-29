---
name: client-professional-photo-edit
description: Use when modifying or creating a new version of an existing Workstation professional client portrait using a user edit prompt while preserving the client's identity and the professional portrait style.
---

# Client Professional Photo Edit

Use this skill to modify an existing generated professional portrait for a Workstation client.

This is for iterative changes such as:

- make it more formal;
- make the background more like a law office;
- make the suit darker;
- make the expression warmer;
- crop closer;
- reduce the black-and-white effect;
- make it more premium or more approachable.

## Inputs

Expected inputs:

- Client folder under `data/workstation/clients/{client_id}-{client-slug}/`.
- Existing professional photo version path, usually:

```text
professional-photo/vNNN/professional-photo.jpg
```

- User modification prompt.
- Optional original source photos from `media/` if identity needs reinforcement.

## Output Convention

Never overwrite an existing version.

Save every modification as the next version:

```text
data/workstation/clients/{client-folder}/professional-photo/v002/professional-photo.jpg
data/workstation/clients/{client-folder}/professional-photo/v002/metadata.json
```

If `v002` exists, create `v003`, then `v004`, and so on.

`metadata.json` should include:

- operation: `edit`;
- previous version path;
- output image path;
- source image paths used;
- user edit prompt;
- final image prompt text;
- creation timestamp.

## Identity And Continuity Rules

- Preserve the same person and recognizable identity.
- Preserve the professional portrait quality unless the user explicitly asks otherwise.
- Keep the person realistic and natural.
- Keep age, facial structure, skin tone, hair, facial hair, and expression direction consistent.
- Do not introduce logos, text, watermarks, fake names, or fake readable certificates.
- Do not replace the person with a generic model.
- Do not degrade into a casual selfie, social-media avatar, or stock-photo style.

## Edit Prompt Template

Use the previous professional portrait as the main image reference. Use original client photos as identity references when available.

```text
Create a new edited version of this professional portrait.

Preserve the person's identity accurately: same facial structure, age range, skin tone, hair, facial hair, and recognizable features. Keep the image realistic and suitable for a premium lawyer, accountant, consultant, or firm owner profile.

Apply this requested change:
{USER_EDIT_PROMPT}

Keep the overall style professional and refined: elegant office setting, dark suit or formal professional clothing, calm confident expression, soft studio lighting, shallow depth of field, realistic DSLR portrait quality, natural skin texture, realistic eyes and hands.

Unless the edit request says otherwise, keep the muted charcoal/black/white office background with the person in natural color. Avoid text, logos, watermarks, fake readable certificates, distorted anatomy, plastic retouching, and stock-photo exaggeration.
```

## Workflow

1. Locate the client folder and current professional photo version.
2. Read the user's edit prompt.
3. Determine the next output version under `professional-photo/vNNN/`.
4. Use image generation/editing with the previous image as the main reference.
5. Include original selected client photos as identity references if available.
6. Save the new version to `professional-photo/vNNN/professional-photo.jpg`.
7. Write `metadata.json`.
8. Return the exact new output path and version.

## Workstation Integration Contract

When the Workstation feature calls Codex for an edit, it should pass:

- client folder path;
- previous generated professional photo path;
- selected original media image paths if available;
- user edit prompt;
- requested output version or `next`.

The Codex task should be: use this skill to create the next professional-photo version with the user's requested change.
