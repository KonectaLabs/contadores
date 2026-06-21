# Plan 124: Remove Real Provider Identifiers From Docs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- README.md .codex/skills/konecta-meta-ads/SKILL.md wiki/skills/konecta-meta-ads/SKILL.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PRIVACY-03

## Why This Matters

The README includes real-looking Meta account/resource identifiers. They are not access tokens, but committed provider ids create avoidable exposure and invite future agents to treat old local credentials as canonical.

Docs should describe where to configure provider ids without committing the values.

## Current State

- README lists local Meta credentials:

```markdown
README.md:345
Credenciales Meta locales validadas el 2026-05-31:
```

```markdown
README.md:348
- Ad account: `act_396900435976478`
```

- The same block lists business, page, WhatsApp phone number, and WABA ids.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Provider id scan | `rg -n "Credenciales Meta locales|act_[0-9]+|WhatsApp phone number:|WABA|Business:|Page:" README.md .env.example wiki .codex` | docs use placeholders or env names, not real ids |

## Scope

**In scope**:
- Replace committed real-looking provider ids with placeholder examples.
- Preserve useful setup guidance and env variable names.
- Add a note that live provider ids live in local/server secrets only.
- Check related Meta skills for the same pattern.

**Out of scope**:
- Env contract inventory; plan 025 covers `.env.example` completeness.
- Runtime code changes.
- Removing historical client names or business context unrelated to provider ids.

## Git Workflow

- Branch: `codex/remove-provider-ids-from-docs`
- Commit message: `Remove real provider identifiers from docs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace exact ids

Use placeholders such as `act_<META_AD_ACCOUNT_ID>`, `<META_BUSINESS_ID>`, `<META_PAGE_ID>`, `<META_WHATSAPP_PHONE_NUMBER_ID>`, and `<META_WHATSAPP_BUSINESS_ACCOUNT_ID>`.

### Step 2: Preserve verification language

Keep the fact that credentials should be validated locally, but state that actual ids belong in `.env`, 1Password, or server secrets.

### Step 3: Scan docs and skills

Run the provider id scan and update any matching operational doc.

## Test Plan

- Provider id scan returns no real-looking Meta account ids in docs.
- README still names the required env variables.

## Done Criteria

- [ ] Real-looking Meta provider ids are removed from docs.
- [ ] Placeholder/env-name guidance remains clear.
- [ ] Related skills do not reintroduce the same ids.

## STOP Conditions

- A real id is intentionally public and product owner wants it in docs.
- Removing ids would break a documented third-party setup process that has no safer placeholder.

## Maintenance Notes

Docs can say what to configure without storing the current production identifier. Treat provider ids as operational details, not project documentation.
