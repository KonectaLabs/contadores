# Plan 015: Limit Recipient Chat Reads In SQL

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Delivery recipient chat endpoint is used as an operator audit thread. It currently loads up to 5000 deliveries for every sibling source sharing the same recipient phone, then sorts and trims in Python. This can become slow exactly for high-volume recipients.

## Current State

- The endpoint gathers every sibling source id, then does a per-source fan-out:

```python
src/backend/endpoints/client_leads.py:1477
crm_leads = ContadoresLead.list_by_normalized_phone(source.normalized_recipient_phone, include_archived=False)
sibling_source_ids = [
    item.id
    for item in ClientLeadSource.list_all()
    if item.normalized_recipient_phone and item.normalized_recipient_phone == source.normalized_recipient_phone
] or [source.id]
deliveries = []
for sibling_source_id in sibling_source_ids:
    deliveries.extend(
        item
        for item in ClientLeadDelivery.list_by_source(sibling_source_id, limit=5000)
        if should_show_recipient_chat_message(item)
    )
deliveries = sorted(deliveries, key=recipient_chat_sort_key)[-limit:]
```

- Visibility excludes pending and blocked rows:

```python
src/backend/endpoints/client_leads.py:424
def should_show_recipient_chat_message(item: ClientLeadDelivery) -> bool:
    status = item.delivery_status.value if isinstance(item.delivery_status, ClientLeadDeliveryStatus) else str(item.delivery_status)
    if status in {ClientLeadDeliveryStatus.PENDING.value, ClientLeadDeliveryStatus.BLOCKED.value}:
        return False
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/endpoints/client_leads.py`
- `src/backend/tests/test_client_lead_delivery.py`

**Out of scope**:
- Changing recipient-chat response shape.
- Changing which statuses are visible.
- Changing CRM lead lookup.

## Git Workflow

- Branch: `codex/limit-recipient-chat-db-reads`
- Commit message: `Limit recipient chat reads in SQL`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add one database helper for chat deliveries

Add a `ClientLeadDelivery` classmethod such as:

```python
list_recipient_chat_deliveries(source_ids: Iterable[str], *, limit: int) -> list[ClientLeadDelivery]
```

Keep it readable:

- normalize `source_ids`,
- filter `source_id.in_(...)`,
- exclude `pending` and `blocked`,
- order by the same fields used by `recipient_chat_sort_key`,
- apply the requested limit in SQL,
- detach rows before returning.

Use descending SQL order plus a final reverse if needed so the endpoint preserves chronological display.

### Step 2: Replace the endpoint fan-out

Update `get_client_lead_recipient_chat()` to call the helper once instead of looping over `list_by_source(..., limit=5000)`.

Preserve fallback to `[source.id]` when no sibling is found.

### Step 3: Add a regression test

Add or extend a Delivery test that creates more visible messages than the requested limit across at least two sibling sources with the same recipient phone.

Assert:

- response count equals the requested limit,
- messages still come from both eligible sibling sources when they are among the latest rows,
- pending and blocked rows are excluded,
- ordering matches the current recipient chat behavior.

## Test Plan

- Delivery endpoint regression for recipient chat.
- Existing Delivery tests.
- Backend import smoke.

## Done Criteria

- [ ] Recipient chat no longer reads 5000 deliveries per sibling source.
- [ ] Response JSON shape is unchanged.
- [ ] Pending and blocked rows stay hidden.
- [ ] Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- The endpoint intentionally needs to scan all historical rows for a product reason not represented by the response limit.
- SQL ordering cannot match `recipient_chat_sort_key` without changing visible ordering.

## Maintenance Notes

This is a local performance fix. It should not change Delivery dispatch, retries, or public campaign submission behavior.
