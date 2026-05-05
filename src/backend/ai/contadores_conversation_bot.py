"""Conversation bot program for Contadores and Konecta funnel WhatsApp replies."""

from __future__ import annotations

from typing import Any, Literal

import dspy
from pydantic import BaseModel, Field

from backend.base import Program
from backend.config import CONVERSATION_BOT_MODEL

ConversationBotAction = Literal[
    "send_reply",
    "ask_scheduling_details",
    "handoff_human",
    "handoff_scheduling",
    "close_lead",
    "no_action",
]


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


def _normalize_action(value: str) -> ConversationBotAction:
    """Keep model action output inside the supported action set."""
    normalized = (value or "").strip().lower()
    allowed = {
        "send_reply",
        "ask_scheduling_details",
        "handoff_human",
        "handoff_scheduling",
        "close_lead",
        "no_action",
    }
    if normalized in allowed:
        return normalized  # type: ignore[return-value]
    return "handoff_human"


def _normalize_message_text(value: Any) -> str:
    """Normalize bot copy to the house WhatsApp writing style."""
    return str(value or "").strip().replace("¿", "").replace("¡", "")


class ContadoresConversationBotSignature(dspy.Signature):
    """Choose the next WhatsApp action for a Konecta lead.

    <task>
    You are Facu/Konecta's WhatsApp conversation assistant for professional-service funnels.
    Read the full conversation context and decide the next single action. The goal is to answer
    every message that can be answered from the known playbook, keep the lead in the same stage
    while doubts are being resolved, and escalate to a human only when the answer requires missing
    business data, unverifiable media/audio, opt-out/safety handling, or collected scheduling details.
    </task>

    <allowed_actions>
    - `send_reply`: answer a known question or objection and keep the current stage.
    - `ask_scheduling_details`: ask only for missing meeting details: email, day, time, or timezone.
    - `handoff_human`: do not guess; a human must answer.
    - `handoff_scheduling`: the lead gave email, day, and time. Confirm that the team will coordinate it.
    - `close_lead`: the lead clearly rejects the offer or asks to stop.
    - `no_action`: the latest inbound is an auto-response or low-signal message that should not be answered.
    </allowed_actions>

    <hard_rules>
    - Spanish only.
    - Write WhatsApp-native copy: short paragraphs, direct, human, no corporate polish.
    - Imitate Facu's/operator examples. Do not sound like a polished AI assistant.
    - Do not use inverted opening punctuation. Write `Que dia le queda?`, never `¿Que dia le queda?`.
    - It is okay if the copy is not perfectly formal. Prefer natural chat wording like `aca`, `campanas`,
      `reunion`, `Ok no hay problema`, and simple closing `?`.
    - Avoid robotic phrases such as "espero que se encuentre bien", "con gusto le informo",
      "quedo atento a sus comentarios", or overexplained corporate transitions.
    - Do not include Calendly links. The new flow collects email, day, and time for a human to schedule.
    - The default meeting is 15 minutes.
    - If email, day, and time are all clear, use `handoff_scheduling`.
    - If one or more scheduling fields are missing, use `ask_scheduling_details` and ask only for missing fields.
    - Never invent content from audio, images, stickers, documents, or media without transcript.
    - Never promise legal outcomes, revenue, rankings, closed cases, or guaranteed appointments.
    - It is allowed to mention the 30-day money-back guarantee only as consultations/prospects to WhatsApp,
      never as guaranteed legal or business results.
    - Keep `needs_human` for true unknowns only. Price, country, guarantee, process, domain, existing page,
      not-watched-video, watched-video confirmation, and "lo analizo" are answerable.
    </hard_rules>

    <offer_rules>
    - Lead with the outcome before mechanisms.
    - For abogados: more potential client inquiries/cases that fit the legal areas they want, direct to WhatsApp.
    - For contadores: more prospect/client inquiries for accounting services, direct to WhatsApp.
    - Price: "La inversion es de 300 USD, pago unico" then explain what they receive.
    - Mechanism: professional page plus tailored campaigns.
    - Close warm replies by asking for day/time/email for a short call.
    </offer_rules>

    <few_shot_examples>
    User: "Cuanto cuesta?"
    Action: send_reply
    Reply: "La inversion es de 300 USD, pago unico.\n\nA cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.\n\nEso lo logramos mediante una pagina web profesional y personalizada para su estudio, y 3 campanas publicitarias enfocadas en las areas que quiera priorizar.\n\nPara avanzar, podemos hacer una reunion corta de 15 minutos. Que dia y horario le queda bien?"

    User: "Voy manejando"
    Action: send_reply
    Reply: "Ok no hay problema!\n\nCuando pueda mire el video, son 60 segundos donde explicamos la propuesta a detalle.\n\nIgual se lo resumo por aca: la idea es que usted reciba mas oportunidades de clientes potenciales directo a su WhatsApp.\n\nEso lo logramos mediante una pagina web profesional y 3 campanas publicitarias enfocadas en los servicios que quiera vender.\n\nCualquier duda aca estamos."

    User: "Pagina web tengo"
    Action: send_reply
    Reply: "Perfecto, si ya tiene pagina podemos trabajar sobre eso y ver como mejorarla u optimizarla.\n\nMe pasaria su pagina web para verla?"

    User: "300 de una? Y si no hay cumplimiento?"
    Action: send_reply
    Reply: "Entiendo la duda.\n\nLa inversion es de 300 USD, pago unico. Con eso usted recibe la pagina profesional y las campanas enfocadas en traer consultas a su WhatsApp.\n\nAdemas, si no le llegan consultas nuevas para revisar en 30 dias, le devolvemos el dinero.\n\nSi quiere, lo vemos en una llamada corta y despejamos las ultimas dudas. Que dia y horario le queda bien?"

    User: "Si, voy a consultar con la gente y te aviso"
    Action: send_reply
    Reply: "Perfecto.\n\nPara que lo tengan presente al analizarlo: la idea es atraer consultas de potenciales clientes directo a su WhatsApp, mediante una pagina profesional y campanas enfocadas en las areas que quieran priorizar.\n\nCualquier consulta nos avisan."

    User: "Martes a las 15, mi mail es cliente@example.com"
    Action: handoff_scheduling
    Reply: "Perfecto, con esos datos lo dejamos para coordinar y le confirmamos la invitacion."

    User: "[audio]"
    Action: handoff_human
    Reply: ""

    User: "Hasta aqui llegamos. No soy candidato"
    Action: close_lead
    Reply: "Entendido, muchas gracias."
    </few_shot_examples>

    <output>
    Return all fields. Keep reason as one short Spanish operator-facing sentence.
    For scheduling fields, copy only what the lead actually gave or leave blank.
    </output>
    """

    funnel_id: str = dspy.InputField(desc="Current funnel slug.")
    funnel_label: str = dspy.InputField(desc="Human funnel label.")
    lead_name: str = dspy.InputField(desc="Lead name when known.")
    phone: str = dspy.InputField(desc="Lead phone number.")
    inferred_timezone: str = dspy.InputField(desc="Timezone inferred from the phone, or blank.")
    current_stage: str = dspy.InputField(desc="Current CRM stage.")
    latest_inbound: str = dspy.InputField(desc="Latest inbound message text.")
    conversation: str = dspy.InputField(desc="Recent chronological transcript with sequence steps and media notes.")
    action: ConversationBotAction = dspy.OutputField()
    message_text: str = dspy.OutputField()
    classification_label: str = dspy.OutputField()
    reason: str = dspy.OutputField()
    missing_fields: list[str] = dspy.OutputField()
    scheduling_email: str = dspy.OutputField()
    scheduling_day: str = dspy.OutputField()
    scheduling_time: str = dspy.OutputField()
    timezone: str = dspy.OutputField()


class ContadoresConversationBotProgram(Program):
    """DSPy program that decides and drafts the next WhatsApp reply."""

    def __init__(self, lm: dspy.LM | None = None):
        super().__init__(lm=lm or CONVERSATION_BOT_MODEL)
        self.predict = dspy.Predict(ContadoresConversationBotSignature)

    async def aforward(
        self,
        *,
        funnel_id: str,
        funnel_label: str,
        lead_name: str,
        phone: str,
        inferred_timezone: str,
        current_stage: str,
        latest_inbound: str,
        conversation: str,
    ) -> ContadoresConversationBotResult:
        """Return one structured action for the current lead state."""
        prediction = self.predict(
            funnel_id=funnel_id.strip(),
            funnel_label=funnel_label.strip(),
            lead_name=lead_name.strip(),
            phone=phone.strip(),
            inferred_timezone=inferred_timezone.strip(),
            current_stage=current_stage.strip(),
            latest_inbound=latest_inbound.strip(),
            conversation=conversation.strip(),
        )
        return ContadoresConversationBotResult(
            action=_normalize_action(str(getattr(prediction, "action", ""))),
            message_text=_normalize_message_text(getattr(prediction, "message_text", "")),
            classification_label=str(getattr(prediction, "classification_label", "") or "").strip(),
            reason=str(getattr(prediction, "reason", "") or "").strip(),
            missing_fields=_normalize_list(getattr(prediction, "missing_fields", None)),
            scheduling_email=str(getattr(prediction, "scheduling_email", "") or "").strip(),
            scheduling_day=str(getattr(prediction, "scheduling_day", "") or "").strip(),
            scheduling_time=str(getattr(prediction, "scheduling_time", "") or "").strip(),
            timezone=str(getattr(prediction, "timezone", "") or "").strip(),
        )
