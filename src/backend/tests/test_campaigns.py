"""Tests for owned campaign forms and converted-client campaign linking."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.database import (
    ClientLeadDelivery,
    ClientLeadDeliveryStatus,
    ClientLeadSource,
    LeadCaptureSubmission,
    PlatformAdCampaign,
    WorkstationClient,
)
from backend.main import app
from backend.tests.test_contadores import configure_contadores_db


def campaign_payload() -> dict[str, object]:
    """Return a compact active campaign command."""
    return {
        "name": "Campania Test",
        "status": "active",
        "client": {
            "name": "Cliente Campania",
            "whatsapp": "+5491123456789",
            "email": "cliente@example.com",
            "extra_info": "Cliente creado desde campaign test.",
        },
        "daily_budget_usd": 15,
        "geo_targeting": {
            "country_code": "AR",
            "regions": [{"name": "Buenos Aires"}, {"name": "Cordoba"}],
            "cities": [{"name": "CABA"}, {"name": "La Plata"}],
        },
        "creative_brief": "Problema primero, formulario propio.",
        "form_schema": {
            "fields": [
                {"id": "full_name", "label": "Nombre", "type": "text", "required": True},
                {"id": "phone", "label": "WhatsApp", "type": "phone", "required": True},
                {"id": "email", "label": "Email", "type": "email"},
                {"id": "necesidad", "label": "Necesidad", "type": "textarea", "required": True},
            ],
        },
    }


def test_campaign_api_creates_converted_client_and_queues_delivery(monkeypatch, tmp_path) -> None:
    """Owned form submissions should reuse Workstation and Client Lead Delivery."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_response = client.post("/api/campaigns", json=campaign_payload())
        assert create_response.status_code == 200, create_response.text
        campaign = create_response.json()["campaign"]

        assert campaign["status"] == "active"
        assert campaign["client"]["lead"]["normalized_phone"]
        assert campaign["client_lead_source_id"]
        assert campaign["platform_ad_campaign_id"]
        assert campaign["location"] == "AR · Buenos Aires, Cordoba · CABA, La Plata"
        assert campaign["campaign_info"]["meta_targeting"]["geo_locations"]["countries"] == ["AR"]
        assert campaign["campaign_info"]["location_regions"] == [
            {"name": "Buenos Aires", "country": "AR"},
            {"name": "Cordoba", "country": "AR"},
        ]
        assert campaign["campaign_info"]["location_cities"] == [
            {"name": "CABA", "country": "AR"},
            {"name": "La Plata", "country": "AR"},
        ]
        assert campaign["public_url"].endswith(f"/c/{campaign['public_slug']}")
        assert WorkstationClient.get_by_id(campaign["client_id"]) is not None
        assert ClientLeadSource.get_by_id(campaign["client_lead_source_id"]) is not None
        platform_campaign = PlatformAdCampaign.get_by_id(campaign["platform_ad_campaign_id"])
        assert platform_campaign is not None
        assert platform_campaign.target_segments()[0]["targeting"]["geo_locations"]["countries"] == ["AR"]
        assert platform_campaign.target_segments()[1]["regions"][0]["name"] == "Buenos Aires"

        public_response = client.get(f"/api/public/campaigns/{campaign['public_slug']}")
        assert public_response.status_code == 200
        assert public_response.json()["campaign"]["form_schema"]["fields"][0]["id"] == "full_name"

        submit_response = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={
                "answers": {
                    "full_name": "Lead Capturado",
                    "phone": "+5491199988877",
                    "email": "lead@example.com",
                    "necesidad": "Quiero mas informacion",
                },
                "idempotency_key": "campaign-submit-1",
            },
        )
        assert submit_response.status_code == 200, submit_response.text
        submitted = submit_response.json()
        assert submitted["delivery_queued"] is True
        assert set(submitted["submission"]) == {"id", "created_at"}

        duplicate_response = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={
                "answers": {
                    "full_name": "Lead Capturado",
                    "phone": "+5491199988877",
                    "necesidad": "Duplicado",
                },
                "idempotency_key": "campaign-submit-1",
            },
        )
        assert duplicate_response.status_code == 200
        assert duplicate_response.json()["duplicate"] is True
        assert "meta_event_response" not in duplicate_response.text

        submissions = LeadCaptureSubmission.list_by_campaign(campaign["id"])
        deliveries = ClientLeadDelivery.list_by_source(campaign["client_lead_source_id"])
        assert len(submissions) == 1
        assert len(deliveries) == 1
        assert deliveries[0].raw_row["necesidad"] == "Quiero mas informacion"
        assert submissions[0].meta_event_status == "disabled"

        sync_response = client.post(f"/api/client-lead-sources/{campaign['client_lead_source_id']}/sync")
        assert sync_response.status_code == 200
        assert sync_response.json()["source"]["last_sync_note"] == "owned campaign form source; submissions arrive directly"


def test_public_form_requires_active_campaign_and_valid_phone(monkeypatch, tmp_path) -> None:
    """Draft campaigns are not public and invalid submission phones are rejected."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/campaigns",
            json={**campaign_payload(), "status": "draft", "name": "Draft Campaign"},
        )
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]

        assert client.get(f"/api/public/campaigns/{campaign['public_slug']}").status_code == 404

        activate_response = client.patch(f"/api/campaigns/{campaign['id']}", json={"status": "active"})
        assert activate_response.status_code == 200
        bad_submit = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={"answers": {"full_name": "Lead Malo", "phone": "no-phone"}},
        )
        assert bad_submit.status_code == 400
        assert "WhatsApp" in bad_submit.json()["detail"]


def test_public_submission_validates_schema_and_payload_caps(monkeypatch, tmp_path) -> None:
    """Public submissions should not accept unknown, missing, or oversized fields."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_response = client.post("/api/campaigns", json=campaign_payload())
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]
        submit_url = f"/api/public/campaigns/{campaign['public_slug']}/submissions"

        missing_response = client.post(submit_url, json={"answers": {"full_name": "Lead"}})
        assert missing_response.status_code == 400
        assert "WhatsApp" in missing_response.json()["detail"]

        unknown_response = client.post(
            submit_url,
            json={"answers": {"full_name": "Lead", "phone": "+5491199988877", "extra": "x"}},
        )
        assert unknown_response.status_code == 400
        assert "Unknown field" in unknown_response.json()["detail"]

        oversized_response = client.post(
            submit_url,
            json={"answers": {"full_name": "Lead", "phone": "+5491199988877", "necesidad": "x" * 2500}},
        )
        assert oversized_response.status_code == 400
        assert "too long" in oversized_response.json()["detail"]


def test_public_form_html_escapes_configured_schema(monkeypatch, tmp_path) -> None:
    """Public form labels/options come from config and must not render as raw HTML."""
    configure_contadores_db(monkeypatch, tmp_path)

    payload = campaign_payload()
    payload["form_schema"] = {
        "fields": [
            {
                "id": "full_name",
                "label": 'Nombre </script><div id="owned">x</div>',
                "type": "text",
                "required": True,
                "placeholder": '" autofocus onfocus="alert(1)',
            },
            {
                "id": "choice",
                "label": "Opcion",
                "type": "select",
                "options": ['<img src=x onerror="alert(1)">', "Normal"],
            },
        ],
    }

    with TestClient(app) as client:
        create_response = client.post("/api/campaigns", json=payload)
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]

        html_response = client.get(f"/c/{campaign['public_slug']}")
        assert html_response.status_code == 200
        html = html_response.text

        assert '</script><div id="owned">' not in html
        assert "${option}</button>" not in html
        assert "escapeHtml(field.label || field.id)" in html
        assert "escapeAttr(option)" in html


def test_public_idempotency_is_campaign_scoped_and_phone_dedupes(monkeypatch, tmp_path) -> None:
    """The same external key can be reused across campaigns, but one phone does not enqueue twice."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        first = client.post("/api/campaigns", json={**campaign_payload(), "name": "Campania Uno"})
        second = client.post(
            "/api/campaigns",
            json={
                **campaign_payload(),
                "name": "Campania Dos",
                "client": {
                    "name": "Cliente Dos",
                    "whatsapp": "+5491122222222",
                    "email": "dos@example.com",
                },
            },
        )
        assert first.status_code == 200
        assert second.status_code == 200
        first_campaign = first.json()["campaign"]
        second_campaign = second.json()["campaign"]

        base_answers = {"full_name": "Lead Compartido", "phone": "+5491199988877", "necesidad": "Info"}
        first_submit = client.post(
            f"/api/public/campaigns/{first_campaign['public_slug']}/submissions",
            json={"answers": base_answers, "idempotency_key": "same-browser-key"},
        )
        second_submit = client.post(
            f"/api/public/campaigns/{second_campaign['public_slug']}/submissions",
            json={"answers": base_answers, "idempotency_key": "same-browser-key"},
        )
        assert first_submit.status_code == 200
        assert second_submit.status_code == 200
        assert first_submit.json()["duplicate"] is False
        assert second_submit.json()["duplicate"] is False
        assert len(LeadCaptureSubmission.list_by_campaign(first_campaign["id"])) == 1
        assert len(LeadCaptureSubmission.list_by_campaign(second_campaign["id"])) == 1

        repeat_phone = client.post(
            f"/api/public/campaigns/{first_campaign['public_slug']}/submissions",
            json={"answers": {**base_answers, "necesidad": "Otra vez"}, "idempotency_key": "new-key-same-phone"},
        )
        assert repeat_phone.status_code == 200
        assert repeat_phone.json()["duplicate"] is True
        assert len(ClientLeadDelivery.list_by_source(first_campaign["client_lead_source_id"])) == 1


def test_agent_campaign_endpoints_support_dry_run_and_submissions(monkeypatch, tmp_path) -> None:
    """Agent API should expose campaign/client operations over HTTP."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        dry_response = client.post(
            "/api/agent/clients/converted",
            json={"name": "Cliente Dry", "whatsapp": "+5491111111111", "dry_run": True},
        )
        assert dry_response.status_code == 200
        assert dry_response.json()["dry_run"] is True

        create_response = client.post("/api/agent/campaigns", json=campaign_payload())
        assert create_response.status_code == 200, create_response.text
        campaign = create_response.json()["campaign"]

        list_response = client.get("/api/agent/campaigns", params={"status": "active"})
        assert list_response.status_code == 200
        assert list_response.json()["count"] == 1

        submit_response = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={
                "answers": {"full_name": "Lead Agent", "phone": "+5491199988877", "necesidad": "Info"},
                "idempotency_key": "agent-submit-1",
            },
        )
        assert submit_response.status_code == 200

        submissions_response = client.get(f"/api/agent/campaigns/{campaign['id']}/submissions")
        assert submissions_response.status_code == 200
        assert submissions_response.json()["count"] == 1


def test_campaign_patch_rejects_invalid_or_unpublishable_client(monkeypatch, tmp_path) -> None:
    """Publishing must keep the campaign linked to a real client with WhatsApp."""
    configure_contadores_db(monkeypatch, tmp_path)

    with TestClient(app) as client:
        create_response = client.post("/api/campaigns", json={**campaign_payload(), "status": "draft"})
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]

        invalid_client = client.patch(f"/api/campaigns/{campaign['id']}", json={"client_id": "missing-client"})
        assert invalid_client.status_code == 404

        unlinked = client.patch(f"/api/campaigns/{campaign['id']}", json={"client_id": "", "status": "active"})
        assert unlinked.status_code == 400
        assert "linked to a client" in unlinked.json()["detail"]


def test_meta_capi_status_is_blocked_when_live_writes_are_not_enabled(monkeypatch, tmp_path) -> None:
    """Meta CAPI is a live write and should not block the local lead capture path."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("META_MARKETING_LIVE_WRITES_ENABLED", raising=False)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/campaigns",
            json={**campaign_payload(), "meta_pixel_id": "pixel-1", "meta_events_enabled": True},
        )
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]

        submit_response = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={
                "answers": {"full_name": "Lead Meta", "phone": "+5491199988877", "necesidad": "Info"},
                "idempotency_key": "meta-submit-1",
            },
        )
        assert submit_response.status_code == 200
        assert "META_MARKETING_ACCESS_TOKEN" not in submit_response.text
        submission = LeadCaptureSubmission.list_by_campaign(campaign["id"])[0]
        assert submission.meta_event_status == "blocked"
        assert "META_MARKETING_LIVE_WRITES_ENABLED" in submission.meta_event_response["blocked_reasons"]


def test_meta_capi_errors_are_redacted_and_not_public(monkeypatch, tmp_path) -> None:
    """Provider errors must not leak Meta access tokens into public responses or DB payloads."""
    configure_contadores_db(monkeypatch, tmp_path)
    monkeypatch.setenv("META_MARKETING_API_VERSION", "v25.0")
    monkeypatch.setenv("META_MARKETING_ACCESS_TOKEN", "secret-token-value")
    monkeypatch.setenv("META_MARKETING_LIVE_WRITES_ENABLED", "true")

    import backend.meta_conversions as meta_conversions

    def failing_poster(*, api_version: str, access_token: str, timeout: float = 20):
        def graph_post(path: str, payload: dict[str, object]) -> dict[str, object]:
            raise RuntimeError(f"https://graph.facebook.com/{api_version}/{path}?access_token={access_token}")

        return graph_post

    monkeypatch.setattr(meta_conversions, "_default_graph_poster", failing_poster)

    with TestClient(app) as client:
        create_response = client.post(
            "/api/campaigns",
            json={**campaign_payload(), "meta_pixel_id": "pixel-1", "meta_events_enabled": True},
        )
        assert create_response.status_code == 200
        campaign = create_response.json()["campaign"]

        submit_response = client.post(
            f"/api/public/campaigns/{campaign['public_slug']}/submissions",
            json={
                "answers": {"full_name": "Lead Meta", "phone": "+5491199988877", "necesidad": "Info"},
                "idempotency_key": "meta-fail-1",
            },
        )
        assert submit_response.status_code == 200
        assert "secret-token-value" not in submit_response.text

        submission = LeadCaptureSubmission.list_by_campaign(campaign["id"])[0]
        assert submission.meta_event_status == "failed"
        assert "secret-token-value" not in str(submission.meta_event_response)
        assert "access_token=[redacted]" in str(submission.meta_event_response)
