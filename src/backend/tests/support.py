"""Shared backend test helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlmodel import SQLModel, create_engine

import backend.ai.contadores_conversation_bot as contadores_conversation_bot_module
import backend.database as database_module
import backend.endpoints.contadores as contadores_endpoints
import backend.endpoints.workstation as workstation_endpoints
from backend.ai import codex_agent_runtime
from backend.ai.client_profile_extractor import (
    ClientProfileAdAngle,
    ClientProfileExtractionResult,
    ClientProfileSegment,
    ClientProfileSourceSnippet,
)
from backend.database import ContadoresMessage


def now_utc() -> datetime:
    """Return a timezone-aware UTC timestamp for test fixtures."""
    return datetime.now(timezone.utc)


def configure_contadores_db(monkeypatch, tmp_path) -> None:
    """Point database and Contadores router state at a temporary SQLite file."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_ENABLED", False)
    monkeypatch.setattr(contadores_endpoints, "CODEX_AGENT_TOOLS_CONVERSATION_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_AGENT_TOOLS_WORKSTATION_ENABLED", False)
    monkeypatch.setattr(workstation_endpoints, "CODEX_BACKEND_ENABLED", True)
    monkeypatch.setattr(contadores_conversation_bot_module, "CODEX_BACKEND_ENABLED", True)
    monkeypatch.setattr(codex_agent_runtime, "CODEX_BACKEND_ENABLED", True)
    pending_alert_claims = getattr(contadores_endpoints, "PENDING_ALERT_CLAIMS", None)
    if pending_alert_claims is not None:
        pending_alert_claims.clear()
    db_path = tmp_path / "contadores.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    monkeypatch.setattr(database_module, "engine", engine)
    monkeypatch.setattr(database_module, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(contadores_endpoints, "engine", engine)
    SQLModel.metadata.create_all(engine)


def fake_profile_extraction(**kwargs) -> ClientProfileExtractionResult:
    """Return deterministic transcript extraction for lifecycle tests."""
    return ClientProfileExtractionResult(
        business_summary="Clinica dental enfocada en implantes premium.",
        offer_summary="Evaluacion inicial para pacientes que necesitan implantes.",
        market_summary="Pacientes adultos que quieren recuperar sonrisa sin vueltas.",
        segments=[
            ClientProfileSegment(
                name="pacientes implantes premium",
                description="Adultos con perdida dental y capacidad de pago.",
                geo="Montevideo",
                meta_targeting_notes="Usar geo local y copies sobre recuperar sonrisa.",
            )
        ],
        ad_angles=[
            ClientProfileAdAngle(
                hook="Recupera tu sonrisa sin esperar meses",
                problem="Perdida dental",
                desired_outcome="Volver a sonreir con confianza",
                without_objection="sin tratamientos eternos",
                evidence="quiere pacientes premium",
            )
        ],
        meta_planning={
            "objective": "OUTCOME_LEADS",
            "lead_destination": "whatsapp",
            "suggested_daily_budget_usd": 20,
            "required_before_meta_publish": ["page_id", "whatsapp_phone_number_id"],
        },
        delivery_notes={"lead_sheet": "Crear Google Sheet de delivery para el cliente."},
        unresolved_questions=["Confirmar radio geografico exacto antes de publicar en Meta."],
        source_snippets=[
            ClientProfileSourceSnippet(
                topic="oferta",
                quote="El cliente vende implantes y quiere pacientes premium.",
                use_for="Meta copy y segmentacion",
            )
        ],
        confidence="high",
    )


def add_recent_inbound(lead_id: str, *, text: str = "Si, me interesa") -> ContadoresMessage:
    """Add one recent inbound WhatsApp message to keep the 24-hour window open."""
    return ContadoresMessage.add(
        lead_id=lead_id,
        from_me=False,
        text=text,
        created_at=now_utc() - timedelta(minutes=5),
    )


def build_abogados_test_funnel(
    *,
    referral_ids: list[str] | None = None,
    initial_reply_quiet_seconds: int = 1,
) -> dict[str, object]:
    """Build a compact Abogados funnel fixture."""
    return {
        "id": "abogados",
        "label": "Abogados",
        "kind": "campaign",
        "enabled": True,
        "sheet_url": None,
        "sheet_gid": None,
        "sheet_source_filter": None,
        "sheet_poll_seconds": 30,
        "template_language": "es",
        "opener_text": (
            "Hola {nombre}, llenaste el formulario para abogados de {pais} sobre como conseguir "
            "casos redituables a tu whatsapp. es correcto?"
        ),
        "opener_template_name": "abogados_intro_nombre_pais_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "manual_ping_text": "Hola, queria saber si queres que retomemos la conversacion",
        "manual_ping_template_name": None,
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/facundogoiriz/crecimiento",
        "alert_emails": [],
        "whatsapp_referral_source_ids": referral_ids or [],
        "initial_reply_quiet_seconds": initial_reply_quiet_seconds,
        "post_loom_min_seconds": 600,
        "post_loom_quiet_seconds": 30,
        "strategies": [
            {
                "step": "loom",
                "id": "loom_mp4",
                "label": "WhatsApp MP4",
                "weight": 100,
                "delivery": "video",
                "sequence_step": "loom_video",
                "message_text": "Video enviado por WhatsApp.",
                "media_type": "video",
                "media_path": "data/abogados/videos/loom_60_seconds_captions.mp4",
                "media_caption": None,
            }
        ],
    }


def build_contadores_test_funnel(**overrides: object) -> dict[str, object]:
    """Build a compact Contadores funnel fixture."""
    funnel = build_abogados_test_funnel(initial_reply_quiet_seconds=30)
    funnel.update(
        {
            "id": "contadores",
            "label": "Contadores",
            "sheet_url": "https://docs.google.com/spreadsheets/d/example",
            "sheet_gid": "0",
            "opener_text": (
                "Hola {nombre}, llenaste el formulario para contadores de {pais} sobre como conseguir "
                "clientes a tu whatsapp. es correcto?"
            ),
            "opener_template_name": "contadores_intro_nombre_pais_es_v1",
            "opener_followup_text": "Queria compartirte informacion sobre como podes obtener clientes.",
            "opener_followup_template_name": "contadores_followup_es_v1",
            "manual_ping_template_name": "contadores_manual_ping_es_v1",
            "loom_intro_text": "Perfecto. Te cuento rapido como funciona:",
            "calendly_base_url": "https://calendly.com/test/contadores",
            "whatsapp_referral_source_ids": [],
        }
    )
    funnel["strategies"][0]["media_path"] = "data/contadores/videos/loom_60_seconds_captions.mp4"
    funnel.update(overrides)
    return funnel


def write_funnels_config(tmp_path, *funnels: dict[str, object]) -> None:
    """Write the test funnel override config."""
    (tmp_path / "funnels.json").write_text(
        json.dumps({"version": 1, "funnels": list(funnels)}),
        encoding="utf-8",
    )
