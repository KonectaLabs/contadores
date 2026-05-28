"""Small helpers for funnel-owned Calendly URLs."""

from __future__ import annotations


def normalize_calendly_url(url: str | None = None) -> str:
    """Normalize a configured booking URL without choosing one in code."""
    return (url or "").strip().rstrip("/")
