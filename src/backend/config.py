"""Configuration management for Contadores."""

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

import dspy
from dotenv import load_dotenv
from dspy.adapters.baml_adapter import BAMLAdapter

env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path, override=True)

if os.getenv("CONTADORES_TEST_CLEAR_PROVIDER_KEYS", "").strip().lower() in {"1", "true", "yes", "on"}:
    for name in (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "PERPLEXITY_API_KEY",
    ):
        os.environ.pop(name, None)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

AUDIO_TRANSCRIPTION_MODEL = os.getenv("OPENAI_AUDIO_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
AUDIO_TRANSCRIPTION_PROMPT = os.getenv(
    "OPENAI_AUDIO_TRANSCRIPTION_PROMPT",
    (
        "Transcribe audio de WhatsApp de leads de Konecta. "
        "Devuelve solo el texto dicho, manteniendo idioma y palabras comerciales como "
        "pagina, campanas, reunion, WhatsApp, contadores y abogados."
    ),
)
CONVERSATION_BOT_CODEX_MODEL = os.getenv("CONVERSATION_BOT_CODEX_MODEL", "gpt-5.5")
CONVERSATION_BOT_CODEX_EFFORT = os.getenv("CONVERSATION_BOT_CODEX_EFFORT", "medium")
CONVERSATION_BOT_CODEX_SERVICE_TIER = (os.getenv("CONVERSATION_BOT_CODEX_SERVICE_TIER", "") or "").strip() or None


def _env_truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


CODEX_BACKEND_ENABLED = _env_truthy("CODEX_BACKEND_ENABLED")
CODEX_PREFER_CHATGPT_LOGIN = _env_truthy("CODEX_PREFER_CHATGPT_LOGIN")
_CODEX_HOME = (os.getenv("CODEX_HOME", "") or "").strip()
CONVERSATION_BOT_CODEX_CHATGPT_HOME = (
    os.getenv("CONVERSATION_BOT_CODEX_CHATGPT_HOME", _CODEX_HOME) or ""
).strip()
CONVERSATION_BOT_CODEX_API_KEY_HOME = (
    os.getenv(
        "CONVERSATION_BOT_CODEX_API_KEY_HOME",
        f"{_CODEX_HOME}-api-key" if _CODEX_HOME else "",
    )
    or ""
).strip()
CODEX_AGENT_TOOLS_ENABLED = os.getenv("CODEX_AGENT_TOOLS_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CODEX_AGENT_TOOLS_WORKSTATION_ENABLED = os.getenv(
    "CODEX_AGENT_TOOLS_WORKSTATION_ENABLED",
    "false",
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CODEX_AGENT_TOOLS_CONVERSATION_ENABLED = os.getenv(
    "CODEX_AGENT_TOOLS_CONVERSATION_ENABLED",
    "false",
).lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WORKSTATION_PING_TEMPLATE_1_NAME = os.getenv(
    "WORKSTATION_PING_TEMPLATE_1_NAME",
    "konecta_workstation_ping_1_es_v1",
).strip()
WORKSTATION_PING_TEMPLATE_2_NAME = os.getenv(
    "WORKSTATION_PING_TEMPLATE_2_NAME",
    "konecta_workstation_ping_2_es_v1",
).strip()
WORKSTATION_HANDOFF_TEMPLATE_NAME = os.getenv(
    "WORKSTATION_HANDOFF_TEMPLATE_NAME",
    "konecta_workstation_handoff_es_v1",
).strip()
WORKSTATION_TEMPLATE_LANGUAGE = os.getenv("WORKSTATION_TEMPLATE_LANGUAGE", "es").strip() or "es"
WORKSTATION_HUMAN_HANDOFF_TEXT = os.getenv(
    "WORKSTATION_HUMAN_HANDOFF_TEXT",
    "Te paso con Facundo para seguir la conversacion por WhatsApp.",
).strip()
WORKSTATION_PING_1_TEXT = os.getenv(
    "WORKSTATION_PING_1_TEXT",
    "Hola, queria avisarle que ya tengo una actualizacion de su pagina. Esta por ahi?",
).strip()
WORKSTATION_PING_2_TEXT = os.getenv(
    "WORKSTATION_PING_2_TEXT",
    "Le escribo para retomar lo de su pagina. Quiere que sigamos con el boceto?",
).strip()
WA_CALLBACK_URL = os.getenv("WA_CALLBACK_URL", "").strip()
WORKSTATION_PUBLIC_PAGE_BASE_URL = os.getenv("WORKSTATION_PUBLIC_PAGE_BASE_URL", "").strip().rstrip("/")
WORKSTATION_CODEX_HEARTBEAT_ENABLED = os.getenv(
    "WORKSTATION_CODEX_HEARTBEAT_ENABLED",
    "true",
).lower() in {"1", "true", "yes", "on"}
try:
    WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS = max(
        1,
        int(os.getenv("WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS", "12")),
    )
except ValueError:
    WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS = 12


# Instantly configuration
INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY", "")
INSTANTLY_MCP_URL = os.getenv("INSTANTLY_MCP_URL", "https://mcp.instantly.ai/mcp")


@lru_cache(maxsize=None)
def get_gpt_5_mini(
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low",
    verbosity: Literal["low", "medium", "high"] = "low",
):
    """get a gpt-5 mini model"""
    full_model = f"openai/gpt-5-mini"

    return dspy.LM(
        full_model,
        temperature=1.0,
        max_tokens=40_000,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        allowed_openai_params=["reasoning_effort", "verbosity"],
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_gpt_5_4_mini(
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low",
    verbosity: Literal["low", "medium", "high"] = "low",
):
    """Get a GPT-5.4 mini model."""
    full_model = os.getenv("OPENAI_GPT_5_4_MINI_MODEL", "openai/gpt-5.4-mini")

    return dspy.LM(
        full_model,
        temperature=1.0,
        max_tokens=40_000,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        allowed_openai_params=["reasoning_effort", "verbosity"],
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_grok_4_3():
    """Get Grok 4.3 through OpenRouter."""
    full_model = os.getenv("OPENROUTER_GROK_4_3_MODEL", "openrouter/x-ai/grok-4.3")

    return dspy.LM(
        full_model,
        temperature=0.7,
        max_tokens=16_384,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_gpt_5_2(
    reasoning_effort: Literal["minimal", "low", "medium", "high"] = "low",
    verbosity: Literal["low", "medium", "high"] = "low",
):
    """get a gpt-5 model"""
    full_model = f"openai/gpt-5.2"

    return dspy.LM(
        full_model,
        temperature=1.0,
        max_tokens=40_000,
        reasoning_effort=reasoning_effort,
        verbosity=verbosity,
        allowed_openai_params=["reasoning_effort", "verbosity"],
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )

REASONING_EFFORT: Literal["minimal", "low", "medium", "high"] = "low"
VERBOSITY: Literal["low", "medium", "high"] = "low"
CACHE: bool = True


@lru_cache(maxsize=None)
def get_gemini_pro_3_1():
    return dspy.LM(
        "openrouter/google/gemini-3.1-pro-preview",
        temperature=1.0,
        max_tokens=16_384,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_kimi_2_5():
    return dspy.LM(
        "openrouter/moonshotai/kimi-k2.5",
        temperature=1.0,
        max_tokens=16_384,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_grok_4_1_fast_non_reasoning():
    return dspy.LM(
        "openrouter/x-ai/grok-4.1-fast",
        temperature=1.0,
        max_tokens=16_384,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_grok_4_1_fast_reasoning():
    return dspy.LM(
        "openrouter/x-ai/grok-4.1-fast",
        temperature=1.0,
        max_tokens=16_384,
        reasoning={"effort": "high"},
        include_reasoning=True,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_gemini_3_1_flash_lite_preview():
    return dspy.LM(
        "openrouter/google/gemini-3.1-flash-lite-preview",
        temperature=1.0,
        max_tokens=32_768,
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
    )


@lru_cache(maxsize=None)
def get_fast_model():
    return get_grok_4_1_fast_reasoning()


@lru_cache(maxsize=None)
def get_smart_model():
    return get_gpt_5_2(reasoning_effort="high", verbosity="high")


@lru_cache(maxsize=None)
def get_conversation_bot_model():
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        return get_grok_4_3()
    return get_gpt_5_4_mini(reasoning_effort="medium", verbosity="low")


_DSPY_CONFIGURED = False


def configure_dspy_if_needed(lm=None) -> None:
    """Configure DSPy lazily when a DSPy program is constructed."""
    global _DSPY_CONFIGURED
    if _DSPY_CONFIGURED:
        return
    dspy.configure(lm=lm or get_fast_model(), adapter=BAMLAdapter())
    dspy.configure_cache(enable_disk_cache=CACHE, enable_memory_cache=CACHE)
    _DSPY_CONFIGURED = True


def reset_ai_model_cache() -> None:
    """Reset lazy AI model state for tests."""
    global _DSPY_CONFIGURED
    for accessor in (
        get_gpt_5_mini,
        get_gpt_5_4_mini,
        get_grok_4_3,
        get_gpt_5_2,
        get_gemini_pro_3_1,
        get_kimi_2_5,
        get_grok_4_1_fast_non_reasoning,
        get_grok_4_1_fast_reasoning,
        get_gemini_3_1_flash_lite_preview,
        get_fast_model,
        get_smart_model,
        get_conversation_bot_model,
    ):
        accessor.cache_clear()
    _DSPY_CONFIGURED = False


## PARALLEL EXECUTION

# async def run(input):
#     result = await program.acall(input=input)
#     return result

# tasks = [run(input) for input in inputs]
# results = await asyncio.gather(*tasks)

if __name__ == "__main__":
    pass
