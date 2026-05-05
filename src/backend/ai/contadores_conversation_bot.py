"""Conversation bot programs for Konecta WhatsApp replies."""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from typing import Any, Literal

import dspy
from pydantic import BaseModel, Field

from backend.ai.contadores_conversation_prompt import (
    CONVERSATION_BOT_FEW_SHOTS,
    GLOBAL_CONVERSATION_BOT_PROMPT,
    KONECTA_SOURCE_OF_TRUTH,
    build_conversation_bot_prompt,
)
from backend.base import Program
from backend.codex_utils import CodexSkill, REPO_ROOT, run_codex_with_context
from backend.config import (
    CONVERSATION_BOT_CODEX_EFFORT,
    CONVERSATION_BOT_CODEX_MODEL,
    CONVERSATION_BOT_CODEX_SERVICE_TIER,
    CONVERSATION_BOT_MODEL,
)

ConversationBotAction = Literal[
    "send_reply",
    "ask_scheduling_details",
    "handoff_human",
    "handoff_scheduling",
    "close_lead",
    "no_action",
]

ALLOWED_ACTIONS = {
    "send_reply",
    "ask_scheduling_details",
    "handoff_human",
    "handoff_scheduling",
    "close_lead",
    "no_action",
}

CODEX_RUNTIME_NOTE = (
    "This is a production runtime decision. Do not inspect or modify repository files, "
    "do not run shell commands, and do not use tools. Use only this prompt and the "
    "attached skills as context. Return JSON only."
)

CODEX_CONVERSATION_SKILLS = [
    CodexSkill(
        name="contadores-bot-sequence",
        path=str(REPO_ROOT / ".codex/skills/contadores-bot-sequence/SKILL.md"),
    ),
    CodexSkill(
        name="contadores-lead-reply-playbook",
        path=str(REPO_ROOT / ".codex/skills/contadores-lead-reply-playbook/SKILL.md"),
    ),
]

COMPANY_ORIGIN_REPLY = (
    "Escribo desde Argentina.\n\n"
    "Somos Konecta Labs y trabajamos remoto para toda Latinoamerica."
)

ITALIAN_NUMBER_REPLY = (
    "Si, el numero es italiano porque Alan, mi socio, vivio mucho tiempo en Italia "
    "y conserva ese numero.\n\n"
    "Yo escribo desde Argentina y trabajamos remoto para toda Latinoamerica."
)

WRONG_LOCAL_ORIGIN_PATTERN = re.compile(
    r"\b(somos|soy|estamos|la empresa es|somos una empresa)\s+"
    r"(de|en|ecuatorianos|bolivianos|paraguayos|mexicanos|colombianos|chilenos|"
    r"uruguayos|peruanos|venezolanos|espanoles)\b",
    flags=re.IGNORECASE,
)

WRONG_ORIGIN_TERMS = {
    "bolivia",
    "bolivianos",
    "chile",
    "chilenos",
    "colombia",
    "colombianos",
    "ecuador",
    "ecuatorianos",
    "espana",
    "espanoles",
    "mexico",
    "mexicanos",
    "paraguay",
    "paraguayos",
    "peru",
    "peruanos",
    "uruguay",
    "uruguayos",
    "venezuela",
    "venezolanos",
}


class ContadoresConversationBotResult(BaseModel):
    """Structured next action for one WhatsApp conversation."""

    action: ConversationBotAction
    message_text: str = ""
    classification_label: str = ""
    reason: str = ""
    missing_fields: list[str] = Field(default_factory=list)
    scheduling_email: str = ""
    scheduling_day: str = ""
    scheduling_time: str = ""
    timezone: str = ""
    runtime_provider: str = ""
    runtime_error: str = ""


def _normalize_list(value: Any) -> list[str]:
    """Normalize a model-returned missing-fields value into a short list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    clean_value = str(value).strip()
    if not clean_value:
        return []
    return [
        part.strip()
        for part in clean_value.replace("\n", ",").split(",")
        if part.strip()
    ]


def _normalize_action(value: Any) -> ConversationBotAction:
    """Keep model action output inside the supported action set."""
    normalized = str(value or "").strip().lower()
    if normalized in ALLOWED_ACTIONS:
        return normalized  # type: ignore[return-value]
    return "handoff_human"


def _normalize_message_text(value: Any) -> str:
    """Normalize bot copy to the house WhatsApp writing style."""
    return str(value or "").strip().replace("¿", "").replace("¡", "")


def _normalize_text_for_rules(value: str) -> str:
    """Normalize Spanish copy for simple guardrail checks."""
    ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _asks_about_italian_number(value: str) -> bool:
    """Return True when the lead is asking about the Italian WhatsApp number."""
    normalized = _normalize_text_for_rules(value)
    return (
        ("italia" in normalized or "italiano" in normalized)
        and any(word in normalized for word in ("numero", "whatsapp", "telefono", "celular"))
    )


def _asks_about_company_origin(value: str) -> bool:
    """Return True when the lead asks where Konecta is from or located."""
    normalized = _normalize_text_for_rules(value)
    phrases = (
        "de donde son",
        "de donde eres",
        "de donde escriben",
        "de donde escribes",
        "de que pais",
        "que pais son",
        "donde estan",
        "donde se ubican",
        "son de aqui",
        "no son de aqui",
        "ustedes no son",
        "empresa local",
    )
    return any(phrase in normalized for phrase in phrases)


def _claims_wrong_company_origin(value: str) -> bool:
    """Return True when generated copy claims Konecta is from the lead's country."""
    normalized = _normalize_text_for_rules(value)
    if "somos de argentina" in normalized or "escribo desde argentina" in normalized:
        return False
    if WRONG_LOCAL_ORIGIN_PATTERN.search(normalized) and any(
        term in normalized for term in WRONG_ORIGIN_TERMS
    ):
        return True
    return any(
        f"somos de {term}" in normalized
        or f"estamos en {term}" in normalized
        or f"somos una empresa {term}" in normalized
        or f"somos {term}" in normalized
        for term in WRONG_ORIGIN_TERMS
    )


def _apply_company_source_truth_guard(
    result: ContadoresConversationBotResult,
    *,
    latest_inbound: str,
) -> ContadoresConversationBotResult:
    """Prevent the model from inventing Konecta's origin or copying the lead country."""
    if result.action in {"close_lead", "no_action", "handoff_scheduling"}:
        return result

    if _asks_about_italian_number(latest_inbound):
        return result.model_copy(
            update={
                "action": "send_reply",
                "message_text": ITALIAN_NUMBER_REPLY,
                "classification_label": "answered_italian_number",
                "reason": "Respondio el numero italiano segun source of truth.",
                "missing_fields": [],
                "scheduling_email": "",
                "scheduling_day": "",
                "scheduling_time": "",
                "timezone": "",
            }
        )

    if _asks_about_company_origin(latest_inbound) or _claims_wrong_company_origin(result.message_text):
        return result.model_copy(
            update={
                "action": "send_reply",
                "message_text": COMPANY_ORIGIN_REPLY,
                "classification_label": "answered_company_origin",
                "reason": "Respondio origen de Konecta segun source of truth.",
                "missing_fields": [],
                "scheduling_email": "",
                "scheduling_day": "",
                "scheduling_time": "",
                "timezone": "",
            }
        )

    return result


def _prediction_value(payload: Any, field_name: str, default: Any = "") -> Any:
    """Read one field from a dict, pydantic model, or DSPy Prediction."""
    if isinstance(payload, dict):
        return payload.get(field_name, default)
    return getattr(payload, field_name, default)


def _normalize_result(
    payload: Any,
    *,
    runtime_provider: str,
    runtime_error: str = "",
) -> ContadoresConversationBotResult:
    """Normalize any provider payload into the public result contract."""
    return ContadoresConversationBotResult(
        action=_normalize_action(_prediction_value(payload, "action")),
        message_text=_normalize_message_text(_prediction_value(payload, "message_text")),
        classification_label=str(_prediction_value(payload, "classification_label") or "").strip(),
        reason=str(_prediction_value(payload, "reason") or "").strip(),
        missing_fields=_normalize_list(_prediction_value(payload, "missing_fields", None)),
        scheduling_email=str(_prediction_value(payload, "scheduling_email") or "").strip(),
        scheduling_day=str(_prediction_value(payload, "scheduling_day") or "").strip(),
        scheduling_time=str(_prediction_value(payload, "scheduling_time") or "").strip(),
        timezone=str(_prediction_value(payload, "timezone") or "").strip(),
        runtime_provider=runtime_provider,
        runtime_error=" ".join(str(runtime_error or "").split()).strip(),
    )


def _extract_json_payload(value: str) -> dict[str, Any]:
    """Extract the strict JSON object from a model response."""
    clean_value = (value or "").strip()
    if not clean_value:
        raise ValueError("Codex returned an empty response")

    code_fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_value, flags=re.DOTALL)
    if code_fence_match:
        clean_value = code_fence_match.group(1).strip()
    else:
        start = clean_value.find("{")
        end = clean_value.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Codex response did not include a JSON object")
        clean_value = clean_value[start : end + 1]

    payload = json.loads(clean_value)
    if not isinstance(payload, dict):
        raise ValueError("Codex response JSON must be an object")
    return payload


class ContadoresConversationBotSignature(dspy.Signature):
    """Choose the next WhatsApp action using the supplied rules and examples."""

    global_rules: str = dspy.InputField(desc="Global business rules, style, and JSON contract.")
    few_shot_examples: str = dspy.InputField(desc="Static examples grouped by lead-message category.")
    funnel_info: str = dspy.InputField(desc="Specific funnel objective, audience, offer, and services.")
    funnel_id: str = dspy.InputField(desc="Current funnel slug.")
    funnel_label: str = dspy.InputField(desc="Human funnel label.")
    lead_name: str = dspy.InputField(desc="Lead name when known.")
    phone: str = dspy.InputField(desc="Lead phone number.")
    inferred_timezone: str = dspy.InputField(desc="Timezone inferred from the phone, or blank.")
    current_stage: str = dspy.InputField(desc="Current CRM stage.")
    latest_inbound: str = dspy.InputField(desc="Latest inbound message text.")
    conversation: str = dspy.InputField(desc="Recent chronological transcript with sequence steps and media notes.")
    action: ConversationBotAction = dspy.OutputField(desc="One allowed action.")
    message_text: str = dspy.OutputField(desc="WhatsApp reply text, or empty string.")
    classification_label: str = dspy.OutputField(desc="Short snake_case label.")
    reason: str = dspy.OutputField(desc="One short Spanish operator-facing sentence.")
    missing_fields: list[str] = dspy.OutputField(desc="Missing scheduling fields only.")
    scheduling_email: str = dspy.OutputField(desc="Email provided by the lead, or blank.")
    scheduling_day: str = dspy.OutputField(desc="Meeting day provided by the lead, or blank.")
    scheduling_time: str = dspy.OutputField(desc="Meeting time provided by the lead, or blank.")
    timezone: str = dspy.OutputField(desc="Timezone when explicit or confidently inferred, or blank.")


class DspyConversationBotProgram(Program):
    """DSPy fallback that mirrors the Codex JSON contract."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or CONVERSATION_BOT_MODEL)
        self.predict = dspy.Predict(ContadoresConversationBotSignature)

    async def aforward(
        self,
        *,
        funnel_id: str,
        funnel_label: str,
        funnel_info: str = "",
        lead_name: str,
        phone: str,
        inferred_timezone: str,
        current_stage: str,
        latest_inbound: str,
        conversation: str,
    ) -> ContadoresConversationBotResult:
        """Return one structured fallback action for the current lead state."""
        prediction = await self.predict.acall(
            global_rules=f"{KONECTA_SOURCE_OF_TRUTH}\n\n{GLOBAL_CONVERSATION_BOT_PROMPT}",
            few_shot_examples=CONVERSATION_BOT_FEW_SHOTS,
            funnel_info=funnel_info.strip(),
            funnel_id=funnel_id.strip(),
            funnel_label=funnel_label.strip(),
            lead_name=lead_name.strip(),
            phone=phone.strip(),
            inferred_timezone=inferred_timezone.strip(),
            current_stage=current_stage.strip(),
            latest_inbound=latest_inbound.strip(),
            conversation=conversation.strip(),
        )
        result = _normalize_result(prediction, runtime_provider="dspy")
        return _apply_company_source_truth_guard(result, latest_inbound=latest_inbound)


class CodexConversationBotProgram:
    """Codex SDK primary runtime for the WhatsApp conversation bot."""

    def __init__(
        self,
        *,
        model: str = CONVERSATION_BOT_CODEX_MODEL,
        effort: str = CONVERSATION_BOT_CODEX_EFFORT,
        service_tier: str | None = CONVERSATION_BOT_CODEX_SERVICE_TIER,
    ):
        self.model = model
        self.effort = effort
        self.service_tier = service_tier

    async def aforward(
        self,
        *,
        funnel_id: str,
        funnel_label: str,
        funnel_info: str = "",
        lead_name: str,
        phone: str,
        inferred_timezone: str,
        current_stage: str,
        latest_inbound: str,
        conversation: str,
    ) -> ContadoresConversationBotResult:
        """Run Codex and parse its JSON result."""
        prompt = "\n\n".join(
            [
                CODEX_RUNTIME_NOTE,
                build_conversation_bot_prompt(
                    funnel_id=funnel_id,
                    funnel_label=funnel_label,
                    funnel_info=funnel_info,
                    lead_name=lead_name,
                    phone=phone,
                    inferred_timezone=inferred_timezone,
                    current_stage=current_stage,
                    latest_inbound=latest_inbound,
                    conversation=conversation,
                ),
            ]
        )
        result = await asyncio.to_thread(
            run_codex_with_context,
            prompt,
            skills=CODEX_CONVERSATION_SKILLS,
            model=self.model,
            effort=self.effort,  # type: ignore[arg-type]
            service_tier=self.service_tier,  # type: ignore[arg-type]
            cwd=REPO_ROOT,
        )
        payload = _extract_json_payload(result.final_response)
        normalized = _normalize_result(payload, runtime_provider="codex")
        return _apply_company_source_truth_guard(normalized, latest_inbound=latest_inbound)


class ContadoresConversationBotProgram(Program):
    """Primary Codex bot with a Grok/DSPy fallback."""

    def __init__(
        self,
        lm: dspy.LM | None = None,
        *,
        codex_program: CodexConversationBotProgram | None = None,
        dspy_program: DspyConversationBotProgram | None = None,
    ):
        self.dspy_fallback = dspy_program or DspyConversationBotProgram(lm=lm)
        super().__init__(lm=self.dspy_fallback.lm)
        self.codex_program = codex_program or CodexConversationBotProgram()

    async def aforward(
        self,
        *,
        funnel_id: str,
        funnel_label: str,
        funnel_info: str = "",
        lead_name: str,
        phone: str,
        inferred_timezone: str,
        current_stage: str,
        latest_inbound: str,
        conversation: str,
    ) -> ContadoresConversationBotResult:
        """Return one structured action, using DSPy only if Codex fails."""
        kwargs = {
            "funnel_id": funnel_id,
            "funnel_label": funnel_label,
            "funnel_info": funnel_info,
            "lead_name": lead_name,
            "phone": phone,
            "inferred_timezone": inferred_timezone,
            "current_stage": current_stage,
            "latest_inbound": latest_inbound,
            "conversation": conversation,
        }
        try:
            result = await self.codex_program.aforward(**kwargs)
            return _apply_company_source_truth_guard(result, latest_inbound=latest_inbound)
        except Exception as codex_error:
            codex_error_text = f"{codex_error.__class__.__name__}: {codex_error}"

        try:
            fallback = await self.dspy_fallback.aforward(**kwargs)
            fallback.runtime_provider = "dspy_fallback"
            fallback.runtime_error = f"Codex failed: {codex_error_text}"
            return _apply_company_source_truth_guard(fallback, latest_inbound=latest_inbound)
        except Exception as fallback_error:
            return ContadoresConversationBotResult(
                action="handoff_human",
                classification_label="needs_human",
                reason="Codex y el fallback DSPy fallaron.",
                runtime_provider="failed",
                runtime_error=(
                    f"Codex failed: {codex_error_text}; "
                    f"DSPy failed: {fallback_error.__class__.__name__}: {fallback_error}"
                ),
            )
