"""Operator CLI for Cloudflare Registrar and DNS automation."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
import typer
from dotenv import load_dotenv


API_BASE_URL = "https://api.cloudflare.com/client/v4"
app = typer.Typer(help="Cloudflare Registrar and DNS operator CLI.")


class CloudflareApiError(RuntimeError):
    """Raised when Cloudflare rejects a request or local safety checks fail."""


@dataclass(frozen=True)
class CloudflareConfig:
    account_id: str
    api_token: str = ""
    api_email: str = ""
    api_key: str = ""
    api_base_url: str = API_BASE_URL


def normalize_domain(value: str) -> str:
    """Return a lower-case ASCII domain without URL or email noise."""
    clean = value.strip().lower()
    if "://" in clean:
        parsed = urlparse(clean)
        clean = parsed.netloc or parsed.path
    if "@" in clean:
        clean = clean.rsplit("@", 1)[-1]
    clean = clean.split("/", 1)[0].split(":", 1)[0].strip(".")

    try:
        ascii_domain = clean.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise CloudflareApiError(f"Invalid domain: {value}") from error

    labels = ascii_domain.split(".")
    if len(labels) < 2 or len(ascii_domain) > 253:
        raise CloudflareApiError("Use a full domain like example.com.")
    if any(not label or label.startswith("-") or label.endswith("-") for label in labels):
        raise CloudflareApiError(f"Invalid domain: {value}")
    return ascii_domain


def build_registration_payload(
    domain: str,
    *,
    years: int | None,
    auto_renew: bool,
    privacy_mode: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "domain_name": normalize_domain(domain),
        "auto_renew": auto_renew,
        "privacy_mode": privacy_mode,
    }
    if years is not None:
        payload["years"] = years
    return payload


def build_dns_record_payload(
    *,
    record_type: str,
    name: str,
    content: str,
    ttl: int,
    proxied: bool | None,
    priority: int | None,
    comment: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": record_type.upper(),
        "name": name,
        "content": content,
        "ttl": ttl,
    }
    if proxied is not None:
        payload["proxied"] = proxied
    if priority is not None:
        payload["priority"] = priority
    if comment:
        payload["comment"] = comment
    return payload


def require_registrable(
    domain_result: dict[str, Any],
    *,
    max_first_year_usd: Decimal | None,
) -> None:
    name = str(domain_result.get("name") or "requested domain")

    if not domain_result.get("registrable"):
        reason = domain_result.get("reason") or "not_registrable"
        raise CloudflareApiError(f"{name} is not registrable via Cloudflare API: {reason}")

    if domain_result.get("tier") == "premium":
        raise CloudflareApiError(f"{name} is premium. Cloudflare API does not support premium registration.")

    if max_first_year_usd is None:
        return

    pricing = domain_result.get("pricing") or {}
    currency = pricing.get("currency")
    first_year = pricing.get("registration_cost")
    if currency != "USD" or first_year is None:
        raise CloudflareApiError(f"{name} has no USD first-year price to compare against the limit.")

    try:
        first_year_price = Decimal(str(first_year))
    except InvalidOperation as error:
        raise CloudflareApiError(f"{name} returned an invalid first-year price: {first_year}") from error

    if first_year_price > max_first_year_usd:
        raise CloudflareApiError(
            f"{name} first-year price is {first_year_price} USD, above limit {max_first_year_usd} USD."
        )


def load_config() -> CloudflareConfig:
    load_dotenv()
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    api_email = os.getenv("CLOUDFLARE_API_EMAIL", "").strip()
    api_key = os.getenv("CLOUDFLARE_API_KEY", "").strip()
    if not account_id:
        raise CloudflareApiError("Missing CLOUDFLARE_ACCOUNT_ID.")
    if not api_token and not (api_email and api_key):
        raise CloudflareApiError("Missing CLOUDFLARE_API_TOKEN or CLOUDFLARE_API_EMAIL plus CLOUDFLARE_API_KEY.")
    return CloudflareConfig(account_id=account_id, api_token=api_token, api_email=api_email, api_key=api_key)


class CloudflareClient:
    def __init__(self, config: CloudflareConfig, http_client: httpx.Client | None = None):
        self.config = config
        self._client = http_client or httpx.Client(timeout=30)
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        prefer_async: bool = False,
    ) -> Any:
        headers = self._auth_headers()
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if prefer_async:
            headers["Prefer"] = "respond-async"

        url = f"{self.config.api_base_url}{path}"
        response = self._client.request(method, url, params=params, json=json_body, headers=headers)
        try:
            payload = response.json()
        except ValueError as error:
            raise CloudflareApiError(f"Cloudflare returned non-JSON HTTP {response.status_code}.") from error

        if response.is_error or not payload.get("success", False):
            raise CloudflareApiError(_format_api_error(payload, response.status_code))
        return payload.get("result")

    def _auth_headers(self) -> dict[str, str]:
        if self.config.api_token:
            return {"Authorization": f"Bearer {self.config.api_token}"}
        if self.config.api_email and self.config.api_key:
            return {
                "X-Auth-Email": self.config.api_email,
                "X-Auth-Key": self.config.api_key,
            }
        raise CloudflareApiError("Cloudflare auth is not configured.")

    def verify_token(self) -> dict[str, Any]:
        if self.config.api_token:
            return self.request("GET", "/user/tokens/verify")
        accounts = self.list_accounts()
        return {
            "status": "legacy_api_key_ok",
            "account_count": len(accounts),
            "account_ids": [account.get("id") for account in accounts],
        }

    def list_accounts(self) -> list[dict[str, Any]]:
        result = self.request("GET", "/accounts")
        return list(result or [])

    def search_domains(
        self,
        query: str,
        *,
        limit: int,
        extensions: list[str],
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "limit": limit}
        if extensions:
            params["extensions"] = ",".join(ext.strip().lstrip(".") for ext in extensions)
        return self.request("GET", f"/accounts/{self.config.account_id}/registrar/domain-search", params=params)

    def check_domains(self, domains: list[str]) -> dict[str, Any]:
        clean_domains = [normalize_domain(domain) for domain in domains]
        if len(clean_domains) > 20:
            raise CloudflareApiError("Cloudflare domain-check accepts at most 20 domains per request.")
        return self.request(
            "POST",
            f"/accounts/{self.config.account_id}/registrar/domain-check",
            json_body={"domains": clean_domains},
        )

    def create_registration(
        self,
        domain: str,
        *,
        years: int | None,
        auto_renew: bool,
        privacy_mode: str,
        prefer_async: bool,
    ) -> dict[str, Any]:
        payload = build_registration_payload(
            domain,
            years=years,
            auto_renew=auto_renew,
            privacy_mode=privacy_mode,
        )
        return self.request(
            "POST",
            f"/accounts/{self.config.account_id}/registrar/registrations",
            json_body=payload,
            prefer_async=prefer_async,
        )

    def get_registration(self, domain: str) -> dict[str, Any]:
        clean_domain = normalize_domain(domain)
        return self.request("GET", f"/accounts/{self.config.account_id}/registrar/registrations/{clean_domain}")

    def get_registration_status(self, domain: str) -> dict[str, Any]:
        clean_domain = normalize_domain(domain)
        return self.request(
            "GET",
            f"/accounts/{self.config.account_id}/registrar/registrations/{clean_domain}/registration-status",
        )

    def list_zones(self, *, name: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"account.id": self.config.account_id}
        if name:
            params["name"] = normalize_domain(name)
        result = self.request("GET", "/zones", params=params)
        return list(result or [])

    def create_zone(self, domain: str, *, zone_type: str) -> dict[str, Any]:
        return self.request(
            "POST",
            "/zones",
            json_body={
                "account": {"id": self.config.account_id},
                "name": normalize_domain(domain),
                "type": zone_type,
            },
        )

    def create_dns_record(
        self,
        *,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int,
        proxied: bool | None,
        priority: int | None,
        comment: str | None,
    ) -> dict[str, Any]:
        payload = build_dns_record_payload(
            record_type=record_type,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            comment=comment,
        )
        return self.request("POST", f"/zones/{zone_id}/dns_records", json_body=payload)

    def list_dns_records(
        self,
        *,
        zone_id: str,
        record_type: str | None = None,
        name: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if record_type:
            params["type"] = record_type.upper()
        if name:
            params["name"] = name
        result = self.request("GET", f"/zones/{zone_id}/dns_records", params=params)
        return list(result or [])

    def update_dns_record(
        self,
        *,
        zone_id: str,
        record_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int,
        proxied: bool | None,
        priority: int | None,
        comment: str | None,
    ) -> dict[str, Any]:
        payload = build_dns_record_payload(
            record_type=record_type,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            comment=comment,
        )
        return self.request("PATCH", f"/zones/{zone_id}/dns_records/{record_id}", json_body=payload)

    def upsert_dns_record(
        self,
        *,
        zone_id: str,
        record_type: str,
        name: str,
        content: str,
        ttl: int,
        proxied: bool | None,
        priority: int | None,
        comment: str | None,
    ) -> dict[str, Any]:
        matches = self.list_dns_records(zone_id=zone_id, record_type=record_type, name=name)
        if len(matches) > 1:
            raise CloudflareApiError(f"Found multiple {record_type.upper()} records for {name}; use --zone-id manually.")
        if not matches:
            return self.create_dns_record(
                zone_id=zone_id,
                record_type=record_type,
                name=name,
                content=content,
                ttl=ttl,
                proxied=proxied,
                priority=priority,
                comment=comment,
            )
        return self.update_dns_record(
            zone_id=zone_id,
            record_id=str(matches[0]["id"]),
            record_type=record_type,
            name=name,
            content=content,
            ttl=ttl,
            proxied=proxied,
            priority=priority,
            comment=comment,
        )


def _format_api_error(payload: dict[str, Any], status_code: int) -> str:
    errors = payload.get("errors") or []
    messages = [str(error.get("message") or error) for error in errors]
    if not messages:
        messages = [f"HTTP {status_code}"]
    return "Cloudflare API error: " + "; ".join(messages)


def _find_checked_domain(result: dict[str, Any], domain: str) -> dict[str, Any]:
    clean_domain = normalize_domain(domain)
    for domain_result in result.get("domains") or []:
        if str(domain_result.get("name") or "").lower().strip(".") == clean_domain:
            return domain_result
    raise CloudflareApiError(f"Cloudflare did not return a check result for {clean_domain}.")


def _resolve_zone_id(client: CloudflareClient, zone_id: str | None, zone_name: str | None) -> str:
    if zone_id:
        return zone_id
    if not zone_name:
        raise CloudflareApiError("Pass --zone-id or --zone.")
    matches = client.list_zones(name=zone_name)
    if not matches:
        raise CloudflareApiError(f"No Cloudflare zone found for {zone_name}.")
    return str(matches[0]["id"])


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise CloudflareApiError(f"Invalid decimal value: {value}") from error


def print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_client_action(action: Callable[[CloudflareClient], Any]) -> Any:
    try:
        config = load_config()
        client = CloudflareClient(config)
        try:
            return action(client)
        finally:
            client.close()
    except CloudflareApiError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


def command_register(
    client: CloudflareClient,
    *,
    domain: str,
    years: int | None,
    auto_renew: bool,
    privacy_mode: str,
    max_first_year_usd: str | None,
    yes: bool,
    wait: bool,
) -> None:
    if privacy_mode not in {"redaction", "off"}:
        raise CloudflareApiError("Use privacy-mode redaction or off.")
    checked = client.check_domains([domain])
    domain_result = _find_checked_domain(checked, domain)
    price_limit = _parse_decimal(max_first_year_usd)
    require_registrable(domain_result, max_first_year_usd=price_limit)

    if not yes:
        print_json(
            {
                "domain": normalize_domain(domain),
                "dry_run": True,
                "checked": domain_result,
                "next_step": "Rerun with --yes and --max-first-year-usd after approving this exact price.",
            }
        )
        return

    if price_limit is None:
        raise CloudflareApiError("Billable registration requires --max-first-year-usd.")

    registration = client.create_registration(
        domain,
        years=years,
        auto_renew=auto_renew,
        privacy_mode=privacy_mode,
        prefer_async=not wait,
    )
    print_json({"checked": domain_result, "registration": registration})


def command_poll_registration(
    client: CloudflareClient,
    *,
    domain: str,
    interval_seconds: int,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        status = client.get_registration_status(domain)
        print_json(status)
        if status.get("completed") or status.get("state") in {"action_required", "failed"}:
            return
        if time.monotonic() >= deadline:
            raise CloudflareApiError("Timed out waiting for registration status.")
        time.sleep(interval_seconds)


def _dns_record_proxied(proxied: bool, dns_only: bool) -> bool | None:
    if proxied and dns_only:
        raise CloudflareApiError("Use only one of --proxied or --dns-only.")
    return True if proxied else False if dns_only else None


def _dns_record_name(name: str, zone_name: str | None) -> str:
    if not zone_name:
        return name
    clean_zone = normalize_domain(zone_name)
    clean_name = name.strip().strip(".")
    if clean_name == "@":
        return clean_zone
    if "." not in clean_name:
        return f"{clean_name}.{clean_zone}"
    return clean_name


@app.command("verify-token")
def verify_token() -> None:
    """Verify Cloudflare auth without printing secrets."""
    run_client_action(lambda client: print_json(client.verify_token()))


@app.command()
def search(
    query: str,
    limit: int = typer.Option(10, min=1, max=50),
    extensions: str = typer.Option("", help="Comma-separated TLDs, for example: com,net,dev."),
) -> None:
    """Search candidate domains."""
    extension_list = [extension.strip() for extension in extensions.split(",") if extension.strip()]
    run_client_action(lambda client: print_json(client.search_domains(query, limit=limit, extensions=extension_list)))


@app.command()
def check(domains: list[str]) -> None:
    """Check authoritative availability and pricing."""
    run_client_action(lambda client: print_json(client.check_domains(domains)))


@app.command()
def register(
    domain: str,
    years: int | None = typer.Option(None, min=1, max=10),
    auto_renew: bool = typer.Option(False, help="Enable automatic annual renewal."),
    privacy_mode: str = typer.Option("redaction"),
    max_first_year_usd: str | None = typer.Option(None),
    yes: bool = typer.Option(False, help="Confirm the billable registration."),
    wait: bool = typer.Option(False, help="Let Cloudflare hold the request when possible."),
) -> None:
    """Register one domain after an immediate check."""
    run_client_action(
        lambda client: command_register(
            client,
            domain=domain,
            years=years,
            auto_renew=auto_renew,
            privacy_mode=privacy_mode,
            max_first_year_usd=max_first_year_usd,
            yes=yes,
            wait=wait,
        )
    )


@app.command()
def registration(domain: str) -> None:
    """Read a registration resource."""
    run_client_action(lambda client: print_json(client.get_registration(domain)))


@app.command("registration-status")
def registration_status(domain: str) -> None:
    """Read registration workflow status."""
    run_client_action(lambda client: print_json(client.get_registration_status(domain)))


@app.command("poll-registration")
def poll_registration(
    domain: str,
    interval_seconds: int = typer.Option(5, min=1),
    timeout_seconds: int = typer.Option(300, min=1),
) -> None:
    """Poll registration status until terminal state."""
    run_client_action(
        lambda client: command_poll_registration(
            client,
            domain=domain,
            interval_seconds=interval_seconds,
            timeout_seconds=timeout_seconds,
        )
    )


@app.command("list-zones")
def list_zones(name: str | None = None) -> None:
    """List zones on the configured account."""
    run_client_action(lambda client: print_json(client.list_zones(name=name)))


@app.command("create-zone")
def create_zone(
    domain: str,
    zone_type: str = typer.Option("full", "--type", help="full, partial, secondary, or internal."),
) -> None:
    """Create a Cloudflare DNS zone."""
    if zone_type not in {"full", "partial", "secondary", "internal"}:
        raise typer.BadParameter("Use full, partial, secondary, or internal.", param_hint="--type")
    run_client_action(lambda client: print_json(client.create_zone(domain, zone_type=zone_type)))


@app.command("add-record")
def add_record(
    record_type: str = typer.Option(..., "--type"),
    name: str = typer.Option(...),
    content: str = typer.Option(...),
    zone_id: str | None = typer.Option(None),
    zone: str | None = typer.Option(None),
    ttl: int = typer.Option(1, min=1),
    proxied: bool = False,
    dns_only: bool = False,
    priority: int | None = None,
    comment: str | None = None,
) -> None:
    """Create a DNS record in a zone."""

    def action(client: CloudflareClient) -> None:
        selected_zone_id = _resolve_zone_id(client, zone_id, zone)
        print_json(
            client.create_dns_record(
                zone_id=selected_zone_id,
                record_type=record_type,
                name=_dns_record_name(name, zone),
                content=content,
                ttl=ttl,
                proxied=_dns_record_proxied(proxied, dns_only),
                priority=priority,
                comment=comment,
            )
        )

    run_client_action(action)


@app.command("upsert-record")
def upsert_record(
    record_type: str = typer.Option(..., "--type"),
    name: str = typer.Option(...),
    content: str = typer.Option(...),
    zone_id: str | None = typer.Option(None),
    zone: str | None = typer.Option(None),
    ttl: int = typer.Option(1, min=1),
    proxied: bool = False,
    dns_only: bool = False,
    priority: int | None = None,
    comment: str | None = None,
) -> None:
    """Create or update one DNS record in a zone."""

    def action(client: CloudflareClient) -> None:
        selected_zone_id = _resolve_zone_id(client, zone_id, zone)
        print_json(
            client.upsert_dns_record(
                zone_id=selected_zone_id,
                record_type=record_type,
                name=_dns_record_name(name, zone),
                content=content,
                ttl=ttl,
                proxied=_dns_record_proxied(proxied, dns_only),
                priority=priority,
                comment=comment,
            )
        )

    run_client_action(action)


if __name__ == "__main__":
    app()
