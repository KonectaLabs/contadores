# Plan 036: Require Calendly Webhook Signatures

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/tests README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-02

## Why This Matters

The Calendly webhook endpoint can reconcile meetings into Contadores lead state. Today the signature helper returns `True` when `CALENDLY_WEBHOOK_SIGNING_KEY` is unset, so a public route can accept attacker-supplied JSON in a misconfigured deployment.

## Current State

- The signing key is optional at import time:

```python
src/bot/main.py:87
CALENDLY_WEBHOOK_SIGNING_KEY = (os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "") or "").strip()
```

- Missing key currently means success:

```python
src/bot/main.py:99
def verify_calendly_signature(*, payload: bytes, signature_header: str | None) -> bool:
    """Best-effort Calendly webhook signature verification."""
    if not CALENDLY_WEBHOOK_SIGNING_KEY:
        return True
```

- The public webhook only rejects when the helper returns false:

```python
src/bot/main.py:597
@app.post("/webhook/calendly")
async def calendly_webhook(request: Request) -> dict[str, Any]:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |

## Scope

**In scope**:
- `src/bot/main.py`
- `src/bot/tests/`
- `.env.example`
- README webhook configuration notes.

**Out of scope**:
- Changing Calendly payload reconciliation behavior.
- Changing WhatsApp or AgentMail webhook verification.
- Changing backend auth middleware.
- Adding a new secret manager or credential source.

## Git Workflow

- Branch: `codex/require-calendly-webhook-signatures`
- Commit message: `Require Calendly webhook signatures`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Fail closed when the signing key is missing

Change the Calendly verification path so an exposed webhook never accepts unsigned requests because the secret is unset.

Keep the operator signal clear:

- if `CALENDLY_WEBHOOK_SIGNING_KEY` is missing, return `503` from `/webhook/calendly` with a clear detail such as `Calendly webhook signing key is not configured`,
- if the header is missing, return `401`,
- if the header is present but invalid, return `401`.

Do not make the helper silently accept a missing key.

### Step 2: Keep signature parsing explicit

Keep support for the current header parsing shape:

- comma-separated parts,
- `v1=...`,
- `signature=...`,
- raw header fallback.

Use `hmac.compare_digest()` for comparison. Keep the code short and readable.

### Step 3: Add focused tests

Add tests around the helper or endpoint that cover:

- missing signing key returns `503` at the endpoint,
- configured key plus missing header returns `401`,
- configured key plus invalid header returns `401`,
- configured key plus valid HMAC returns success and calls the existing reconciliation path.

Mock the backend client/reconciliation boundary; do not make real backend calls.

### Step 4: Update env and docs

Update `.env.example` so `CALENDLY_WEBHOOK_SIGNING_KEY` is documented as required when the Calendly webhook is exposed.

Update README in the Calendly/webhook section with the fail-closed behavior.

## Test Plan

- Run the bot test command.
- Run the bot import smoke.
- Inspect the endpoint manually and confirm no branch accepts a public Calendly POST when the signing key is unset.

## Done Criteria

- [ ] Missing `CALENDLY_WEBHOOK_SIGNING_KEY` no longer accepts webhook POSTs.
- [ ] Missing or invalid signatures return `401`.
- [ ] Valid signatures still allow the existing reconciliation path.
- [ ] Tests cover missing key, missing header, invalid signature, and valid signature.
- [ ] `.env.example` and README describe the requirement.

## STOP Conditions

- Production intentionally exposes Calendly without signatures and cannot provide a signing key before deploy.
- Calendly sends a different signature header format than the code currently supports, and the real format cannot be verified from docs or a live sample.
- Tests require real Calendly or real backend credentials.

## Maintenance Notes

This endpoint should behave like other public webhooks: public route, private proof. Missing configuration must make the route unavailable, not permissive.
