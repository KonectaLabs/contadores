"""HTTP-only Typer CLI for the Contadores Agent API."""

from __future__ import annotations

import json
import os
import secrets
import stat
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Annotated, Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse

import click
import httpx
import typer


CONFIG_ENV = "CONTADORES_AGENT_CONFIG"
BASE_URL_ENV = "CONTADORES_AGENT_BASE_URL"
TOKEN_ENV = "CONTADORES_AGENT_TOKEN"
INTERNAL_TOKEN_ENV = "CONTADORES_AGENT_INTERNAL_TOKEN"
CONFIG_MODE = stat.S_IRUSR | stat.S_IWUSR
API_PREFIX = "/api/agent"
LOCAL_CALLBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

app = typer.Typer(no_args_is_help=True, help="Operate the Contadores Agent API over HTTP.")
profile_app = typer.Typer(no_args_is_help=True, help="Manage local Agent API profiles.")
queues_app = typer.Typer(no_args_is_help=True, help="Read CRM queues.")
conversations_app = typer.Typer(no_args_is_help=True, help="Read CRM conversations.")
tags_app = typer.Typer(no_args_is_help=True, help="Set or append conversation tags.")
note_app = typer.Typer(no_args_is_help=True, help="Add conversation notes.")
followup_app = typer.Typer(no_args_is_help=True, help="Schedule future agent follow-ups.")
tool_app = typer.Typer(no_args_is_help=True, help="List and call audited tools.")


@dataclass(frozen=True)
class RuntimeOptions:
    """Global CLI options."""

    profile: str | None
    pretty: bool


@dataclass(frozen=True)
class AgentProfile:
    """Resolved HTTP client profile."""

    name: str
    base_url: str
    token: str = ""
    internal_token: str = ""
    from_env: bool = False


class AgentCliError(RuntimeError):
    """Raised for user-facing CLI failures."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def config_path() -> Path:
    """Return the local profile store path outside the repo."""
    configured = os.getenv(CONFIG_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "contadores-agent" / "profiles.json"


def empty_config() -> dict[str, Any]:
    return {"current_profile": None, "profiles": {}}


def load_config() -> dict[str, Any]:
    """Load local CLI profiles."""
    path = config_path()
    if not path.exists():
        return empty_config()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AgentCliError(f"Could not read Agent CLI config: {error}") from error

    profiles = payload.get("profiles")
    if not isinstance(profiles, dict):
        raise AgentCliError("Agent CLI config is invalid: profiles must be an object.")
    return {"current_profile": payload.get("current_profile"), "profiles": profiles}


def save_config(config: dict[str, Any]) -> None:
    """Persist local CLI profiles with user-only permissions."""
    path = config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        path.chmod(CONFIG_MODE)
    except OSError as error:
        raise AgentCliError(f"Could not write Agent CLI config: {error}") from error


def runtime_options() -> RuntimeOptions:
    """Return Typer context options for formatting/profile selection."""
    ctx = click.get_current_context(silent=True)
    if ctx is None or ctx.obj is None:
        return RuntimeOptions(profile=None, pretty=False)
    return ctx.obj


def print_json(payload: Any, *, err: bool = False) -> None:
    """Print machine-readable JSON by default."""
    options = runtime_options()
    if options.pretty:
        text = json.dumps(payload, indent=2, sort_keys=True)
    else:
        text = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    typer.echo(text, err=err)


def exit_with_error(error: AgentCliError) -> None:
    payload: dict[str, Any] = {"error": {"message": str(error)}}
    if error.status_code is not None:
        payload["error"]["status_code"] = error.status_code
    print_json(payload, err=True)
    raise typer.Exit(1) from error


def clean_url(value: str) -> str:
    """Validate and normalize a CRM base URL."""
    cleaned = (value or "").strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentCliError("Use an absolute CRM base URL, for example https://crm.fgoiriz.com.")
    return cleaned


def clean_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop empty query/body fields while keeping falsey explicit values like 0."""
    return {key: value for key, value in params.items() if value is not None}


def clean_tags(values: list[str]) -> list[str]:
    """Normalize comma-separated and repeated tag arguments."""
    tags: list[str] = []
    for value in values:
        for item in value.split(","):
            tag = item.strip()
            if tag:
                tags.append(tag)
    if not tags:
        raise AgentCliError("Provide at least one tag.")
    return tags


def parse_json_object(value: str) -> dict[str, Any]:
    """Parse a JSON object CLI option."""
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise AgentCliError(f"Invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise AgentCliError("--json must be a JSON object.")
    return parsed


def profile_from_payload(name: str, payload: dict[str, Any], *, fallback_base_url: str = "") -> AgentProfile:
    """Build one profile from stored JSON plus env fallbacks."""
    return AgentProfile(
        name=name,
        base_url=clean_url(str(payload.get("base_url") or fallback_base_url)),
        token=str(payload.get("token") or payload.get("session_token") or ""),
        internal_token=str(payload.get("internal_token") or ""),
    )


def resolve_profile() -> AgentProfile:
    """Resolve the active profile or env fallback for one API call."""
    options = runtime_options()
    config = load_config()
    profiles = config["profiles"]
    selected_name = options.profile or config.get("current_profile")

    if options.profile and options.profile not in profiles:
        raise AgentCliError(f"Profile not found: {options.profile}")

    env_base_url = os.getenv(BASE_URL_ENV, "").strip()
    env_token = os.getenv(TOKEN_ENV, "").strip()
    env_internal_token = os.getenv(INTERNAL_TOKEN_ENV, "").strip()
    profile_payload = profiles.get(selected_name) if selected_name else None

    if profile_payload is None:
        if not env_base_url:
            raise AgentCliError(f"No Agent API profile is selected and {BASE_URL_ENV} is not set.")
        return AgentProfile(
            name="env",
            base_url=clean_url(env_base_url),
            token=env_token,
            internal_token=env_internal_token,
            from_env=True,
        )

    profile = profile_from_payload(str(selected_name), profile_payload, fallback_base_url=env_base_url)
    return AgentProfile(
        name=profile.name,
        base_url=profile.base_url,
        token=profile.token or env_token,
        internal_token=profile.internal_token or env_internal_token,
    )


class AgentClient:
    """Small HTTP client for the Agent API."""

    def __init__(self, profile: AgentProfile) -> None:
        self.profile = profile

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.profile.token:
            headers["Authorization"] = f"Bearer {self.profile.token}"
        if self.profile.internal_token:
            headers["X-Internal-Token"] = self.profile.internal_token

        try:
            response = httpx.request(
                method,
                f"{self.profile.base_url}{path}",
                params=params,
                json=json_body,
                headers=headers,
                timeout=30,
            )
        except httpx.HTTPError as error:
            raise AgentCliError(f"HTTP request failed: {error}") from error

        try:
            payload = response.json()
        except ValueError as error:
            raise AgentCliError(
                f"Agent API returned non-JSON HTTP {response.status_code}.",
                status_code=response.status_code,
            ) from error

        if response.is_error:
            raise AgentCliError(format_api_error(payload), status_code=response.status_code)
        return payload


def format_api_error(payload: Any) -> str:
    """Extract a concise API error message."""
    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload.get("message")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail, separators=(",", ":"), sort_keys=True)
    return "Agent API request failed."


def api_client() -> AgentClient:
    return AgentClient(resolve_profile())


def run_api_call(action: Callable[[AgentClient], Any]) -> None:
    try:
        print_json(action(api_client()))
    except AgentCliError as error:
        exit_with_error(error)


def api_path(*parts: str) -> str:
    """Build a safely escaped Agent API path."""
    encoded = [quote(part.strip("/"), safe="") for part in parts if part]
    if not encoded:
        return API_PREFIX
    return f"{API_PREFIX}/{'/'.join(encoded)}"


def auth_url(base_url: str, callback_url: str, state: str) -> str:
    """Return the browser URL that starts CLI login from a web session."""
    query = urlencode({"callback_url": callback_url, "state": state})
    return f"{base_url}{API_PREFIX}/auth/cli/start?{query}"


def receive_login_code(
    *,
    base_url: str,
    host: str,
    port: int,
    state: str,
    timeout_seconds: int,
    open_browser: bool,
) -> tuple[str, str]:
    """Open a localhost callback server and wait for the browser redirect."""
    if host not in LOCAL_CALLBACK_HOSTS:
        raise AgentCliError("Callback host must be localhost, 127.0.0.1, or ::1.")
    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            result["code"] = (query.get("code") or [""])[0]
            result["state"] = (query.get("state") or [""])[0]
            result["error"] = (query.get("error") or [""])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Contadores Agent login received. You can close this tab.")

        def log_message(self, format: str, *args: Any) -> None:
            return None

    with HTTPServer((host, port), CallbackHandler) as server:
        server.timeout = timeout_seconds
        actual_port = int(server.server_address[1])
        callback_url = f"http://{host}:{actual_port}/callback"
        if open_browser:
            webbrowser.open(auth_url(base_url, callback_url, state))
        server.handle_request()

    if result.get("error"):
        raise AgentCliError(f"Login failed: {result['error']}")
    if not result.get("code"):
        raise AgentCliError("Timed out waiting for Agent API login callback.")
    if result.get("state") != state:
        raise AgentCliError("Login callback state did not match.")
    return result["code"], callback_url


def token_from_login_response(payload: Any) -> tuple[str, str]:
    """Extract the signed CLI session token returned by code exchange."""
    if not isinstance(payload, dict):
        raise AgentCliError("Login response must be a JSON object.")
    token = str(payload.get("session_token") or payload.get("access_token") or payload.get("token") or "").strip()
    internal_token = str(payload.get("internal_token") or "").strip()
    if not token:
        raise AgentCliError("Login response did not include a session token.")
    return token, internal_token


@app.callback()
def main(
    ctx: typer.Context,
    profile: str | None = typer.Option(None, "--profile", "-p", help="Local profile name to use."),
    pretty: bool = typer.Option(False, "--pretty", help="Print indented JSON."),
) -> None:
    """Configure shared CLI options."""
    ctx.obj = RuntimeOptions(profile=profile, pretty=pretty)


@app.command()
def login(
    url: str | None = typer.Argument(None, help="CRM base URL, normally https://crm.fgoiriz.com."),
    base_url: str | None = typer.Option(None, "--base-url", help="Fallback CRM base URL."),
    name: str | None = typer.Option(None, "--name", help="Profile name to store."),
    callback_host: str = typer.Option("127.0.0.1", "--callback-host"),
    callback_port: int = typer.Option(0, "--callback-port", min=0),
    timeout_seconds: int = typer.Option(120, "--timeout-seconds", min=1),
    open_browser: bool = typer.Option(True, "--open-browser/--no-open-browser"),
) -> None:
    """Open browser login, receive a localhost callback, and store the CLI token."""
    try:
        options = runtime_options()
        profile_name = name or options.profile or "default"
        config = load_config()
        existing = config["profiles"].get(profile_name, {})
        selected_base_url = url or base_url or existing.get("base_url") or os.getenv(BASE_URL_ENV, "")
        clean_base_url = clean_url(str(selected_base_url))
        state = secrets.token_urlsafe(24)
        code, _callback_url = receive_login_code(
            base_url=clean_base_url,
            host=callback_host,
            port=callback_port,
            state=state,
            timeout_seconds=timeout_seconds,
            open_browser=open_browser,
        )
        client = AgentClient(AgentProfile(name=profile_name, base_url=clean_base_url))
        payload = client.request("POST", api_path("auth", "cli", "exchange"), json_body={"code": code})
        token, internal_token = token_from_login_response(payload)

        config["profiles"][profile_name] = {
            "base_url": clean_base_url,
            "token": token,
            "internal_token": internal_token,
        }
        config["current_profile"] = profile_name
        save_config(config)
        print_json({"current_profile": profile_name, "profile": profile_name, "status": "logged_in"})
    except AgentCliError as error:
        exit_with_error(error)


@app.command()
def status() -> None:
    """Verify the selected Agent API profile."""
    run_api_call(lambda client: client.request("GET", api_path("me")))


@app.command()
def logout() -> None:
    """Revoke the selected token and clear it from the local profile."""

    def action(client: AgentClient) -> Any:
        payload = client.request("POST", api_path("auth", "logout"))
        if client.profile.from_env:
            return {"api": payload, "local_profile_updated": False}

        config = load_config()
        profile_payload = config["profiles"].get(client.profile.name)
        if isinstance(profile_payload, dict):
            profile_payload["token"] = ""
            profile_payload["internal_token"] = ""
            save_config(config)
            return {"api": payload, "local_profile_updated": True, "profile": client.profile.name}
        return {"api": payload, "local_profile_updated": False}

    run_api_call(action)


@app.command()
def messages(
    lead_id: str,
    limit: int | None = typer.Option(None, "--limit", min=1),
) -> None:
    """List messages for one conversation."""
    run_api_call(
        lambda client: client.request(
            "GET",
            api_path("conversations", lead_id, "messages"),
            params=clean_params({"limit": limit}),
        )
    )


@app.command()
def send(
    lead_id: str,
    text: str,
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Send one outbound CRM message."""
    run_api_call(
        lambda client: client.request(
            "POST",
            api_path("conversations", lead_id, "messages"),
            json_body=clean_params(
                {
                    "text": text,
                    "idempotency_key": idempotency_key,
                    "dry_run": dry_run if dry_run else None,
                }
            ),
        )
    )


@app.command()
def action(
    lead_id: str,
    action_name: str = typer.Argument(..., metavar="ACTION"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run one existing CRM action."""
    run_api_call(
        lambda client: client.request(
            "POST",
            api_path("conversations", lead_id, "actions"),
            json_body=clean_params({"action": action_name, "dry_run": dry_run if dry_run else None}),
        )
    )


@profile_app.command("list")
def profile_list() -> None:
    """List configured profiles without printing secrets."""
    try:
        config = load_config()
        current = config.get("current_profile")
        profiles = []
        for name, payload in sorted(config["profiles"].items()):
            profiles.append(
                {
                    "name": name,
                    "base_url": payload.get("base_url"),
                    "current": name == current,
                    "has_token": bool(payload.get("token") or payload.get("session_token")),
                    "has_internal_token": bool(payload.get("internal_token")),
                }
            )
        print_json({"config_path": str(config_path()), "current_profile": current, "profiles": profiles})
    except AgentCliError as error:
        exit_with_error(error)


@profile_app.command("use")
def profile_use(name: str) -> None:
    """Set the default local profile."""
    try:
        config = load_config()
        if name not in config["profiles"]:
            raise AgentCliError(f"Profile not found: {name}")
        config["current_profile"] = name
        save_config(config)
        print_json({"current_profile": name, "status": "selected"})
    except AgentCliError as error:
        exit_with_error(error)


@profile_app.command("remove")
def profile_remove(name: str) -> None:
    """Remove a local profile."""
    try:
        config = load_config()
        if name not in config["profiles"]:
            raise AgentCliError(f"Profile not found: {name}")
        del config["profiles"][name]
        if config.get("current_profile") == name:
            config["current_profile"] = None
        save_config(config)
        print_json({"profile": name, "status": "removed"})
    except AgentCliError as error:
        exit_with_error(error)


@queues_app.command("list")
def queues_list(
    funnel_id: str | None = typer.Option(None, "--funnel-id"),
    include_archived: bool = typer.Option(False, "--include-archived"),
) -> None:
    """List queues visible to the Agent API."""
    run_api_call(
        lambda client: client.request(
            "GET",
            api_path("queues"),
            params=clean_params(
                {
                    "funnel_id": funnel_id,
                    "include_archived": include_archived if include_archived else None,
                }
            ),
        )
    )


@queues_app.command("needs-attention")
def queues_needs_attention(
    funnel_id: str | None = typer.Option(None, "--funnel-id"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    messages_per_lead: int | None = typer.Option(None, "--messages-per-lead", min=0),
) -> None:
    """List conversations that need attention."""
    run_api_call(
        lambda client: client.request(
            "GET",
            api_path("queues", "needs-attention"),
            params=clean_params(
                {
                    "funnel_id": funnel_id,
                    "limit": limit,
                    "messages_per_lead": messages_per_lead,
                }
            ),
        )
    )


@conversations_app.command("list")
def conversations_list(
    funnel_id: str | None = typer.Option(None, "--funnel-id"),
    queue_state: str | None = typer.Option(None, "--queue-state"),
    attention_state: str | None = typer.Option(None, "--attention-state"),
    manual_reply_status: str | None = typer.Option(None, "--manual-reply-status"),
    pipeline_stage: str | None = typer.Option(None, "--pipeline-stage"),
    terminal_state: str | None = typer.Option(None, "--terminal-state"),
    tag: str | None = typer.Option(None, "--tag"),
    platform: str | None = typer.Option(None, "--platform"),
    query: str | None = typer.Option(None, "--query"),
    limit: int | None = typer.Option(None, "--limit", min=1),
    messages_per_lead: int | None = typer.Option(None, "--messages-per-lead", min=0),
    include_archived: bool = typer.Option(False, "--include-archived"),
) -> None:
    """List CRM conversations."""
    run_api_call(
        lambda client: client.request(
            "GET",
            api_path("conversations"),
            params=clean_params(
                {
                    "funnel_id": funnel_id,
                    "queue_state": queue_state,
                    "attention_state": attention_state,
                    "manual_reply_status": manual_reply_status,
                    "pipeline_stage": pipeline_stage,
                    "terminal_state": terminal_state,
                    "tag": tag,
                    "platform": platform,
                    "query": query,
                    "limit": limit,
                    "messages_per_lead": messages_per_lead,
                    "include_archived": include_archived if include_archived else None,
                }
            ),
        )
    )


@conversations_app.command("get")
def conversations_get(lead_id: str) -> None:
    """Fetch one CRM conversation."""
    run_api_call(lambda client: client.request("GET", api_path("conversations", lead_id)))


@tags_app.command("set")
def tags_set(lead_id: str, tags: Annotated[list[str], typer.Argument()]) -> None:
    """Replace conversation tags."""
    try:
        tag_list = clean_tags(tags)
    except AgentCliError as error:
        exit_with_error(error)
    run_api_call(
        lambda client: client.request(
            "PUT",
            api_path("conversations", lead_id, "tags"),
            json_body={"tags": tag_list, "mode": "set"},
        )
    )


@tags_app.command("append")
def tags_append(lead_id: str, tags: Annotated[list[str], typer.Argument()]) -> None:
    """Append conversation tags."""
    try:
        tag_list = clean_tags(tags)
    except AgentCliError as error:
        exit_with_error(error)
    run_api_call(
        lambda client: client.request(
            "PUT",
            api_path("conversations", lead_id, "tags"),
            json_body={"tags": tag_list, "mode": "append"},
        )
    )


@note_app.command("add")
def note_add(lead_id: str, text: str) -> None:
    """Add an internal note to a conversation."""
    run_api_call(
        lambda client: client.request(
            "POST",
            api_path("conversations", lead_id, "notes"),
            json_body={"text": text},
        )
    )


@followup_app.command("schedule")
def followup_schedule(
    lead_id: str,
    minutes: int = typer.Option(..., "--minutes", min=1),
    instruction: str = typer.Option(..., "--instruction"),
    idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Schedule a follow-up for a conversation."""
    run_api_call(
        lambda client: client.request(
            "POST",
            api_path("conversations", lead_id, "followups"),
            json_body=clean_params(
                {
                    "minutes": minutes,
                    "instruction": instruction,
                    "idempotency_key": idempotency_key,
                    "dry_run": dry_run if dry_run else None,
                }
            ),
        )
    )


@tool_app.command("list")
def tool_list() -> None:
    """List tools exposed by the Agent API."""
    run_api_call(lambda client: client.request("GET", api_path("tools")))


@tool_app.command("call")
def tool_call(
    tool_name: str,
    json_text: str = typer.Option("{}", "--json", help="Tool arguments as a JSON object."),
    run_id: str | None = typer.Option(None, "--run-id", help="Existing AgentRun id to attach to."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Call one audited Agent API tool."""
    try:
        arguments = parse_json_object(json_text)
    except AgentCliError as error:
        exit_with_error(error)
    clean_run_id = run_id or f"agent-cli-{secrets.token_urlsafe(12)}"
    run_api_call(
        lambda client: client.request(
            "POST",
            api_path("runs", clean_run_id, "tools", tool_name),
            json_body=clean_params({"arguments": arguments, "dry_run": dry_run if dry_run else None}),
        )
    )


app.add_typer(profile_app, name="profile")
app.add_typer(queues_app, name="queues")
app.add_typer(conversations_app, name="conversations")
app.add_typer(tags_app, name="tags")
app.add_typer(note_app, name="note")
app.add_typer(followup_app, name="followup")
app.add_typer(tool_app, name="tool")


if __name__ == "__main__":
    app()
