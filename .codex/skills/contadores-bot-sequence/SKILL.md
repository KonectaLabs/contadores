---
name: contadores-bot-sequence
description: Use when working on the WhatsApp sequence, message copy, timing windows, template opener, Loom step, conversational bot replies, scheduling handoff, manual Calendly actions, or human handoff behavior for Contadores.
---

# Contadores Bot Sequence

Use this skill when editing or reviewing the WhatsApp automation flow.

Contadores is now the first configured funnel in the multi-funnel platform.
Default copy, template names, video strategy definitions, and strategy weights
come from the funnel definition layer. If `data/funnels.json` exists, it can
override the built-in Contadores definition.

## Current sequence

1. Send opener as a WhatsApp template for sheet-imported leads.
   - Click-to-WhatsApp leads whose `referral.source_id` matches the funnel config skip this step because their first inbound message is already the reply.
   - Abogados leads whose first inbound text normalizes to `Hola! Quiero mas informacion de su propuesta para abogados!` also skip this step.
2. Wait for any reply.
3. Wait 30 seconds of silence.
4. Send the Loom intro text.
5. Send the configured Loom strategy:
   - `loom_mp4`: WhatsApp MP4 from `data/contadores/videos/loom_60_seconds_captions.mp4`.
6. Wait 10 minutes.
7. If there is still no reply, send `¿conseguiste ver el video?`
8. Once there are 30 seconds of silence after the post-Loom replies, run the
   conversational bot with the full conversation history, funnel, `funnel_info`,
   stage, latest messages, inferred country/timezone when clear, and commercial
   rules.
   - Primary runtime: ChatGPT-authenticated Codex SDK `gpt-5.5` with medium
     effort, using this skill and `contadores-lead-reply-playbook` as
     structured context.
   - Codex may inspect repository files and use read-only tools/shell commands
     to resolve source-of-truth questions during the runtime decision. It must
     not modify files, external systems, or production state.
   - Fallback order: Codex with API-key auth, then DSPy/Grok 4.3 through
     OpenRouter, or `gpt-5.4-mini` when OpenRouter is not configured.
   - If ChatGPT Codex auth fails, create a runtime email alert with
     `https://auth.openai.com/codex/device` and the server command that
     generates the short-lived device code. Do not pause the lead if the API-key
     Codex fallback or Grok/DSPy answers safely.
   - Static few-shot examples live in code. Do not fetch CRM examples during a
     live conversation.
9. The bot must return one structured action:
   - `send_reply`
   - `ask_scheduling_details`
   - `handoff_human`
   - `handoff_scheduling`
   - `close_lead`
   - `no_action`
10. If the bot answers a known question, queue `sequence_step=ai_reply` and keep
    the lead in its current stage.
    - Copy must follow Facu/operator WhatsApp style: natural, short, not
      AI-polished, and no inverted opening punctuation like `¿` or `¡`.
11. If the bot needs email, day, time, or timezone for a call, queue
    `sequence_step=ai_reply` asking only for the missing detail.
12. If the bot has email, day, and time, queue
    `sequence_step=scheduling_handoff_confirmation`, pause the lead in
    `needs_human`, set `automation_paused_reason=booking_details_collected`,
    and alert Facu with the scheduling details.
13. Inbound audio should be transcribed first with OpenAI
    `gpt-4o-transcribe`; WhatsApp `.ogg` audio is converted with `ffmpeg`.
    Store the original audio as a playable media message, then store the
    transcript as the next inbound message with
    `sequence_step=audio_transcript`.
14. If the bot lacks real data to answer, receives media/audio without
    transcript, sees an exclusion, or hits an uncovered situation, pause in
    `needs_human` and alert the operators.
15. If Codex fails but DSPy/Grok answers safely, keep the lead in its current
    stage, send the fallback reply, and create a runtime email alert with the
    Codex error, fallback action, latest inbound, and CRM link. Only move to
    `needs_human` when both Codex and fallback fail or when the action itself
    requires human/scheduling handoff.

## Company source of truth

The bot must never infer Konecta's identity or origin from the lead country,
phone timezone, or CRM country field.

Use this source of truth before any dynamic context:

- Company: Konecta Labs.
- Legal/trade fact from the Konecta Labs repo: KonectaLabs is the trade name of
  Octopy LLC.
- Positioning: small founder-led applied AI / product studio focused on concrete
  systems, fast delivery, and production use.
- Founders: Facundo Goiriz and Alan Kravchuk.
- Operating mode: remote team working with clients across Latin America and
  other markets.
- Origin answer for leads: `Escribo desde Argentina. Somos Konecta Labs y
  trabajamos remoto para toda Latinoamerica.`
- Do not claim local offices in Ecuador, Bolivia, Paraguay, Mexico, Colombia,
  Chile, Uruguay, Peru, Venezuela, Spain, or any other country unless the source
  of truth is explicitly updated.
- Italian WhatsApp number: Alan lived in Italy and keeps that number. It does
  not mean the service is only for Italy.
- Broader Konecta context: applied AI/product studio with work across education
  course generation, AI avatar learning, conversational audits, WhatsApp/voice
  operations, editorial automation, real estate training, and custom web/AI
  systems. Use this only for trust/context questions, not in every sales reply.
- Current funnel service: a client-acquisition system for professionals.
  Outcome first: more opportunities/inquiries/potential clients writing directly
  to the lead's WhatsApp.
- Mechanism: professional page/landing plus tailored campaigns.
- Current code-level offer: custom professional page + 3 advertising campaigns.
  Manual examples use Facebook/Instagram/Meta. Do not invent Google Ads, TikTok,
  LinkedIn, SEO deliverables, CRM integrations, calendar automation, or monthly
  management unless the funnel/operator explicitly says so.
- Contadores ICP: accountants, accounting firms, tax advisors, and similar
  professionals who want prospects for accounting/tax/business services.
- Abogados ICP: lawyers, law firms, and legal professionals who want inquiries
  for the practice areas they choose to prioritize.
- Delivery: define the target client, service area, geography, and message;
  prepare the page/landing and campaigns; send interested people to the
  professional's WhatsApp. Konecta does not close the client's sales/cases for
  them.
- Runtime price: 300 USD, pago unico. Do not invent monthly fees, installments,
  taxes, invoices, or payment rails unless already provided in the conversation.
- Guarantee: if there are no new consultations/prospects to review in 30 days,
  money back. Never promise closed clients, legal cases, revenue, guaranteed
  appointments, ad approval, exact lead volume, rankings, or exact ROI.
- Consultation/prospect definition: an opportunity is a real person/business
  from the target market writing to the professional's WhatsApp about a relevant
  service. It is not a closed client. When the lead asks this, answer the
  definition persuasively and do not ask for email/day/time in that same answer.
- Never start a reply with `Para estar claros:`, `Para ser claros:`,
  `En resumen:`, or by repeating the lead's question as a heading.
- Scheduling v1: no automatic Calendly. Collect email, day, time, and timezone
  for a 15-minute call, then hand off to a human.
- If a factual question falls outside this source of truth and `funnel_info`,
  use `handoff_human` instead of inventing.

For `De donde son?`, `De que pais escriben?`, `ustedes no son de aca?`, or
similar, answer from this section first. Never answer `Somos de Ecuador` or copy
the lead's country as Konecta's origin.

## Manual-only template

Operators can send `contadores_manual_ping_es_v1` from the backoffice to reopen
the WhatsApp 24-hour window:

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This is not part of the automatic sequence and is not the 24-hour opener
follow-up. It is only queued by a manual operator action and pauses automation
for that lead.

Bulk CRM actions must never preselect `Manual ping`. The operator must
explicitly choose and confirm that template before it can be queued. Bulk
Manual ping requests must include backend confirmation and batch audit metadata.

Closed leads cannot receive outbound WhatsApp messages. Reopen the lead first,
then send the message or template.

Marking a lead as `booked` must not send any WhatsApp message. The legacy
`send-manual-booked` action name is kept as a compatibility alias, but it only
marks the lead as `booked` and pauses automation.

## Manual Calendly actions

Operators have two backoffice actions:

- `send-calendly`: send the configured Calendly intro text and then `https://calendly.com/facundogoiriz/crecimiento`.
- `send-calendly-link`: send only the Calendly URL.

Both actions record `calendly_sent_at` and keep the lead in Manual.
Automation must not send Calendly automatically in the conversational bot flow;
it asks for email, day, and time, then hands the scheduling details to Facu.
The Calendly URL is fixed across Contadores, Abogados, and every other funnel.

## Manual reply ownership

The backoffice Manual stage shows every manual lead. The pipeline also has a
`Needs answer` bucket between Manual and Closed for leads whose current
`manual_reply_status` is `needs_reply`. Once an operator sends a reply or marks
the lead answered, the lead leaves `Needs answer` but remains visible in Manual.

Manual outbound can send text alone or text plus one or more operator-attached
media files. Operators can select files, drop them on the composer, or paste
clipboard images/files. Uploaded outbound files are stored under
`data/contadores/outbound_media/{lead_id}/`, recorded on the queued
`contadores_messages` row, shown in the CRM timeline, and dispatched by the bot
as WhatsApp image, video, audio, or document media.

Manual/custom outbound is only allowed while WhatsApp's 24-hour customer service
window is open. If `last_inbound_at` is older than 24 hours or missing, do not
queue non-template sends. The UI should block the custom composer and point the
operator to an approved template such as `Manual ping`.

## Runtime rule

- This flow runs from sheet-imported leads and Click-to-WhatsApp inbounds.
- Strategy rollout weights are stored in Contadores config as `strategy_weights` and can be seeded with `CONTADORES_STRATEGY_WEIGHTS_JSON`.
- Funnel definitions are stored in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
  The UI and Codex edit the same file.
- Click-to-WhatsApp ad IDs are stored in each funnel as `whatsapp_referral_source_ids`.
  Contadores should stay empty when it has no real campaign; currently the real ad source belongs to Abogados.
- Inbound WhatsApp messages with no matching reply/referral are saved in the built-in `general` inbox, except the approved Abogados prefilled proposal text route.
- If Meta includes the sender WhatsApp profile name, the inbound handler stores it as the lead name for WhatsApp-created leads and fills existing phone-only leads without replacing sheet/operator names.
- Audio transcription needs `OPENAI_API_KEY`; use
  `OPENAI_AUDIO_TRANSCRIPTION_MODEL=gpt-4o-transcribe` by default and keep
  `gpt-4o-mini-transcribe` available as a cheaper env override.

Read [references/sequence.md](references/sequence.md) for the exact messages and timing.
