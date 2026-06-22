"""Pytest config for bot local module imports."""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
import types
from pathlib import Path

import pytest

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

PROVIDER_ENV_VARS = (
    "AGENTMAIL_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "META_ACCESS_TOKEN",
    "META_APP_SECRET",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "WA_ACCESS_TOKEN",
    "WA_APP_SECRET",
    "WHATSAPP_ACCESS_TOKEN",
)

for env_name in PROVIDER_ENV_VARS:
    os.environ.pop(env_name, None)


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str):
        return True
    clean_host = host.strip("[]").lower()
    if clean_host in {"", "localhost", "testserver"}:
        return True
    try:
        return ipaddress.ip_address(clean_host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch, request) -> None:
    """Fail closed when tests accidentally open real provider connections."""
    if not _env_truthy("PYTEST_KEEP_PROVIDER_SECRETS"):
        for name in PROVIDER_ENV_VARS:
            monkeypatch.delenv(name, raising=False)

    if (
        _env_truthy("PYTEST_ALLOW_NETWORK")
        or request.node.get_closest_marker("network")
        or request.node.get_closest_marker("external")
    ):
        return

    real_connect = socket.socket.connect

    def guarded_connect(self, address):
        if not isinstance(address, tuple) or _is_loopback_host(address[0]):
            return real_connect(self, address)
        raise RuntimeError(f"External network is disabled during tests: {address!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

if "agentmail" not in sys.modules:
    agentmail_module = types.ModuleType("agentmail")

    class DummyAsyncAgentMail:
        """Minimal AgentMail stub so provider imports work in tests."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    class DummyAgentMailEnvironment:
        """Minimal AgentMail environment enum stub."""

        PRODUCTION = "production"

    agentmail_module.AsyncAgentMail = DummyAsyncAgentMail
    agentmail_module.AgentMailEnvironment = DummyAgentMailEnvironment
    sys.modules["agentmail"] = agentmail_module

if "google" not in sys.modules:
    google_module = types.ModuleType("google")
    google_auth_module = types.ModuleType("google.auth")
    google_auth_transport_module = types.ModuleType("google.auth.transport")
    google_auth_requests_module = types.ModuleType("google.auth.transport.requests")
    google_oauth2_module = types.ModuleType("google.oauth2")
    google_oauth2_credentials_module = types.ModuleType("google.oauth2.credentials")
    googleapiclient_module = types.ModuleType("googleapiclient")
    googleapiclient_discovery_module = types.ModuleType("googleapiclient.discovery")

    class DummyRequest:
        """Minimal Google auth Request stub."""

    class DummyCredentials:
        """Minimal Google OAuth credentials stub."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    def dummy_build(*args, **kwargs):
        """Minimal Google API builder stub."""
        return None

    google_auth_requests_module.Request = DummyRequest
    google_oauth2_credentials_module.Credentials = DummyCredentials
    googleapiclient_discovery_module.build = dummy_build

    sys.modules["google"] = google_module
    sys.modules["google.auth"] = google_auth_module
    sys.modules["google.auth.transport"] = google_auth_transport_module
    sys.modules["google.auth.transport.requests"] = google_auth_requests_module
    sys.modules["google.oauth2"] = google_oauth2_module
    sys.modules["google.oauth2.credentials"] = google_oauth2_credentials_module
    sys.modules["googleapiclient"] = googleapiclient_module
    sys.modules["googleapiclient.discovery"] = googleapiclient_discovery_module

if "pywa" not in sys.modules:
    pywa_module = types.ModuleType("pywa")
    pywa_types_module = types.ModuleType("pywa.types")
    pywa_templates_module = types.ModuleType("pywa.types.templates")

    class DummyBodyText:
        """Minimal pywa template body helper."""

        @staticmethod
        def params(*args):
            return list(args)

    class DummyTemplateLanguage:
        """Minimal template language enum stub."""

        ENGLISH_US = "en_US"
        SPANISH = "es"

    pywa_templates_module.BodyText = DummyBodyText
    pywa_templates_module.TemplateLanguage = DummyTemplateLanguage
    sys.modules["pywa"] = pywa_module
    sys.modules["pywa.types"] = pywa_types_module
    sys.modules["pywa.types.templates"] = pywa_templates_module

if "pywa_async" not in sys.modules:
    pywa_async_module = types.ModuleType("pywa_async")
    pywa_async_types_module = types.ModuleType("pywa_async.types")
    pywa_async_utils_module = types.ModuleType("pywa_async.utils")

    class DummyWhatsApp:
        """Minimal async WhatsApp client stub."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    class DummyCallbackURLScopeValue:
        """Minimal enum-like value with a `.name` attribute."""

        def __init__(self, name: str) -> None:
            self.name = name

    class DummyCallbackURLScope:
        """Minimal callback URL scope enum stub."""

        PHONE = DummyCallbackURLScopeValue("PHONE")

    pywa_async_module.WhatsApp = DummyWhatsApp
    pywa_async_module.types = pywa_async_types_module
    pywa_async_module.utils = pywa_async_utils_module
    pywa_async_utils_module.CallbackURLScope = DummyCallbackURLScope
    sys.modules["pywa_async"] = pywa_async_module
    sys.modules["pywa_async.types"] = pywa_async_types_module
    sys.modules["pywa_async.utils"] = pywa_async_utils_module

if "svix" not in sys.modules:
    svix_module = types.ModuleType("svix")
    svix_webhooks_module = types.ModuleType("svix.webhooks")

    class DummyWebhook:
        """Minimal Svix webhook verifier stub."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    svix_webhooks_module.Webhook = DummyWebhook
    sys.modules["svix"] = svix_module
    sys.modules["svix.webhooks"] = svix_webhooks_module

if "unquotemail" not in sys.modules:
    unquotemail_module = types.ModuleType("unquotemail")

    class DummyUnquote:
        """Minimal unquotemail stub."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    unquotemail_module.Unquote = DummyUnquote
    sys.modules["unquotemail"] = unquotemail_module
