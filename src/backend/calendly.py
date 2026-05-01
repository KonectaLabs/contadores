"""Shared Calendly configuration."""

KONECTA_CALENDLY_URL = "https://calendly.com/facundogoiriz/crecimiento"


def normalize_calendly_url(_url: str | None = None) -> str:
    """Return the only Calendly URL used by every funnel."""
    return KONECTA_CALENDLY_URL
