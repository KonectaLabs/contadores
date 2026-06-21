# Plan 001: Verify Meta Lead Webhook Signatures

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/endpoints/meta_leads.py src/backend/tests/test_client_lead_delivery.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

`/api/meta-leads/webhook` is intentionally public so Meta can call it, but POST delivery currently trusts any JSON body. A forged request can create unresolved platform events, burn Meta API quota through lead fetch attempts, and route webhook processing toward a requested Delivery source. The GET challenge token is not enough; Meta POST webhooks need body HMAC validation before processing.

## Current State

- `src/backend/main.py` exposes `/api/meta-leads/webhook` without a session:

```python
src/backend/main.py:73
PUBLIC_PATHS_WITHOUT_SESSION = {
    "/health",
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/meta-leads/webhook",
    "/api/agent/auth/cli/exchange",
}
```

- `src/backend/endpoints/meta_leads.py` verifies the GET challenge token only:

```python
src/backend/endpoints/meta_leads.py:114
@meta_leads_router.get("/webhook")
async def verify_meta_lead_webhook(request: Request) -> PlainTextResponse:
    expected = _webhook_verify_token()
    ...
```

- `src/backend/endpoints/meta_leads.py` parses POST JSON directly:

```python
src/backend/endpoints/meta_leads.py:129
@meta_leads_router.post("/webhook", response_model=MetaLeadWebhookResponse)
async def receive_meta_lead_webhook(
    request: Request,
    source_id: str | None = Query(default=None),
) -> MetaLeadWebhookResponse:
    try:
        payload = await request.json()
```

- Existing webhook test covers GET token and unsigned POST success:

```python
src/backend/tests/test_client_lead_delivery.py:594
webhook = client.post(
    "/api/meta-leads/webhook",
    json={
        "object": "page",
        "entry": [
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Targeted backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/meta_leads.py`
- `src/backend/tests/test_client_lead_delivery.py`
- `.env.example`
- `README.md`

**Out of scope**:
- Any live Meta call.
- Any change to the GET verification-token flow except shared helper extraction.
- Any use of CleverApply, Alejandro, or `cleverapply` credentials.
- Any push, deploy, or server mutation.

## Git Workflow

- Branch: `codex/verify-meta-webhook-signature`
- Commit message: `Verify Meta lead webhook signatures`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a signature helper

In `src/backend/endpoints/meta_leads.py`, import `hmac` and `hashlib`.

Add helpers near `_webhook_verify_token()`:

- `_webhook_app_secret()` reads `META_APP_SECRET` or `META_WEBHOOK_APP_SECRET`.
- `_verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool`.

Expected behavior:

- If no app secret is configured, POST webhook processing must reject with 503 and a clear setup detail.
- Accept only `sha256=<hex>` from `X-Hub-Signature-256`.
- Compute `hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()`.
- Use `hmac.compare_digest()`.

Do not log or return the secret or computed digest.

**Verify**: `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` should still run, but will fail until tests are updated because existing POST tests are unsigned.

### Step 2: Verify before parsing JSON

In `receive_meta_lead_webhook`, read the raw body once:

```python
raw_body = await request.body()
if not _verify_webhook_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
    raise HTTPException(status_code=403, detail="Invalid Meta webhook signature.")
```

Then parse with `json.loads(raw_body.decode("utf-8") or "{}")` instead of `await request.json()`.

Return 503 when the app secret is missing, 403 when the signature is missing or invalid, and 400 only for malformed JSON.

**Verify**: backend import smoke command prints `backend-import-ok`.

### Step 3: Update webhook tests

In `src/backend/tests/test_client_lead_delivery.py`, add a small test helper that signs raw JSON bytes:

```python
def signed_meta_webhook_headers(body: bytes, secret: str = "test-meta-secret") -> dict[str, str]:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}
```

Update the existing webhook POST test to set `META_APP_SECRET` and post raw content with the signed header.

Add tests for:

- POST without configured app secret returns 503.
- POST with missing signature returns 403.
- POST with bad signature returns 403.
- GET challenge still works with `META_LEAD_WEBHOOK_VERIFY_TOKEN`.

**Verify**: targeted backend tests exit 0.

### Step 4: Document env configuration

Add `META_APP_SECRET=` or `META_WEBHOOK_APP_SECRET=` to `.env.example`.

Add one README sentence in the Meta lead webhook area explaining that POST webhooks require `X-Hub-Signature-256` signed with the Meta app secret. Do not include a real secret.

**Verify**:

```bash
rg -n "META_APP_SECRET|META_WEBHOOK_APP_SECRET|X-Hub-Signature-256" .env.example README.md src/backend/endpoints/meta_leads.py src/backend/tests/test_client_lead_delivery.py
```

Expected: all four paths contain the relevant config/test/code references.

## Test Plan

- Unit/API tests in `src/backend/tests/test_client_lead_delivery.py`.
- Existing successful webhook path must remain covered, but signed.
- Rejection paths must verify status codes before any fake Meta fetch helper is called.

## Done Criteria

- [ ] Unsigned or badly signed POST `/api/meta-leads/webhook` requests are rejected before JSON processing.
- [ ] Missing app secret returns setup failure, not silent acceptance.
- [ ] GET verification challenge still passes.
- [ ] `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` exits 0.
- [ ] `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` prints `backend-import-ok`.
- [ ] No secret value is committed or printed.

## STOP Conditions

- The live Meta webhook uses a different signature header or algorithm than `X-Hub-Signature-256`.
- Tests reveal that FastAPI/TestClient consumes the request body before the helper can parse it.
- Implementing this requires touching auth middleware or public path exemptions outside the listed scope.

## Maintenance Notes

Reviewers should check that the signature is computed over exact raw bytes and that error paths cannot leak secrets or digests. Future webhook endpoints should reuse this pattern instead of adding their own unauthenticated POST body processing.
