"""Lead-level guardrails for product Codex work."""

from __future__ import annotations

from backend.database import ContadoresLead, WorkstationClient


CODEX_DISABLED_MESSAGE = "Codex is disabled for this lead."


class CodexDisabledError(RuntimeError):
    """Raised when a lead-level switch blocks Codex work."""


def codex_enabled_for_lead(lead: ContadoresLead | None) -> bool:
    """Return True when Codex may run for a loaded lead."""
    return bool(lead and lead.codex_enabled)


def lead_for_codex_target(target_type: str, target_id: str) -> ContadoresLead | None:
    """Resolve a Codex target to its source lead when one exists."""
    clean_target_type = (target_type or "").strip()
    clean_target_id = (target_id or "").strip()
    if not clean_target_id:
        return None
    if clean_target_type == "lead":
        return ContadoresLead.get_by_id(clean_target_id)
    if clean_target_type == "workstation_client":
        client = WorkstationClient.get_by_id(clean_target_id)
        return ContadoresLead.get_by_id(client.lead_id) if client else None
    return None


def assert_codex_enabled_for_lead(lead: ContadoresLead | None) -> ContadoresLead:
    """Return the lead or raise when its Codex switch is off."""
    if lead is None:
        raise CodexDisabledError("Lead not found.")
    if not codex_enabled_for_lead(lead):
        raise CodexDisabledError(CODEX_DISABLED_MESSAGE)
    return lead


def assert_codex_enabled_for_target(target_type: str, target_id: str) -> None:
    """Raise when a lead-backed target has Codex disabled."""
    clean_target_type = (target_type or "").strip()
    if clean_target_type not in {"lead", "workstation_client"}:
        return
    assert_codex_enabled_for_lead(lead_for_codex_target(clean_target_type, target_id))
