"""Regression tests for file-backed funnel definitions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_funnels_endpoint_exposes_default_contadores(monkeypatch, tmp_path) -> None:
    """The funnel API should always expose the built-in Contadores funnel."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))

    with TestClient(app) as client:
        response = client.get("/api/funnels")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config_path"] == str(tmp_path / "funnels.json")
    assert payload["funnels"][0]["id"] == "contadores"
    assert payload["funnels"][0]["opener_template_name"] == "contadores_intro_es_v2"
    assert payload["funnels"][0]["manual_ping_template_name"] == "contadores_manual_ping_es_v1"
    assert payload["funnels"][0]["manual_ping_text"] == (
        "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion"
    )


def test_funnels_endpoint_persists_new_niche(monkeypatch, tmp_path) -> None:
    """A new niche funnel should be saved to the shared JSON config file."""
    config_path = tmp_path / "funnels.json"
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(config_path))

    new_funnel = {
        "id": "abogados",
        "label": "Abogados",
        "enabled": True,
        "source_mode": "testing",
        "test_phone": "+5491111111111",
        "test_name": "Lead Abogado",
        "sheet_url": None,
        "sheet_gid": None,
        "sheet_source_filter": None,
        "sheet_poll_seconds": 300,
        "template_language": "es",
        "opener_text": "Hola, completaste el formulario para abogados. Es correcto?",
        "opener_template_name": "abogados_intro_es_v1",
        "opener_followup_text": "Queria compartirte informacion sobre la propuesta para tu estudio juridico.",
        "opener_followup_template_name": "abogados_followup_es_v1",
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "https://www.loom.com/share/abogados",
        "video_check_text": "Terminaste de ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/konecta/abogados",
        "alert_emails": ["facu@example.com"],
        "initial_reply_quiet_seconds": 30,
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

    with TestClient(app) as client:
        create_response = client.post("/api/funnels", json=new_funnel)
        list_response = client.get("/api/funnels")

    assert create_response.status_code == 200
    assert create_response.json()["id"] == "abogados"
    assert config_path.exists()
    assert list_response.status_code == 200
    ids = [item["id"] for item in list_response.json()["funnels"]]
    assert ids == ["contadores", "abogados"]
