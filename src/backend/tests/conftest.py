"""Pytest config for backend local module imports."""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("AUTH_DISABLE", "true")
os.environ.setdefault("CONTADORES_TEST_CLEAR_PROVIDER_KEYS", "true")

from backend.auth import auth_manager
from backend.endpoints.auth import login_throttle

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
def reset_auth_manager_state() -> None:
    """Keep auth state aligned with env changes between tests."""
    auth_manager.reload_from_env()
    login_throttle.reset()


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


@pytest.fixture(autouse=True)
def reset_workstation_photo_jobs() -> None:
    """Keep in-process professional-photo jobs from leaking across tests."""
    import backend.endpoints.workstation as workstation_endpoints

    workstation_endpoints.reset_professional_photo_jobs()
    yield
    workstation_endpoints.reset_professional_photo_jobs()

if "firecrawl" not in sys.modules:
    firecrawl_module = types.ModuleType("firecrawl")
    firecrawl_v2_module = types.ModuleType("firecrawl.v2")
    firecrawl_v2_types_module = types.ModuleType("firecrawl.v2.types")

    class DummyFirecrawl:
        """Minimal Firecrawl stub so backend app imports work in tests."""

        def __init__(self, *args, **kwargs) -> None:
            return None

    class DummyScrapeOptions:
        """Minimal ScrapeOptions stub for stage imports."""

        def __init__(self, *args, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    firecrawl_module.Firecrawl = DummyFirecrawl
    firecrawl_v2_types_module.ScrapeOptions = DummyScrapeOptions
    sys.modules["firecrawl"] = firecrawl_module
    sys.modules["firecrawl.v2"] = firecrawl_v2_module
    sys.modules["firecrawl.v2.types"] = firecrawl_v2_types_module
