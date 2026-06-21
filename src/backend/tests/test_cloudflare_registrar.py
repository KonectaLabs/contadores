from __future__ import annotations

import json
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from backend import cloudflare_registrar
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


runner = CliRunner()


class FakeCloudflareClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def create_zone(self, domain: str, *, zone_type: str) -> dict[str, object]:
        self.calls.append(("create_zone", {"domain": domain, "zone_type": zone_type}))
        return {"id": "zone-1"}

    def create_dns_record(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("create_dns_record", kwargs))
        return {"id": "record-1"}

    def upsert_dns_record(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(("upsert_dns_record", kwargs))
        return {"id": "record-1"}


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


def test_create_zone_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cloudflare_registrar,
        "run_client_action",
        lambda action: pytest.fail("dry-run must not create a client"),
    )

    result = runner.invoke(cloudflare_registrar.app, ["create-zone", "Example.com"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "domain": "example.com",
        "dry_run": True,
        "next_step": "Rerun with --yes.",
        "type": "full",
    }


def test_create_zone_yes_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeCloudflareClient()
    monkeypatch.setattr(cloudflare_registrar, "run_client_action", lambda action: action(fake_client))

    result = runner.invoke(cloudflare_registrar.app, ["create-zone", "example.com", "--yes"])

    assert result.exit_code == 0, result.output
    assert fake_client.calls == [("create_zone", {"domain": "example.com", "zone_type": "full"})]
    assert json.loads(result.output) == {"id": "zone-1"}


def test_add_record_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cloudflare_registrar,
        "run_client_action",
        lambda action: pytest.fail("zone-id dry-run must not create a client"),
    )

    result = runner.invoke(
        cloudflare_registrar.app,
        [
            "add-record",
            "--zone-id",
            "zone-1",
            "--type",
            "CNAME",
            "--name",
            "www.example.com",
            "--content",
            "target.example.com",
            "--proxied",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "dry_run": True,
        "next_step": "Rerun with --yes.",
        "record": {
            "content": "target.example.com",
            "name": "www.example.com",
            "proxied": True,
            "ttl": 1,
            "type": "CNAME",
        },
        "zone_id": "zone-1",
    }


def test_add_record_yes_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeCloudflareClient()
    monkeypatch.setattr(cloudflare_registrar, "run_client_action", lambda action: action(fake_client))

    result = runner.invoke(
        cloudflare_registrar.app,
        [
            "add-record",
            "--zone-id",
            "zone-1",
            "--type",
            "CNAME",
            "--name",
            "www.example.com",
            "--content",
            "target.example.com",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_client.calls == [
        (
            "create_dns_record",
            {
                "comment": None,
                "content": "target.example.com",
                "name": "www.example.com",
                "priority": None,
                "proxied": None,
                "record_type": "CNAME",
                "ttl": 1,
                "zone_id": "zone-1",
            },
        )
    ]
    assert json.loads(result.output) == {"id": "record-1"}


def test_upsert_record_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cloudflare_registrar,
        "run_client_action",
        lambda action: pytest.fail("zone-id dry-run must not create a client"),
    )

    result = runner.invoke(
        cloudflare_registrar.app,
        [
            "upsert-record",
            "--zone-id",
            "zone-1",
            "--type",
            "A",
            "--name",
            "example.com",
            "--content",
            "192.0.2.1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "dry_run": True,
        "next_step": "Rerun with --yes.",
        "record": {
            "content": "192.0.2.1",
            "name": "example.com",
            "ttl": 1,
            "type": "A",
        },
        "zone_id": "zone-1",
    }


def test_upsert_record_yes_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = FakeCloudflareClient()
    monkeypatch.setattr(cloudflare_registrar, "run_client_action", lambda action: action(fake_client))

    result = runner.invoke(
        cloudflare_registrar.app,
        [
            "upsert-record",
            "--zone-id",
            "zone-1",
            "--type",
            "A",
            "--name",
            "example.com",
            "--content",
            "192.0.2.1",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert fake_client.calls == [
        (
            "upsert_dns_record",
            {
                "comment": None,
                "content": "192.0.2.1",
                "name": "example.com",
                "priority": None,
                "proxied": None,
                "record_type": "A",
                "ttl": 1,
                "zone_id": "zone-1",
            },
        )
    ]
    assert json.loads(result.output) == {"id": "record-1"}
