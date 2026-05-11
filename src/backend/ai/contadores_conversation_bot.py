"""Conversation bot programs for Konecta WhatsApp replies."""

from __future__ import annotations

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
    CODEX_BACKEND_ENABLED,
    CODEX_PREFER_CHATGPT_LOGIN,
    CONVERSATION_BOT_CODEX_API_KEY_HOME,
    CONVERSATION_BOT_CODEX_CHATGPT_HOME,
    CONVERSATION_BOT_CODEX_EFFORT,
    CONVERSATION_BOT_CODEX_MODEL,
    CONVERSATION_BOT_CODEX_SERVICE_TIER,
    CONVERSATION_BOT_MODEL,
)

ConversationBotAction = Literal[
    "send_reply",
    "offer_solo_page_promo",
    "send_page_example_video",
    "start_workstation_solo_page",
    "ask_scheduling_details",
    "handoff_human",
    "handoff_scheduling",
    "close_lead",
    "no_action",
]

ALLOWED_ACTIONS = {
    "send_reply",
    "offer_solo_page_promo",
    "send_page_example_video",
    "start_workstation_solo_page",
    "ask_scheduling_details",
    "handoff_human",
    "handoff_scheduling",
    "close_lead",
    "no_action",
}

CODEX_RUNTIME_NOTE = (
    "This is a production runtime decision. You may inspect repository files, "
    "attached skills, and use read-only tools or shell commands when that helps "
    "resolve source-of-truth questions. Do not modify repository files, external "
    "systems, or production state. Return JSON only."
)

CODEX_CHATGPT_REAUTH_URL = "https://auth.openai.com/codex/device"
CODEX_CHATGPT_REAUTH_HELP = (
    "Para reautenticar ChatGPT Codex, generar un codigo nuevo con "
    "`env -u OPENAI_API_KEY codex login --device-auth` y abrir "
    f"{CODEX_CHATGPT_REAUTH_URL}."
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
    "Somos Konecta Labs y trabajamos remoto para toda Latinoamerica.\n\n"
    "La propuesta funciona bien para su mercado: la idea es traerle clientes potenciales "
    "directo a su WhatsApp mediante una pagina web moderna y campanas enfocadas."
)

ITALIAN_NUMBER_REPLY = (
    "Si, el numero es italiano porque Alan, mi socio, vivio mucho tiempo en Italia "
    "y conserva ese numero.\n\n"
    "Yo escribo desde Argentina y trabajamos remoto para toda Latinoamerica."
)

CONSULTATION_DEFINITION_REPLY_BY_FUNNEL = {
    "contadores": (
        "Si, exacto.\n\n"
        "No lo contamos como cliente cerrado, porque el cierre depende de como se atiende despues.\n\n"
        "Para nosotros una consulta valida es una oportunidad real: alguien que necesita un servicio contable, "
        "tributario o de empresa, y le escribe directo a su WhatsApp.\n\n"
        "La idea es no traer likes ni visitas vacias, sino conversaciones comerciales que tengan sentido para su estudio."
    ),
    "abogados": (
        "Si, exacto.\n\n"
        "No lo contamos como cliente cerrado, porque el cierre depende de como se atiende despues.\n\n"
        "Para nosotros una consulta valida es una oportunidad real: alguien que tiene un tema legal relacionado "
        "con las areas que usted quiere trabajar, y le escribe directo a su WhatsApp.\n\n"
        "La idea es no traer likes ni visitas vacias, sino conversaciones comerciales que tengan sentido para su estudio."
    ),
}

REJECTION_SURVEY_REPLY = (
    "1) Muy caros los 300 dolares\n"
    "2) No me sirve la pagina web + publicidades\n"
    "3) No es mi momento para invertir\n"
    "4) Otro motivo"
)

ACTIVE_OFFER_REJECTION_REPLY = (
    "Perfecto, no hay problema.\n\n"
    "No te vuelvo a escribir por esta promo."
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
    codex_thread_id: str = ""
    codex_turn_id: str = ""


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
    text = str(value or "").strip().replace("¿", "").replace("¡", "")
    return re.sub(
        r"^(para estar claros|para ser claros|en resumen|respondiendo a (tu|su) pregunta)\s*[:,]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def _normalize_text_for_rules(value: str) -> str:
    """Normalize Spanish copy for simple guardrail checks."""
    ascii_text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


def _conversation_has_active_offer(value: str) -> bool:
    """Return True when the transcript includes a generic promo/offer outbound step."""
    normalized = _normalize_text_for_rules(value)
    return "konecta step=promo_" in normalized or "konecta step=offer_" in normalized


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


def _asks_about_consultation_definition(value: str) -> bool:
    """Return True when the lead asks what counts as a consultation/prospect."""
    normalized = _normalize_text_for_rules(value)
    if not any(term in normalized for term in ("consulta", "consultas", "prospecto", "prospectos")):
        return False
    markers = (
        "como las defines",
        "como defines",
        "que cuenta",
        "que consideran",
        "que es una consulta",
        "que seria una consulta",
        "consulta seria",
        "seria entonces",
        "aunque no haya cierre",
        "aunque no cierre",
        "aunque solo pregunte",
        "si me escriben pero no compran",
        "prospecto calificado",
        "consulta valida",
    )
    return any(marker in normalized for marker in markers)


def _is_service_rejection(value: str) -> bool:
    """Return True when the lead clearly rejects the service or investment."""
    normalized = _normalize_text_for_rules(value)
    if not normalized:
        return False

    video_or_uncertainty_markers = (
        "no vi",
        "no lo vi",
        "no pude ver",
        "no he visto",
        "no vi el video",
        "no pude ver el video",
        "no entiendo",
        "no entendi",
        "no se",
        "no se si",
    )
    if any(marker in normalized for marker in video_or_uncertainty_markers):
        return False

    opt_out_markers = (
        "no me escrib",
        "no escriban",
        "no manden",
        "dejen de escribir",
        "baja",
        "unsubscribe",
        "eliminar mi numero",
    )
    if any(marker in normalized for marker in opt_out_markers):
        return False

    rejection_phrases = (
        "no gracias",
        "gracias no",
        "no me interesa",
        "no estoy interesado",
        "no estoy interesada",
        "no estamos interesados",
        "no nos interesa",
        "no me sirve",
        "no nos sirve",
        "no quiero",
        "no deseo",
        "no necesito",
        "no lo necesito",
        "no voy a avanzar",
        "no vamos a avanzar",
        "no seguimos",
        "no sigo",
        "no contratar",
        "no voy a contratar",
        "no lo quiero",
        "no me convence",
        "no es mi momento",
        "por ahora no",
        "por el momento no",
        "no por ahora",
        "mas adelante",
        "paso",
        "lo dejo pasar",
        "no tengo presupuesto",
        "no tengo el presupuesto",
        "no puedo invertir",
        "no voy a invertir",
    )
    if any(phrase in normalized for phrase in rejection_phrases):
        return True

    budget_rejection_markers = (
        "muy caro",
        "muy caros",
        "demasiado caro",
        "demasiado caros",
        "esta caro",
        "estan caros",
        "se me hace caro",
        "presupuesto alto",
    )
    return any(marker in normalized for marker in budget_rejection_markers)


def _consultation_definition_reply(funnel_id: str) -> str:
    """Return the canonical persuasive definition for consultation objections."""
    return CONSULTATION_DEFINITION_REPLY_BY_FUNNEL.get(
        (funnel_id or "").strip().lower(),
        (
            "Si, exacto.\n\n"
            "No lo contamos como cliente cerrado, porque el cierre depende de como se atiende despues.\n\n"
            "Para nosotros una consulta valida es una oportunidad real: alguien que tiene una necesidad concreta "
            "y pregunta por un servicio que usted ofrece.\n\n"
            "La idea es no traer likes ni visitas vacias, sino conversaciones comerciales que tengan sentido."
        ),
    )


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
    funnel_id: str,
    conversation: str = "",
) -> ContadoresConversationBotResult:
    """Prevent the model from inventing facts or using robotic high-risk copy."""
    if _is_service_rejection(latest_inbound):
        if _conversation_has_active_offer(conversation):
            return result.model_copy(
                update={
                    "action": "close_lead",
                    "message_text": ACTIVE_OFFER_REJECTION_REPLY,
                    "classification_label": "active_offer_rejected",
                    "reason": "El lead rechazo una promo/oferta activa; se cierra sin encuesta de la oferta default.",
                    "missing_fields": [],
                    "scheduling_email": "",
                    "scheduling_day": "",
                    "scheduling_time": "",
                    "timezone": "",
                }
            )
        return result.model_copy(
            update={
                "action": "close_lead",
                "message_text": REJECTION_SURVEY_REPLY,
                "classification_label": "service_rejection_survey",
                "reason": "El lead rechazo el servicio; se envia encuesta de motivo y se cierra.",
                "missing_fields": [],
                "scheduling_email": "",
                "scheduling_day": "",
                "scheduling_time": "",
                "timezone": "",
            }
        )

    if result.action in {"close_lead", "no_action", "handoff_scheduling"}:
        return result

    if _asks_about_consultation_definition(latest_inbound):
        return result.model_copy(
            update={
                "action": "send_reply",
                "message_text": _consultation_definition_reply(funnel_id),
                "classification_label": "answered_consultation_definition",
                "reason": "Definio consulta/prospecto segun source of truth sin apurar agenda.",
                "missing_fields": [],
                "scheduling_email": "",
                "scheduling_day": "",
                "scheduling_time": "",
                "timezone": "",
            }
        )

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
        codex_thread_id: str | None = None,
    ) -> ContadoresConversationBotResult:
        """Return one structured fallback action for the current lead state."""
        del codex_thread_id
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
        return _apply_company_source_truth_guard(
            result,
            latest_inbound=latest_inbound,
            funnel_id=funnel_id,
            conversation=conversation,
        )


class CodexConversationBotProgram:
    """Codex SDK primary runtime for the WhatsApp conversation bot."""

    def __init__(
        self,
        *,
        model: str = CONVERSATION_BOT_CODEX_MODEL,
        effort: str = CONVERSATION_BOT_CODEX_EFFORT,
        service_tier: str | None = CONVERSATION_BOT_CODEX_SERVICE_TIER,
        prefer_chatgpt_login: bool | None = None,
        codex_home: str | None = None,
        runtime_provider: str | None = None,
    ):
        prefer = CODEX_PREFER_CHATGPT_LOGIN if prefer_chatgpt_login is None else prefer_chatgpt_login
        if codex_home is None:
            resolved_home = CONVERSATION_BOT_CODEX_CHATGPT_HOME if prefer else CONVERSATION_BOT_CODEX_API_KEY_HOME
        else:
            resolved_home = codex_home
        if runtime_provider is None:
            resolved_provider = "codex_chatgpt" if prefer else "codex_api_key"
        else:
            resolved_provider = runtime_provider
        self.model = model
        self.effort = effort
        self.service_tier = service_tier
        self.prefer_chatgpt_login = prefer
        self.codex_home = (resolved_home or "").strip() or None
        self.runtime_provider = resolved_provider

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
        codex_thread_id: str | None = None,
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
        result = await run_codex_with_context(
            prompt,
            thread_id=codex_thread_id,
            skills=CODEX_CONVERSATION_SKILLS,
            model=self.model,
            effort=self.effort,  # type: ignore[arg-type]
            service_tier=self.service_tier,  # type: ignore[arg-type]
            cwd=REPO_ROOT,
            codex_home=self.codex_home,
            prefer_chatgpt_login=self.prefer_chatgpt_login,
        )
        payload = _extract_json_payload(result.final_response)
        normalized = _normalize_result(payload, runtime_provider=self.runtime_provider)
        normalized.codex_thread_id = getattr(result, "thread_id", "") or ""
        normalized.codex_turn_id = getattr(result, "turn_id", "") or ""
        return _apply_company_source_truth_guard(
            normalized,
            latest_inbound=latest_inbound,
            funnel_id=funnel_id,
            conversation=conversation,
        )


class ContadoresConversationBotProgram(Program):
    """Codex SDK (API key by default; optional ChatGPT session), then Grok/DSPy fallback."""

    def __init__(
        self,
        lm: dspy.LM | None = None,
        *,
        codex_program: CodexConversationBotProgram | None = None,
        codex_api_key_program: CodexConversationBotProgram | None = None,
        dspy_program: DspyConversationBotProgram | None = None,
    ):
        self.dspy_fallback = dspy_program or DspyConversationBotProgram(lm=lm)
        super().__init__(lm=self.dspy_fallback.lm)
        if codex_program is not None:
            self.codex_program = codex_program
        elif CODEX_PREFER_CHATGPT_LOGIN:
            self.codex_program = CodexConversationBotProgram(
                prefer_chatgpt_login=True,
                codex_home=CONVERSATION_BOT_CODEX_CHATGPT_HOME,
                runtime_provider="codex_chatgpt",
            )
        else:
            self.codex_program = CodexConversationBotProgram(
                prefer_chatgpt_login=False,
                codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME,
                runtime_provider="codex_api_key",
            )
        if codex_api_key_program is not None:
            self.codex_api_key_program = codex_api_key_program
        elif codex_program is None and CODEX_PREFER_CHATGPT_LOGIN:
            self.codex_api_key_program = CodexConversationBotProgram(
                prefer_chatgpt_login=False,
                codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME,
                runtime_provider="codex_api_key",
            )
        else:
            self.codex_api_key_program = None

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
        codex_thread_id: str | None = None,
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
            "codex_thread_id": codex_thread_id,
        }
        if not CODEX_BACKEND_ENABLED:
            primary_runtime_error = (
                "Codex SDK desactivado (CODEX_BACKEND_ENABLED no es true); no se llama Codex ni por API key."
            )
            api_key_error_text = ""
            try:
                fallback = await self.dspy_fallback.aforward(**kwargs)
                fallback.runtime_provider = "dspy_fallback"
                fallback.runtime_error = primary_runtime_error
                return _apply_company_source_truth_guard(
                    fallback,
                    latest_inbound=latest_inbound,
                    funnel_id=funnel_id,
                    conversation=conversation,
                )
            except Exception as fallback_error:
                return ContadoresConversationBotResult(
                    action="handoff_human",
                    classification_label="needs_human",
                    reason="Codex desactivado y el fallback DSPy fallo.",
                    runtime_provider="failed",
                    runtime_error=(
                        f"{primary_runtime_error}; "
                        f"DSPy failed: {fallback_error.__class__.__name__}: {fallback_error}"
                    ),
                )

        try:
            result = await self.codex_program.aforward(**kwargs)
            return _apply_company_source_truth_guard(
                result,
                latest_inbound=latest_inbound,
                funnel_id=funnel_id,
                conversation=conversation,
            )
        except Exception as chatgpt_error:
            chatgpt_error_text = f"{chatgpt_error.__class__.__name__}: {chatgpt_error}"

        primary_runtime_error = (
            f"Codex ChatGPT failed: {chatgpt_error_text}. {CODEX_CHATGPT_REAUTH_HELP}"
            if CODEX_PREFER_CHATGPT_LOGIN
            else f"Codex failed: {chatgpt_error_text}"
        )

        api_key_error_text = ""
        if self.codex_api_key_program is not None:
            try:
                api_key_result = await self.codex_api_key_program.aforward(**kwargs)
                api_key_result.runtime_provider = "codex_api_key_fallback"
                api_key_result.runtime_error = primary_runtime_error
                return _apply_company_source_truth_guard(
                    api_key_result,
                    latest_inbound=latest_inbound,
                    funnel_id=funnel_id,
                    conversation=conversation,
                )
            except Exception as api_key_error:
                api_key_error_text = f"{api_key_error.__class__.__name__}: {api_key_error}"

        try:
            fallback = await self.dspy_fallback.aforward(**kwargs)
            fallback.runtime_provider = "dspy_fallback"
            fallback.runtime_error = (
                f"{primary_runtime_error}; Codex API key failed: {api_key_error_text}"
                if api_key_error_text
                else primary_runtime_error
            )
            return _apply_company_source_truth_guard(
                fallback,
                latest_inbound=latest_inbound,
                funnel_id=funnel_id,
                conversation=conversation,
            )
        except Exception as fallback_error:
            return ContadoresConversationBotResult(
                action="handoff_human",
                classification_label="needs_human",
                reason="Codex y el fallback DSPy fallaron.",
                runtime_provider="failed",
                runtime_error=(
                    f"{primary_runtime_error}; "
                    f"Codex API key failed: {api_key_error_text or 'not configured'}; "
                    f"DSPy failed: {fallback_error.__class__.__name__}: {fallback_error}"
                ),
            )
