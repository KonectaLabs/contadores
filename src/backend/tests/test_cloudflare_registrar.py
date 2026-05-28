from __future__ import annotations

from decimal import Decimal

import pytest

from backend.cloudflare_registrar import (
    CloudflareApiError,
    CloudflareConfig,
    CloudflareClient,
    _dns_record_name,
    build_dns_record_payload,
    build_registration_payload,
    normalize_domain,
    require_registrable,
)


def test_normalize_domain_removes_url_noise() -> None:
    assert normalize_domain("https://WWW.Example.com/path?x=1") == "www.example.com"


def test_registration_payload_omits_optional_billing_fields_by_default() -> None:
    assert build_registration_payload(
        "Example.com",
        years=None,
        auto_renew=False,
        privacy_mode="redaction",
    ) == {
        "domain_name": "example.com",
        "auto_renew": False,
        "privacy_mode": "redaction",
    }


def test_require_registrable_rejects_unavailable_domain() -> None:
    with pytest.raises(CloudflareApiError, match="domain_unavailable"):
        require_registrable(
            {"name": "example.com", "registrable": False, "reason": "domain_unavailable"},
            max_first_year_usd=Decimal("20"),
        )


def test_require_registrable_rejects_premium_domain() -> None:
    with pytest.raises(CloudflareApiError, match="premium"):
        require_registrable(
            {"name": "example.com", "registrable": True, "tier": "premium"},
            max_first_year_usd=Decimal("200"),
        )


def test_require_registrable_enforces_first_year_price_limit() -> None:
    with pytest.raises(CloudflareApiError, match="above limit"):
        require_registrable(
            {
                "name": "example.com",
                "registrable": True,
                "tier": "standard",
                "pricing": {
                    "currency": "USD",
                    "registration_cost": "25.00",
                    "renewal_cost": "25.00",
                },
            },
            max_first_year_usd=Decimal("15"),
        )


def test_auth_headers_prefer_api_token() -> None:
    client = CloudflareClient(
        CloudflareConfig(
            account_id="account",
            api_token="token",
            api_email="user@example.com",
            api_key="global-key",
        )
    )
    assert client._auth_headers() == {"Authorization": "Bearer token"}
    client.close()


def test_auth_headers_support_legacy_api_key() -> None:
    client = CloudflareClient(
        CloudflareConfig(
            account_id="account",
            api_email="user@example.com",
            api_key="global-key",
        )
    )
    assert client._auth_headers() == {
        "X-Auth-Email": "user@example.com",
        "X-Auth-Key": "global-key",
    }
    client.close()


def test_dns_record_payload_keeps_proxy_choice_explicit() -> None:
    assert build_dns_record_payload(
        record_type="cname",
        name="www.example.com",
        content="contadores.fgoiriz.com",
        ttl=1,
        proxied=True,
        priority=None,
        comment="workstation",
    ) == {
        "type": "CNAME",
        "name": "www.example.com",
        "content": "contadores.fgoiriz.com",
        "ttl": 1,
        "proxied": True,
        "comment": "workstation",
    }


def test_dns_record_name_expands_relative_names_against_zone() -> None:
    assert _dns_record_name("www", "example.com") == "www.example.com"
    assert _dns_record_name("@", "example.com") == "example.com"
    assert _dns_record_name("api.example.com", "example.com") == "api.example.com"
