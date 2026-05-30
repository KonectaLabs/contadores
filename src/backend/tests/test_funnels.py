"""Regression tests for file-backed funnel definitions."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app


def test_funnels_endpoint_exposes_default_contadores(monkeypatch, tmp_path) -> None:
    """The funnel API should expose the versioned seed before local overrides exist."""
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(tmp_path / "funnels.json"))

    with TestClient(app) as client:
        response = client.get("/api/funnels")

    assert response.status_code == 200
    payload = response.json()
    assert payload["seed_config_path"].endswith("config/default-funnels.json")
    assert payload["config_path"] == str(tmp_path / "funnels.json")
    assert payload["config_errors"] == []
    assert payload["funnels"][0]["id"] == "contadores"
    assert payload["funnels"][0]["kind"] == "campaign"
    assert payload["funnels"][0]["sheet_poll_seconds"] == 30
    assert payload["funnels"][0]["opener_template_name"] == "contadores_intro_nombre_pais_es_v1"
    assert payload["funnels"][0]["manual_ping_template_name"] == "contadores_manual_ping_es_v1"
    assert payload["funnels"][0]["whatsapp_referral_source_ids"] == []
    assert payload["funnels"][0]["offer_price_usd"] == 599
    assert payload["funnels"][0]["offer_payment_model"] == "monthly"
    assert [item["id"] for item in payload["funnels"][0]["strategies"]] == ["text_offer_599"]
    assert payload["funnels"][0]["strategies"][0]["delivery"] == "text"
    assert payload["funnels"][-1]["id"] == "general"
    assert payload["funnels"][-1]["kind"] == "inbox"
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
        "loom_intro_text": "Perfecto. Te cuento rapido como traemos consultas a tu estudio:",
        "loom_url": "https://www.loom.com/share/abogados",
        "video_check_text": "conseguiste ver el video?",
        "calendly_intro_text": "Para avanzar, elegi un horario:",
        "calendly_base_url": "https://calendly.com/konecta/abogados",
        "alert_emails": ["facu@example.com"],
        "whatsapp_referral_source_ids": ["120244283740930010"],
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
    assert list_response.json()["config_errors"] == []
    ids = [item["id"] for item in list_response.json()["funnels"]]
    assert ids == ["contadores", "abogados", "general"]
    abogados = list_response.json()["funnels"][1]
    assert abogados["calendly_base_url"] == "https://calendly.com/konecta/abogados"
    assert abogados["whatsapp_referral_source_ids"] == ["120244283740930010"]


def test_funnels_endpoint_keeps_config_owned_campaign_wiring(monkeypatch, tmp_path) -> None:
    """Local funnel files should own Calendly, referrals, and strategy choices."""
    config_path = tmp_path / "funnels.json"
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(config_path))
    config_path.write_text(
        """
{
  "version": 1,
  "funnels": [
    {
      "id": "contadores",
      "label": "Contadores",
      "kind": "campaign",
      "opener_text": "Hola",
      "opener_followup_text": "Follow",
      "loom_intro_text": "Intro",
      "loom_url": "https://www.loom.com/share/old",
      "video_check_text": "Lo viste?",
      "calendly_intro_text": "Agenda",
      "calendly_base_url": "https://calendly.com/contadores",
      "whatsapp_referral_source_ids": ["old-contadores-ad"],
      "strategies": [
        {
          "step": "loom",
          "id": "loom_link",
          "label": "Loom link",
          "weight": 50,
          "delivery": "link",
          "sequence_step": "loom_url",
          "message_text": "https://www.loom.com/share/old"
        },
        {
          "step": "loom",
          "id": "loom_mp4",
          "label": "WhatsApp MP4",
          "weight": 100,
          "delivery": "video",
          "sequence_step": "loom_video",
          "message_text": "Video enviado por WhatsApp.",
          "media_type": "video",
          "media_path": "data/contadores/videos/loom_60_seconds_captions.mp4"
        }
      ]
    },
    {
      "id": "abogados",
      "label": "Abogados",
      "kind": "campaign",
      "opener_text": "Hola",
      "opener_followup_text": "Follow",
      "loom_intro_text": "Intro",
      "loom_url": "https://www.loom.com/share/old-abogados",
      "video_check_text": "Lo viste?",
      "calendly_intro_text": "Agenda",
      "calendly_base_url": "https://calendly.com/abogados",
      "whatsapp_referral_source_ids": ["real-abogados-ad"],
      "strategies": [
        {
          "step": "loom",
          "id": "loom_link",
          "label": "Loom link",
          "weight": 50,
          "delivery": "link",
          "sequence_step": "loom_url",
          "message_text": "https://www.loom.com/share/old-abogados"
        },
        {
          "step": "loom",
          "id": "loom_mp4",
          "label": "WhatsApp MP4",
          "weight": 100,
          "delivery": "video",
          "sequence_step": "loom_video",
          "message_text": "Video enviado por WhatsApp.",
          "media_type": "video",
          "media_path": "data/abogados/videos/loom_60_seconds_captions.mp4"
        }
      ]
    }
  ]
}
""",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.get("/api/funnels")

    assert response.status_code == 200
    funnels = {item["id"]: item for item in response.json()["funnels"]}
    assert funnels["contadores"]["calendly_base_url"] == "https://calendly.com/contadores"
    assert funnels["abogados"]["calendly_base_url"] == "https://calendly.com/abogados"
    assert funnels["contadores"]["whatsapp_referral_source_ids"] == ["old-contadores-ad"]
    assert [item["id"] for item in funnels["contadores"]["strategies"]] == ["loom_link", "loom_mp4"]
    assert funnels["abogados"]["whatsapp_referral_source_ids"] == ["real-abogados-ad"]
    assert [item["id"] for item in funnels["abogados"]["strategies"]] == ["loom_link", "loom_mp4"]


def test_funnels_endpoint_reports_invalid_config_without_breaking(monkeypatch, tmp_path) -> None:
    """Invalid file-backed config should not break the first-run funnel menu."""
    config_path = tmp_path / "funnels.json"
    monkeypatch.setenv("FUNNELS_CONFIG_PATH", str(config_path))
    config_path.write_text("{not-json", encoding="utf-8")

    with TestClient(app) as client:
        response = client.get("/api/funnels")

    assert response.status_code == 200
    payload = response.json()
    assert payload["funnels"][0]["id"] == "contadores"
    assert payload["funnels"][-1]["id"] == "general"
    assert payload["config_errors"]
    assert "invalid JSON" in payload["config_errors"][0]
