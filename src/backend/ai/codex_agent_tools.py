"""Approved product tools callable by autonomous Codex runs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from backend.ai.codex_agent_runtime import CodexAgentToolSpec, run_context_dir, write_jsonl
from backend.database import (
    AgentToolCall,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ScheduledAgentTask,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
)


DEFAULT_AGENT_SEQUENCE_STEP = "codex_agent"


class AgentToolError(RuntimeError):
    """Raised when a tool request is valid JSON but not allowed."""


class LeadToolArgs(BaseModel):
    """Base args for lead tools."""

    lead_id: str = Field(min_length=1)


class ClientToolArgs(BaseModel):
    """Base args for Workstation client tools."""

    client_id: str = Field(min_length=1)


class SendWhatsAppTextArgs(LeadToolArgs):
    """Arguments for sending a text message."""

    text: str = Field(min_length=1, max_length=4000)
    sequence_step: str = DEFAULT_AGENT_SEQUENCE_STEP
    dispatch_after_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    idempotency_key: str | None = None


class SendWhatsAppMediaArgs(SendWhatsAppTextArgs):
    """Arguments for sending a media message."""

    media_type: str = Field(min_length=1)
    media_path: str = Field(min_length=1)
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None


class ScheduleFollowupArgs(BaseModel):
    """Arguments for a future agent wake-up."""

    target_type: str = Field(pattern="^(lead|workstation_client)$")
    target_id: str = Field(min_length=1)
    run_after_minutes: int = Field(ge=1, le=60 * 24 * 30)
    reason: str = Field(min_length=1, max_length=1000)
    instruction: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = None


class UpdateLeadStateArgs(LeadToolArgs):
    """Arguments for updating a lead state."""

    stage: str | None = None
    automation_paused: bool | None = None
    reason: str = Field(default="", max_length=4000)
    classification_label: str = Field(default="codex_agent")


class HandoffHumanArgs(LeadToolArgs):
    """Arguments for handing a lead to a person."""

    reason: str = Field(min_length=1, max_length=4000)
    optional_message: str = Field(default="", max_length=4000)


class CreateOrGetSoloPageClientArgs(LeadToolArgs):
    """Arguments for creating a Workstation solo-page client."""

    offer_price_usd: int | None = Field(default=None, ge=1)


class GenerateOrReviseSoloPageArgs(ClientToolArgs):
    """Arguments for page generation or revision."""

    instruction: str = Field(min_length=1, max_length=8000)
    revision: bool = True
    source_message_ids: list[int] = Field(default_factory=list)


class QueueWorkstationDeliverablesArgs(ClientToolArgs):
    """Arguments for queueing Workstation deliverables."""

    version: str = Field(min_length=1)
    sequence_step: str = "workstation_revision_video"


class MarkPreviewApprovedArgs(ClientToolArgs):
    """Arguments for marking a Workstation preview approved."""

    reason: str = Field(default="El cliente aprobo el boceto.", max_length=4000)


class WriteProgressArgs(ClientToolArgs):
    """Arguments for adding Workstation progress."""

    message: str = Field(min_length=1, max_length=2000)


def tool_specs() -> list[CodexAgentToolSpec]:
    """Return the toolbelt exposed to Codex."""
    specs: list[tuple[str, str, type[BaseModel]]] = [
        ("get_lead_context", "Read lead state and recent WhatsApp messages.", LeadToolArgs),
        ("send_whatsapp_text", "Queue one WhatsApp text message, optionally delayed.", SendWhatsAppTextArgs),
        ("send_whatsapp_media", "Queue one WhatsApp media message, optionally delayed.", SendWhatsAppMediaArgs),
        ("schedule_followup", "Create a DB-backed future agent wake-up.", ScheduleFollowupArgs),
        ("update_lead_state", "Update stage or automation pause state for a lead.", UpdateLeadStateArgs),
        ("handoff_human", "Pause automation and hand a lead to a human.", HandoffHumanArgs),
        (
            "create_or_get_solo_page_client",
            "Create or fetch the Workstation solo-page client for a lead.",
            CreateOrGetSoloPageClientArgs,
        ),
        ("get_workstation_context", "Read Workstation client state, folder, versions, and messages.", ClientToolArgs),
        ("write_progress", "Append one visible Workstation progress line.", WriteProgressArgs),
        ("generate_or_revise_solo_page", "Create or revise the client's static solo-page.", GenerateOrReviseSoloPageArgs),
        ("queue_workstation_deliverables", "Queue preview/media deliverables from a page version.", QueueWorkstationDeliverablesArgs),
        ("mark_preview_approved", "Mark the current Workstation preview approved and hand off.", MarkPreviewApprovedArgs),
    ]
    return [
        CodexAgentToolSpec(
            name=name,
            description=description,
            schema=model.model_json_schema(),
        )
        for name, description, model in specs
    ]


def _lead_or_error(lead_id: str) -> ContadoresLead:
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise AgentToolError(f"Lead not found: {lead_id}")
    return lead


def _client_or_error(client_id: str) -> WorkstationClient:
    client = WorkstationClient.get_by_id(client_id)
    if client is None:
        raise AgentToolError(f"Workstation client not found: {client_id}")
    return client


def _dispatch_after(minutes: int) -> datetime | None:
    if minutes <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _message_payload(row: ContadoresMessage) -> dict[str, Any]:
    return {
        "message_id": row.id,
        "lead_id": row.lead_id,
        "text": row.text,
        "sequence_step": row.sequence_step,
        "media_type": row.media_type,
        "media_path": row.media_path,
        "dispatch_after": row.dispatch_after.isoformat(),
    }


def get_lead_context(arguments: dict[str, Any]) -> dict[str, Any]:
    args = LeadToolArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    messages = ContadoresMessage.list_by_lead(lead.id)[-30:]
    client = WorkstationClient.get_by_lead_id(lead.id)
    return {
        "lead": {
            "id": lead.id,
            "funnel_id": lead.funnel_id,
            "stage": lead.stage.value,
            "full_name": lead.full_name,
            "phone": lead.phone,
            "email": lead.email,
            "automation_paused": lead.automation_paused,
            "automation_paused_reason": lead.automation_paused_reason,
            "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
            "last_outbound_at": lead.last_outbound_at.isoformat() if lead.last_outbound_at else None,
        },
        "workstation_client_id": client.id if client else None,
        "messages": [
            {
                "id": message.id,
                "from_me": message.from_me,
                "text": message.text,
                "media_type": message.media_type,
                "media_path": message.media_path,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


def send_whatsapp_text(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints.contadores import enqueue_lead_outbound

    args = SendWhatsAppTextArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    row = enqueue_lead_outbound(
        lead=lead,
        text=args.text,
        sequence_step=args.sequence_step,
        dispatch_after=_dispatch_after(args.dispatch_after_minutes),
    )
    return {"queued": True, "message": _message_payload(row)}


def send_whatsapp_media(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints.contadores import enqueue_lead_outbound

    args = SendWhatsAppMediaArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    row = enqueue_lead_outbound(
        lead=lead,
        text=args.text,
        sequence_step=args.sequence_step,
        dispatch_after=_dispatch_after(args.dispatch_after_minutes),
        media_type=args.media_type,
        media_path=args.media_path,
        media_caption=args.media_caption,
        media_mime_type=args.media_mime_type,
        media_filename=args.media_filename,
    )
    return {"queued": True, "message": _message_payload(row)}


def schedule_followup(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = ScheduleFollowupArgs.model_validate(arguments)
    due_at = datetime.now(timezone.utc) + timedelta(minutes=args.run_after_minutes)
    key = args.idempotency_key or f"{run_id}:{args.target_type}:{args.target_id}:{args.run_after_minutes}"
    task = ScheduledAgentTask.create(
        target_type=args.target_type,
        target_id=args.target_id,
        due_at=due_at,
        reason=args.reason,
        instruction=args.instruction,
        run_id=run_id,
        idempotency_key=key,
    )
    return {
        "scheduled": True,
        "task_id": task.id,
        "target_type": task.target_type,
        "target_id": task.target_id,
        "due_at": task.due_at.isoformat(),
    }


def update_lead_state(arguments: dict[str, Any]) -> dict[str, Any]:
    args = UpdateLeadStateArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    stage = ContadoresLeadStage(args.stage) if args.stage else None
    updated = ContadoresLead.update_flow_state(
        lead.id,
        stage=stage,
        automation_paused=args.automation_paused,
        automation_paused_reason=args.reason if args.automation_paused else None,
        classification_completed_at=datetime.now(timezone.utc),
        last_classification_label=args.classification_label,
        last_classification_reason=args.reason or "Actualizado por Codex agent tool.",
    )
    return {"updated": updated is not None, "lead_id": lead.id, "stage": updated.stage.value if updated else lead.stage.value}


def handoff_human(arguments: dict[str, Any]) -> dict[str, Any]:
    args = HandoffHumanArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    queued: dict[str, Any] | None = None
    if args.optional_message.strip():
        queued = send_whatsapp_text(
            {
                "lead_id": lead.id,
                "text": args.optional_message,
                "sequence_step": "codex_agent_handoff",
            }
        )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="codex_agent_handoff",
        classification_completed_at=datetime.now(timezone.utc),
        last_classification_label="codex_agent_handoff",
        last_classification_reason=args.reason,
        clear_needs_human_notified_at=True,
    )
    client = WorkstationClient.get_by_lead_id(lead.id)
    if client is not None:
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
            last_automation_handled_at=datetime.now(timezone.utc),
        )
    return {"handoff": True, "lead_id": lead.id, "queued_message": queued}


def create_or_get_solo_page_client(arguments: dict[str, Any]) -> dict[str, Any]:
    args = CreateOrGetSoloPageClientArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    client = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
        offer_price_usd=args.offer_price_usd,
    )
    return {
        "client_id": client.id,
        "lead_id": client.lead_id,
        "folder_name": client.folder_name,
        "automation_status": client.automation_status.value,
    }


def get_workstation_context(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = ClientToolArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    workstation_endpoints.write_client_files(client)
    folder = workstation_endpoints.client_folder(client)
    latest_version = workstation_endpoints.latest_landing_page_version_dir(client)
    messages = ContadoresMessage.list_by_lead(lead.id)[-30:]
    return {
        "client": {
            "id": client.id,
            "lead_id": client.lead_id,
            "display_name": client.display_name,
            "automation_status": client.automation_status.value,
            "folder": str(folder),
            "latest_page_version": str(latest_version) if latest_version else None,
            "last_preview_sent_at": client.last_preview_sent_at.isoformat() if client.last_preview_sent_at else None,
            "approved_at": client.approved_at.isoformat() if client.approved_at else None,
        },
        "lead": {"id": lead.id, "full_name": lead.full_name, "phone": lead.phone},
        "messages": [
            {
                "id": message.id,
                "from_me": message.from_me,
                "text": message.text,
                "media_type": message.media_type,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


def write_progress(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = WriteProgressArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    workstation_endpoints.append_workstation_progress(client, args.message)
    return {"written": True, "client_id": client.id}


def generate_or_revise_solo_page(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = GenerateOrReviseSoloPageArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    messages = ContadoresMessage.list_by_lead(lead.id)
    if args.source_message_ids:
        selected = {int(message_id) for message_id in args.source_message_ids}
        replies = [message for message in messages if message.id in selected]
    else:
        replies = [message for message in messages if not message.from_me][-5:]
    version_dir = workstation_endpoints.generate_solo_page_version_sync(
        client=client,
        lead=lead,
        replies=replies,
        revision=args.revision,
        operator_prompt=args.instruction,
    )
    return {
        "generated": True,
        "client_id": client.id,
        "version": version_dir.name,
        "version_dir": str(version_dir),
        "preview_path": str(version_dir / "preview.mp4"),
    }


def queue_workstation_deliverables(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = QueueWorkstationDeliverablesArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    version_dir = workstation_endpoints.landing_page_root(client) / Path(args.version).name
    if not version_dir.is_dir():
        raise AgentToolError(f"Page version not found: {args.version}")
    rows = workstation_endpoints.queue_workstation_preview(
        client=client,
        lead=lead,
        version_dir=version_dir,
        sequence_step=args.sequence_step,
    )
    if rows:
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=datetime.now(timezone.utc),
            last_preview_sent_at=max(row.created_at for row in rows),
        )
    return {"queued": len(rows), "messages": [_message_payload(row) for row in rows]}


def mark_preview_approved(arguments: dict[str, Any]) -> dict[str, Any]:
    args = MarkPreviewApprovedArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    now = datetime.now(timezone.utc)
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        approved_at=now,
        last_automation_handled_at=now,
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="workstation_solo_page_approved",
        classification_completed_at=now,
        last_classification_label="workstation_solo_page_approved",
        last_classification_reason=args.reason,
        clear_needs_human_notified_at=True,
    )
    return {"approved": True, "client_id": client.id, "lead_id": lead.id}


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_lead_context": get_lead_context,
    "send_whatsapp_text": send_whatsapp_text,
    "send_whatsapp_media": send_whatsapp_media,
    "schedule_followup": schedule_followup,
    "update_lead_state": update_lead_state,
    "handoff_human": handoff_human,
    "create_or_get_solo_page_client": create_or_get_solo_page_client,
    "get_workstation_context": get_workstation_context,
    "write_progress": write_progress,
    "generate_or_revise_solo_page": generate_or_revise_solo_page,
    "queue_workstation_deliverables": queue_workstation_deliverables,
    "mark_preview_approved": mark_preview_approved,
}


def call_tool(*, run_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate, execute, and audit one product tool call."""
    clean_tool_name = (tool_name or "").strip()
    handler = TOOL_HANDLERS.get(clean_tool_name)
    target_type = str(arguments.get("target_type") or ("workstation_client" if arguments.get("client_id") else "lead"))
    target_id = str(arguments.get("target_id") or arguments.get("client_id") or arguments.get("lead_id") or "")
    idempotency_key = str(arguments.get("idempotency_key") or "").strip() or None
    try:
        if handler is None:
            raise AgentToolError(f"Unknown tool: {clean_tool_name}")
        if clean_tool_name == "schedule_followup":
            result = handler(arguments, run_id=run_id)
        else:
            result = handler(arguments)
        payload = {"ok": True, "tool": clean_tool_name, "result": result}
        AgentToolCall.add(
            run_id=run_id,
            tool_name=clean_tool_name,
            arguments=arguments,
            result=result,
            status="succeeded",
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
        )
    except (ValidationError, AgentToolError, Exception) as error:
        payload = {
            "ok": False,
            "tool": clean_tool_name,
            "error_type": error.__class__.__name__,
            "error": str(error),
        }
        AgentToolCall.add(
            run_id=run_id,
            tool_name=clean_tool_name,
            arguments=arguments,
            result=payload,
            status="failed",
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
            error=f"{error.__class__.__name__}: {error}",
        )
    write_jsonl(run_context_dir(run_id) / "tool_calls.jsonl", payload | {"arguments": arguments})
    return payload
