"""Pytest config for backend local module imports."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("AUTH_DISABLE", "true")

from backend.auth import auth_manager


@pytest.fixture(autouse=True)
def reset_auth_manager_state() -> None:
    """Keep auth state aligned with env changes between tests."""
    auth_manager.reload_from_env()

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
