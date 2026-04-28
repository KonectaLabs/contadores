---
name: abogados-loom-video
description: Use when editing, regenerating, reviewing, scripting, or exporting the 60-second Konecta Loom sales presentation for the abogados funnel.
---

# Abogados Loom Video

## Canonical Folder

Use:

```text
/Users/fgoiriz/private/repos/contadores/abogados/media/presentations/loom-video-vender-a-abogados/
```

Main files:

- `Loom Script 60s.html`: source deck.
- `deck-export-60s.html`: generated export copy.
- `Konecta-Loom-Vender-a-Abogados-60s.pptx`: exported PPTX.
- `Loom-Script-60s.txt`: voice script.
- `screenshots/`: rendered previews.

## Required Command

After any edit to the HTML, script, export workflow, or notes, run:

```bash
cd /Users/fgoiriz/private/repos/contadores/abogados/media/presentations/loom-video-vender-a-abogados
npm run pptx
```

Then render/review screenshots if visual layout changed.

## Story Arc

Keep the same 8-slide shape as Contadores:

1. WhatsApp outcome.
2. "Como lo hacemos?"
3. Google/search visibility.
4. Three Meta campaigns.
5. USD 300 price.
6. 30-day guarantee.
7. "Que tenes para perder?"
8. Calendly/meeting CTA.

## Current Script

Target: about 60 seconds.

```text
Asi se va a ver tu WhatsApp: consultas de casos que dejan honorarios, como despidos, amparos y sucesiones, entrando directo a tu estudio.

Como lo hacemos?

Te armamos una pagina profesional para abogado, optimizada para Google. Cuando alguien busca abogado laboral, sucesiones o amparos en tu ciudad, apareces arriba.

Y tres campanas publicitarias en Facebook e Instagram. Cada una apunta a un caso concreto que te interesa tomar, y todo empuja al mismo lugar: tu WhatsApp.

Cuanto vale? Trescientos dolares. Un unico pago. Y por eso recibis pagina, campanas y el flujo para que las consultas entren ordenadas.

Tenes treinta dias de garantia. Si no te llegan consultas nuevas para revisar, te devolvemos los trescientos dolares. Cien por ciento garantizado.

Que tenes para perder? Trescientos dolares. Y a las veinticuatro horas empezamos a trabajar en tu estudio juridico para traerte consultas a tu WhatsApp.

Para arrancar, agenda una reunion con nosotros aca abajo. Te espero adentro.
```

## Content Rules

- Preserve Contadores format unless Facundo asks for a redesign.
- Change only what is needed for abogados.
- Use "casos que dejan honorarios" as the main hook.
- Use examples: sucesion con inmueble, despido con telegrama, amparo urgente.
- Keep the guarantee about consultations, not won cases.
- Do not promise legal outcomes.
