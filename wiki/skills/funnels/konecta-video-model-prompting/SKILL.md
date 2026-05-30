---
name: konecta-video-model-prompting
description: Use when creating or improving prompts for AI video models such as Veo, Flow, Sora, Runway, or other text-to-video/image-to-video tools for Konecta marketing ads, especially continuous-take social videos with dialogue, camera movement, on-screen text, and visual effects.
---

# Konecta Video Model Prompting

## Core Rule

Prompt video like a shoot plan, not like an image prompt.

Separate:

- format and duration;
- subject;
- location;
- camera;
- action timeline;
- dialogue;
- on-screen text;
- motion graphics/effects;
- audio;
- language rules;
- negative constraints.

For Konecta ads, the buyer must see their own problem and desired outcome before
any agency mechanism. Do not lead with Konecta, AI, software, dashboards, or
"marketing".

## Model-Friendly Defaults

- Use vertical `9:16` for Reels, Stories, and TikTok-style ads.
- Ask for `single continuous take` when the user wants no cuts.
- Say `no camera cuts, no montage, no scene cuts` explicitly.
- Give the camera one clear behavior: locked frontal, slow push-in, side
  tracking, handheld follow, etc.
- Keep one main character and one main transformation.
- Use physical transitions when possible: walking through a door, crossing a
  wall, opening a folder, turning a phone, entering a new room.
- Keep generated text short. Long text often fails or mutates.
- For speech, write `The lawyer says:` or `El abogado dice:` before the spoken
  line. Avoid quoting dialogue as floating visual text unless that is intended.
- Tell the model that text and speech must be neutral Latin American Spanish
  when the ad should work across LatAm.

## Continuous-Take Structure

For one-shot ads, use this order:

1. **Opening state**
   - Who is in frame?
   - Where are they?
   - What problem is visually obvious?
2. **Camera path**
   - What does the camera do for the whole video?
   - Does it follow, push in, pan, or track sideways?
3. **Transformation event**
   - What physical thing changes the world?
   - Door, wall crossing, room reveal, phone reveal, folder reveal.
4. **After state**
   - What concrete outcome appears?
   - WhatsApp inquiries, lead cards, documents, clients waiting, organized
     folders, case summary.
5. **CTA**
   - One short spoken line and one short visual text.

Avoid asking for many unrelated actions in the same second. Give beats with
time ranges.

## Prompt Template

```text
Create a vertical 9:16 social media video, [duration] seconds, single continuous
take, no camera cuts, no montage, no scene cuts.

Camera:
[one camera behavior for the full video: locked frontal slow push-in / smooth
side-tracking left to right / handheld follow / overhead table move].

Subject:
[one specific person, age, profession, expression, clothing, emotional state].

Opening location:
[specific room, lighting, clutter, objects, mood].

Opening action:
[what the person does and what proves the problem visually].

Dialogue:
The [person] says: [short neutral Spanish line].

On-screen text:
[short text only, large, readable, synchronized with the line].

Transition:
[physical continuous transition, not a cut. Explain exactly what changes and
what the camera sees while it happens].

After location:
[new room/state/outcome, lighting, objects, people, workflow].

Outcome artifacts:
[real-looking artifacts: message cards, form fill, CRM card, document checklist,
folders, lead record. Use fictitious data].

Final dialogue:
The [person] says: [short CTA].

Final on-screen text:
[short CTA text].

Audio:
[voice style, room tone, music bed, notification sounds].

Language:
All spoken and written Spanish must be neutral Latin American Spanish, familiar
across LatAm. Avoid voseo, Argentine-specific slang, and overly local words.

Style:
[cinematic live-action, premium social ad, high contrast, realistic human
performance, elegant motion graphics, subtle film grain, etc.].

Negative prompt:
[no logos, no agency branding, no robots, no AI visuals, no exact WhatsApp UI,
no official seals, no outcome guarantees, no scene cuts, etc.].
```

## Video Ad Pattern For Lawyers

Use this when the ad targets lawyers.

```text
Create a vertical 9:16 social media video, 22 to 24 seconds, single continuous
take, no camera cuts, no montage, no scene cuts.

The camera is a smooth side-tracking camera, filming the subject in profile and
three-quarter view as he walks from left to right through two connected rooms.
The video should feel like a cinematic side-scrolling stage set.

At the start, show a Latin American lawyer, 35 to 45 years old, in a small dark
messy office. The office has dim moody lighting, scattered legal folders,
papers, an old coffee cup, a cluttered desk, closed blinds, and a tired
atmosphere. The lawyer wears a slightly wrinkled shirt and loose tie, holding a
phone with frustration.

Dull gray floating message bubbles appear near his phone as motion-design
overlays. They are generic message bubbles, not an exact WhatsApp interface.
The bubbles show neutral Latin American Spanish text:
Cuanto cuesta?
Solo queria preguntar
Despues te aviso

The lawyer says: Si eres abogado y tu WhatsApp esta lleno de mensajes que no
avanzan... o peor, directamente no suena... no necesitas mas ruido.

As he walks to the right, the messy gray message bubbles stay behind him, shake
softly, compress, and dissolve. The lawyer approaches a doorway and wall
dividing the dark office from a brighter office.

The camera continues moving sideways and passes through the wall with him. For
about one second, show the inside structure of the wall in a cinematic
cross-section: wooden studs, drywall layers, cables, dust particles, insulation
texture, and depth between the rooms. This is a stylish visual transition, not a
cut. During this wall-crossing moment, the lighting changes from dark and heavy
to warm, clean, and professional.

The lawyer says: Necesitas consultas con intencion real.

After crossing the wall, the lawyer enters a new office. The new office is
bright, organized, professional, warm, and active. There are a few clients
waiting, clean folders on a desk, a collaborator moving documents, and a feeling
of a legal practice with controlled workflow. The lawyer's posture becomes more
upright and confident.

Clean inquiry cards appear around his phone, organized and calm. They show:
Tengo un despido
Necesito iniciar una sucesion
Tengo documentos para revisar

The lawyer says: Casos claros, con datos, documentos y motivo de consulta. Eso
es lo que deberia llegar a tu estudio.

Three clean folders slide onto the desk, labeled:
DATOS
DOCUMENTOS
RESUMEN

The lawyer stops in the bright office, looks at his phone, looks around at the
organized clients and workflow, then looks toward camera with calm confidence.

The lawyer says: Si quieres que tu WhatsApp se vea asi, toca el boton y mira
como funciona.

Final on-screen text:
CONSULTAS MAS ORDENADAS
DIRECTO A TU WHATSAPP
TOCA EL BOTON

Visual style: cinematic live-action, premium social ad, high contrast
transformation, dark messy office to bright professional office, side-tracking
camera, practical set design, realistic human performance, elegant motion
graphics, subtle film grain, sharp subject, shallow depth of field,
professional color grading.

Language: all spoken and written Spanish should be neutral Latin American
Spanish, familiar across LatAm. Do not use voseo. Do not use Argentine-specific
slang. Keep it simple, direct, and professional.

Audio: clear natural neutral Latin American Spanish voice, close-mic ad
delivery, subtle cinematic pulse, soft notification sounds when clean inquiry
cards appear, room tone changes from dull in the dark office to warmer in the
bright office.

Negative prompt: no Konecta logo, no agency branding, no robots, no AI visuals,
no futuristic dashboards, no exact WhatsApp interface, no charts, no money
flying, no luxury flex, no courthouse cliches, no judge hammer, no legal scales
as main object, no official seals, no guarantees of legal outcomes, no
guaranteed clients, no guaranteed cases, no winning-lawsuit claims, no camera
cuts, no montage, no scene cuts, no sudden teleportation, no random extra
locations.
```

## Common Fixes

- If the model creates cuts, repeat: `single continuous take, no camera cuts,
  the same camera keeps moving through the whole scene`.
- If the text mutates, reduce text to 2-4 words per card.
- If the ad feels like software, replace dashboards with human artifacts:
  phone, folders, documents, clients waiting, summary card.
- If the ad feels brand-first, remove logos and company mentions; open on the
  buyer's pain.
- If the scene is too busy, keep only one character, one camera path, and three
  outcome artifacts.
- If the language sounds too Argentine, require neutral LatAm Spanish and avoid
  voseo.
