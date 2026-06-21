"""Small helpers for spreadsheet-openable CSV exports."""

from __future__ import annotations

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def neutralize_spreadsheet_formula(value: object) -> str:
    """Return one CSV cell with spreadsheet formulas neutralized."""
    text = str(value or "")
    if not text:
        return ""
    if text.lstrip(" ").startswith(FORMULA_PREFIXES):
        return f"'{text}"
    return text
