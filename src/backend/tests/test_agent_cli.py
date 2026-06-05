"""Tests for the decoupled Contadores Agent CLI."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from typer.testing import CliRunner

from backend import agent_cli


runner = CliRunner()


class FakeHttp:
    """Capture httpx.request calls and return queued JSON responses."""

    def __init__(self, responses: list[tuple[int, dict[str, object]]] | None = None) -> None:
        self.responses = responses or []
        self.calls: list[dict[str, object]] = []

    def __call__(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "params": kwargs.get("params"),
                "json": kwargs.get("json"),
                "headers": kwargs.get("headers"),
            }
        )
        status_code, payload = self.responses.pop(0) if self.responses else (200, {"ok": True})
        return httpx.Response(status_code, json=payload, request=httpx.Request(method, url))


@pytest.fixture
def config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Use an isolated profile store for CLI tests."""
    path = tmp_path / "profiles.json"
    monkeypatch.setenv(agent_cli.CONFIG_ENV, str(path))
    monkeypatch.delenv(agent_cli.BASE_URL_ENV, raising=False)
    monkeypatch.delenv(agent_cli.TOKEN_ENV, raising=False)
    monkeypatch.delenv(agent_cli.INTERNAL_TOKEN_ENV, raising=False)
    return path


def test_help_lists_agent_cli_groups() -> None:
    """Top-level and subcommand help should be discoverable."""
    root = runner.invoke(agent_cli.app, ["--help"])
    queues = runner.invoke(agent_cli.app, ["queues", "--help"])
    tool = runner.invoke(agent_cli.app, ["tool", "--help"])

    assert root.exit_code == 0
    assert "profile" in root.output
    assert "queues" in root.output
    assert "conversations" in root.output
    assert "campaigns" in root.output
    assert "clients" in root.output
    assert "meta" in root.output
    assert "messages" in root.output
    assert queues.exit_code == 0
    assert "needs-attention" in queues.output
    assert tool.exit_code == 0
    assert "call" in tool.output


def test_login_stores_profile_outside_repo_and_profile_commands_work(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """Login exchanges the browser code and stores a chmod 0600 profile."""

    def fake_receive_login_code(**kwargs: object) -> tuple[str, str]:
        assert kwargs["base_url"] == "https://crm.example"
        assert kwargs["open_browser"] is False
        return "login-code", "http://127.0.0.1:51234/callback"

    fake_http = FakeHttp([(200, {"session_token": "token-1", "user": "facu"})])
    monkeypatch.setattr(agent_cli, "receive_login_code", fake_receive_login_code)
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)

    login_result = runner.invoke(
        agent_cli.app,
        [
            "login",
            "https://crm.example/",
            "--name",
            "local",
            "--no-open-browser",
        ],
    )

    assert login_result.exit_code == 0, login_result.output
    assert json.loads(login_result.output) == {
        "current_profile": "local",
        "profile": "local",
        "status": "logged_in",
    }
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["current_profile"] == "local"
    assert stored["profiles"]["local"] == {
        "base_url": "https://crm.example",
        "token": "token-1",
        "internal_token": "",
    }
    assert fake_http.calls[0]["method"] == "POST"
    assert urlparse(str(fake_http.calls[0]["url"])).path == "/api/agent/auth/cli/exchange"
    assert fake_http.calls[0]["json"] == {"code": "login-code"}

    list_result = runner.invoke(agent_cli.app, ["profile", "list"])
    assert list_result.exit_code == 0, list_result.output
    assert "token-1" not in list_result.output
    list_payload = json.loads(list_result.output)
    assert list_payload["profiles"] == [
        {
            "base_url": "https://crm.example",
            "current": True,
            "has_internal_token": False,
            "has_token": True,
            "name": "local",
        }
    ]

    use_result = runner.invoke(agent_cli.app, ["profile", "use", "local"])
    assert use_result.exit_code == 0, use_result.output
    assert json.loads(use_result.output)["status"] == "selected"

    remove_result = runner.invoke(agent_cli.app, ["profile", "remove", "local"])
    assert remove_result.exit_code == 0, remove_result.output
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "current_profile": None,
        "profiles": {},
    }


def test_login_uses_default_base_url_without_argument(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """The common browser login path should not require passing the CRM URL."""

    def fake_receive_login_code(**kwargs: object) -> tuple[str, str]:
        assert kwargs["base_url"] == agent_cli.DEFAULT_BASE_URL
        assert kwargs["open_browser"] is False
        return "login-code", "http://127.0.0.1:51234/callback"

    fake_http = FakeHttp([(200, {"session_token": "token-default"})])
    monkeypatch.setattr(agent_cli, "receive_login_code", fake_receive_login_code)
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)

    result = runner.invoke(agent_cli.app, ["login", "--no-open-browser"])

    assert result.exit_code == 0, result.output
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["current_profile"] == "default"
    assert stored["profiles"]["default"]["base_url"] == agent_cli.DEFAULT_BASE_URL
    assert fake_http.calls[0]["url"] == f"{agent_cli.DEFAULT_BASE_URL}/api/agent/auth/cli/exchange"


def test_auth_url_uses_cli_start_and_local_callback_state() -> None:
    """Login URL uses the backend CLI start endpoint and carries state."""
    url = agent_cli.auth_url("https://crm.example", "http://127.0.0.1:1234/callback", "state-1")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == "/api/agent/auth/cli/start"
    assert query["callback_url"] == ["http://127.0.0.1:1234/callback"]
    assert query["state"] == ["state-1"]


def test_status_uses_env_fallback_headers_and_pretty_json(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """Commands can run from env fallback without a stored profile."""
    fake_http = FakeHttp([(200, {"ok": True})])
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)
    monkeypatch.setenv(agent_cli.BASE_URL_ENV, "https://crm.test")
    monkeypatch.setenv(agent_cli.TOKEN_ENV, "bearer-token")
    monkeypatch.setenv(agent_cli.INTERNAL_TOKEN_ENV, "internal-token")

    result = runner.invoke(agent_cli.app, ["--pretty", "status"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("{\n")
    assert json.loads(result.output) == {"ok": True}
    call = fake_http.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://crm.test/api/agent/me"
    assert call["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer bearer-token",
        "X-Internal-Token": "internal-token",
    }


def test_status_uses_default_base_url_when_env_only_has_token(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """Env-token automation can omit the base URL and still hit production."""
    fake_http = FakeHttp([(200, {"ok": True})])
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)
    monkeypatch.setenv(agent_cli.TOKEN_ENV, "bearer-token")

    result = runner.invoke(agent_cli.app, ["status"])

    assert result.exit_code == 0, result.output
    assert fake_http.calls[0]["url"] == f"{agent_cli.DEFAULT_BASE_URL}/api/agent/me"
    assert fake_http.calls[0]["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer bearer-token",
    }


def test_global_base_url_overrides_default(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """Operators can target another origin explicitly without changing profiles."""
    fake_http = FakeHttp([(200, {"ok": True})])
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)
    monkeypatch.setenv(agent_cli.TOKEN_ENV, "bearer-token")

    result = runner.invoke(agent_cli.app, ["--base-url", "https://crm.override", "status"])

    assert result.exit_code == 0, result.output
    assert fake_http.calls[0]["url"] == "https://crm.override/api/agent/me"


def test_agent_commands_call_expected_methods_paths_and_bodies(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """CLI commands should remain thin HTTP clients."""
    fake_http = FakeHttp()
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)
    monkeypatch.setenv(agent_cli.BASE_URL_ENV, "https://crm.test/")
    monkeypatch.setenv(agent_cli.TOKEN_ENV, "token")

    commands = [
        (
            ["queues", "list", "--funnel-id", "contadores"],
            "GET",
            "/api/agent/queues",
            {"funnel_id": "contadores"},
            None,
        ),
        (
            ["queues", "needs-attention", "--limit", "3"],
            "GET",
            "/api/agent/queues/needs-attention",
            {"limit": 3},
            None,
        ),
        (
            [
                "conversations",
                "list",
                "--attention-state",
                "needs_reply",
                "--query",
                "ana",
                "--limit",
                "10",
            ],
            "GET",
            "/api/agent/conversations",
            {"attention_state": "needs_reply", "query": "ana", "limit": 10},
            None,
        ),
        (
            ["conversations", "get", "lead-1"],
            "GET",
            "/api/agent/conversations/lead-1",
            None,
            None,
        ),
        (
            ["messages", "lead-1", "--limit", "2"],
            "GET",
            "/api/agent/conversations/lead-1/messages",
            {"limit": 2},
            None,
        ),
        (
            ["send", "lead-1", "hola", "--idempotency-key", "msg-1"],
            "POST",
            "/api/agent/conversations/lead-1/messages",
            None,
            {"text": "hola", "idempotency_key": "msg-1"},
        ),
        (
            ["action", "lead-1", "mark-answered"],
            "POST",
            "/api/agent/conversations/lead-1/actions",
            None,
            {"action": "mark-answered"},
        ),
        (
            ["tags", "set", "lead-1", "hot", "paid"],
            "PUT",
            "/api/agent/conversations/lead-1/tags",
            None,
            {"tags": ["hot", "paid"], "mode": "set"},
        ),
        (
            ["tags", "append", "lead-1", "urgent"],
            "PUT",
            "/api/agent/conversations/lead-1/tags",
            None,
            {"tags": ["urgent"], "mode": "append"},
        ),
        (
            ["note", "add", "lead-1", "Tiene dudas de precio."],
            "POST",
            "/api/agent/conversations/lead-1/notes",
            None,
            {"text": "Tiene dudas de precio."},
        ),
        (
            ["followup", "schedule", "lead-1", "--minutes", "30", "--instruction", "revisar"],
            "POST",
            "/api/agent/conversations/lead-1/followups",
            None,
            {"minutes": 30, "instruction": "revisar"},
        ),
        (
            ["tool", "list"],
            "GET",
            "/api/agent/tools",
            None,
            None,
        ),
        (
            ["clients", "list", "--query", "ana"],
            "GET",
            "/api/agent/clients",
            {"query": "ana"},
            None,
        ),
        (
            ["clients", "create", "--name", "Cliente Uno", "--whatsapp", "+5491111111111", "--dry-run"],
            "POST",
            "/api/agent/clients/converted",
            None,
            {"name": "Cliente Uno", "whatsapp": "+5491111111111", "funnel_id": "contadores", "work_type": "pagina_ads", "status": "paid", "dry_run": True},
        ),
        (
            ["campaigns", "list", "--status", "active"],
            "GET",
            "/api/agent/campaigns",
            {"status": "active"},
            None,
        ),
        (
            ["campaigns", "get", "campaign-1"],
            "GET",
            "/api/agent/campaigns/campaign-1",
            None,
            None,
        ),
        (
            [
                "campaigns",
                "create",
                "--name",
                "Campania",
                "--client-id",
                "client-1",
                "--status",
                "active",
                "--form-schema-json",
                '{"fields":[{"id":"full_name","label":"Nombre","type":"text","required":true}]}',
                "--dry-run",
            ],
            "POST",
            "/api/agent/campaigns",
            None,
            {
                "name": "Campania",
                "client_id": "client-1",
                "status": "active",
                "campaign_info": {},
                "form_schema": {"fields": [{"id": "full_name", "label": "Nombre", "type": "text", "required": True}]},
                "thank_you_title": "Gracias",
                "thank_you_body": "Recibimos tus datos. Te vamos a contactar por WhatsApp.",
                "dry_run": True,
            },
        ),
        (
            ["campaigns", "submissions", "campaign-1", "--limit", "5"],
            "GET",
            "/api/agent/campaigns/campaign-1/submissions",
            {"limit": 5},
            None,
        ),
        (
            ["campaigns", "delivery-source", "campaign-1"],
            "POST",
            "/api/agent/campaigns/campaign-1/delivery-source",
            None,
            None,
        ),
        (
            ["meta", "readiness"],
            "GET",
            "/api/agent/meta/readiness",
            None,
            None,
        ),
        (
            [
                "meta",
                "inventory",
                "--ad-account-id",
                "act_1",
                "--business-id",
                "business_1",
                "--page-id",
                "page_1",
                "--limit",
                "10",
            ],
            "POST",
            "/api/agent/meta/inventory/sync",
            None,
            {
                "ad_account_id": "act_1",
                "business_id": "business_1",
                "page_ids": ["page_1"],
                "include_campaigns": True,
                "include_lead_forms": True,
                "include_pixels": True,
                "include_whatsapp": True,
                "limit": 10,
            },
        ),
        (
            ["tool", "call", "schedule_followup", "--run-id", "run-1", "--json", '{"lead_id":"lead-1"}'],
            "POST",
            "/api/agent/runs/run-1/tools/schedule_followup",
            None,
            {"arguments": {"lead_id": "lead-1"}},
        ),
    ]

    for args, *_ in commands:
        result = runner.invoke(agent_cli.app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"ok": True}

    assert len(fake_http.calls) == len(commands)
    for call, (_, method, path, params, body) in zip(fake_http.calls, commands, strict=True):
        assert call["method"] == method
        assert urlparse(str(call["url"])).path == path
        assert call["params"] == params
        assert call["json"] == body


def test_json_output_and_nonzero_exit_on_api_error(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    """API errors should produce JSON on stderr and a nonzero exit."""
    fake_http = FakeHttp([(400, {"detail": "bad request"})])
    monkeypatch.setattr(agent_cli.httpx, "request", fake_http)
    monkeypatch.setenv(agent_cli.BASE_URL_ENV, "https://crm.test")

    result = runner.invoke(agent_cli.app, ["tool", "list"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "error": {"message": "bad request", "status_code": 400}
    }
