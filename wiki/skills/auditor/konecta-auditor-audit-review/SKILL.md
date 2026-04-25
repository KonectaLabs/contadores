---
name: konecta-auditor-audit-review
description: Review running or recent audits by reading company state, contact transcripts, report artifacts, CEO delivery state, and CRM threads, then surface bugs, prompt fixes, and delivery issues. Use when the user asks to analyze audits, chats, reports, or recent runs.
---

# Konecta Auditor Audit Review

## Use This Skill When
- the user asks to analyze audits that are running,
- the user asks to review the latest completed audits,
- the user asks to inspect chats/transcripts,
- the user asks whether sellers suspect a bot,
- the user asks whether the report reached the CEO or fell back,
- the user asks for bugs or prompt improvements.

## Start With API Truth
Use backend endpoints as the primary source of truth.

Start here:
- `GET /api/companies`
- `GET /api/companies/audit-delivery/poll-state`

Then drill into each target company with:
- `GET /api/companies/{company_id}`
- `GET /api/companies/{company_id}/contacts/{contact_id}/messages`
- `GET /api/companies/{company_id}/artifact-report`
- `GET /api/companies/{company_id}/artifact-pdf-model`
- `GET /api/companies/{company_id}/artifact`
- `GET /api/companies/{company_id}/audit-delivery/ceo-email`
- `GET /api/companies/{company_id}/audit-delivery/email-content`
- `GET /api/companies/{company_id}/audit-delivery/pdf`

If CEO delivery threads exist, also inspect:
- `GET /api/crm/threads`
- `GET /api/crm/threads/{thread_id}`

## Review Workflow
1. Pick the targets:
   - newest companies,
   - `processing`,
   - `completed`,
   - `audited`,
   - companies with replies,
   - or the user-selected company.
2. Read the company detail and every contact transcript.
3. Read the report artifact and PDF-model artifact when present.
4. Read CRM thread history if delivery already created a CEO thread.
5. Correlate transcript behavior, report claims, and delivery state.

## What To Look For In Transcripts
- no response,
- slow response,
- strong response,
- weak discovery,
- robotic repetition,
- obvious bot tells,
- seller explicitly asking if this is a bot,
- off-channel drift,
- awkward tone,
- objective never reached,
- closure logic that feels wrong,
- contact confusion across threads.

Do not skim. Read the full message list for each contact.

## What To Look For In The Report
- seller-only critique, not buyer/bot critique,
- objective/result shown per contact,
- facts grounded in the transcript,
- no invented claims,
- useful prioritization,
- correct contact/outcome mapping,
- evidence of the real business risk.

## Delivery Checks
- If `ceo_email` is empty, say it explicitly.
- If `ceo_email` is empty, note that delivery resolves to the operator fallback:
  - `facundogoiriz@gmail.com`
- If `ceo_delivery_blocked_reason` is set, report the exact reason.
- If `ceo_delivery_sent_at` is missing, say the report was not actually sent yet.
- If CRM thread exists, inspect the CEO response quality and unread state.

## Bug And Improvement Heuristics
Classify findings into:
- prompt/signature issue,
- orchestration/runtime issue,
- persistence/state issue,
- delivery issue,
- report quality issue.

For behavior problems in Stage 2, Stage 3, or Stage 4:
- prefer prompt/signature fixes first,
- only move to Python changes when the issue is deterministic or contractual.

## Required Output Style
Return findings first.

For each finding, include:
- company,
- contact or thread when applicable,
- concrete evidence,
- why it matters,
- likely layer,
- recommended fix.

Also state:
- whether the report exists,
- whether the PDF model exists,
- whether it was sent,
- whether it went to the real CEO email or fallback.

## DB Forensics
Use sqlite only to confirm or debug API inconsistencies.
Do not skip the API review and jump straight to the DB.
