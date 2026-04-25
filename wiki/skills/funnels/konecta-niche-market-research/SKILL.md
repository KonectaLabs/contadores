---
name: konecta-niche-market-research
description: Create and process market-research prompts for a new Konecta niche funnel. Use before ad prompts, offer copy, Loom decks, WhatsApp sequences, or CRM setup for a new industry.
---

# Konecta Niche Market Research

## Goal

Produce a prompt Facundo can send to the external market-research bot. The output should reveal the strongest pain, outcome, buying trigger, and offer wedge for one niche.

## Prompt Template

Replace bracketed fields and keep the prompt in Spanish unless Facundo asks otherwise.

```text
Quiero investigar el nicho [NICHO] en [PAIS/MERCADO] para venderle una solucion de Konecta Labs.

Contexto de Konecta:
- Somos programadores y podemos crear automatizaciones, LLM workflows, procesamiento de texto/documentos, CRM, WhatsApp automation, websites, SEO y campañas Meta Ads.
- Queremos vender outcomes de negocio, no listar tecnologia.
- Buscamos un nicho donde podamos generar leads, mejorar procesos o ahorrar tiempo con soluciones tecnicas.

Investiga:
1. Dolores mas fuertes del nicho.
2. Tareas repetitivas o documentales que puedan automatizarse.
3. Problemas de captacion de clientes y marketing.
4. Que tipo de cliente quiere atraer ese nicho.
5. Objeciones frecuentes al comprar marketing/automatizacion.
6. Promesas que serian atractivas pero defendibles.
7. Promesas que NO deberiamos hacer porque son riesgosas.
8. Angulos de anuncio para Meta Ads.
9. Como deberia sonar un video Loom de 60 segundos.
10. Preguntas abiertas que necesitamos hacerle a Facundo antes de construir el funnel.

Formato de salida:
- Buyer
- Pain principal
- Outcome deseado
- Oferta recomendada
- Mensaje principal
- 5 hooks de anuncio
- Objeciones
- Riesgos
- Ideas para video de 60 segundos
- Preguntas abiertas
```

## After Research Returns

Summarize into:

- `Buyer`
- `Primary pain`
- `Desired outcome`
- `Offer wedge`
- `Ad hooks`
- `Loom angle`
- `CRM sequence implications`
- `Open questions`

Then hand off to `konecta-niche-ad-images`.

