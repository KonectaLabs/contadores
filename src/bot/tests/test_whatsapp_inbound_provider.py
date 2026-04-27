"""Unit tests for WhatsApp inbound webhook mapping."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI

import providers
from providers import WhatsAppProvider


def build_provider() -> WhatsAppProvider:
    """Build provider instance without running constructor side-effects."""
    return WhatsAppProvider.__new__(WhatsAppProvider)


def test_build_inbound_event_from_message_text() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text=" Hola ",
        caption=None,
        reaction=None,
        from_user=SimpleNamespace(wa_id="5491122233344"),
        id="wamid.text.1",
        type=SimpleNamespace(value="text"),
    )

    event = provider._build_inbound_event_from_message(msg)

    assert event is not None
    assert event.phone == "5491122233344"
    assert event.text == "Hola"
    assert event.external_id == "wamid.text.1"
    assert event.in_reply_to is None


def test_build_inbound_event_from_message_reaction_fallback() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text=None,
        caption=None,
        reaction=SimpleNamespace(emoji="👍"),
        from_user=SimpleNamespace(wa_id="5491122233344"),
        id="wamid.reaction.1",
        type=SimpleNamespace(value="reaction"),
    )

    event = provider._build_inbound_event_from_message(msg)

    assert event is not None
    assert event.text == "[reaction] 👍"


def test_build_inbound_event_from_media_only_message() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text=None,
        caption=None,
        reaction=None,
        image=SimpleNamespace(
            id="media-image-1",
            filename="lead-photo.jpg",
            mime_type="image/jpeg",
            sha256="sha-image",
        ),
        from_user=SimpleNamespace(wa_id="5491122233344"),
        id="wamid.image.1",
        type=SimpleNamespace(value="image"),
    )

    event = provider._build_inbound_event_from_message(msg)

    assert event is not None
    assert event.text == "[image]"
    assert event.media_type == "image"
    assert event.media_id == "media-image-1"
    assert event.media_mime_type == "image/jpeg"
    assert event.media_filename == "lead-photo.jpg"
    assert event.media_sha256 == "sha-image"


def test_build_inbound_event_from_audio_message() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text=None,
        caption=None,
        reaction=None,
        audio=SimpleNamespace(
            id="media-audio-1",
            filename=None,
            mime_type="audio/ogg",
            sha256="sha-audio",
        ),
        from_user=SimpleNamespace(wa_id="5491122233344"),
        id="wamid.audio.1",
        type=SimpleNamespace(value="audio"),
    )

    event = provider._build_inbound_event_from_message(msg)

    assert event is not None
    assert event.text == "[audio]"
    assert event.media_type == "audio"
    assert event.media_id == "media-audio-1"
    assert event.media_mime_type == "audio/ogg"


def test_build_inbound_event_from_callback_button() -> None:
    provider = build_provider()
    btn = SimpleNamespace(
        title="Me interesa",
        data="cta_interest",
        from_user=SimpleNamespace(wa_id="5491199988877"),
        id="wamid.callback.1",
        reply_to_message=None,
    )

    event = provider._build_inbound_event_from_callback(btn)

    assert event is not None
    assert event.phone == "5491199988877"
    assert event.text == "Me interesa (cta_interest)"
    assert event.external_id == "wamid.callback.1"
    assert event.in_reply_to is None


def test_build_inbound_event_from_message_replied_context() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text="hola",
        caption=None,
        reaction=None,
        from_user=SimpleNamespace(wa_id="5491122233344"),
        id="wamid.inbound.2",
        message_id_to_reply="wamid.inbound.2",
        reply_to_message=SimpleNamespace(message_id="wamid.outbound.9"),
        type=SimpleNamespace(value="text"),
    )

    event = provider._build_inbound_event_from_message(msg)

    assert event is not None
    assert event.in_reply_to == "wamid.outbound.9"


def test_build_inbound_event_from_callback_replied_context() -> None:
    provider = build_provider()
    btn = SimpleNamespace(
        title="Me interesa",
        data="cta_interest",
        from_user=SimpleNamespace(wa_id="5491199988877"),
        id="wamid.callback.2",
        reply_to_message=SimpleNamespace(message_id="wamid.outbound.42"),
    )

    event = provider._build_inbound_event_from_callback(btn)

    assert event is not None
    assert event.in_reply_to == "wamid.outbound.42"


def test_build_inbound_event_ignores_self_authored_by_display_phone() -> None:
    provider = build_provider()
    msg = SimpleNamespace(
        from_me=False,
        text="hola",
        caption=None,
        reaction=None,
        from_user=SimpleNamespace(wa_id="5491153484587"),
        metadata=SimpleNamespace(display_phone_number="+54 9 11 5348-4587"),
        id="wamid.self.1",
        reply_to_message=None,
        type=SimpleNamespace(value="text"),
    )

    assert provider._build_inbound_event_from_message(msg) is None


def test_build_inbound_event_ignores_stale_update() -> None:
    provider = build_provider()
    provider.max_inbound_age_seconds = 60
    msg = SimpleNamespace(
        from_me=False,
        text="hola",
        caption=None,
        reaction=None,
        from_user=SimpleNamespace(wa_id="5491122233344"),
        metadata=SimpleNamespace(display_phone_number="+54 9 11 5348-4587"),
        id="wamid.old.1",
        reply_to_message=None,
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=5),
        type=SimpleNamespace(value="text"),
    )

    assert provider._build_inbound_event_from_message(msg) is None


def test_normalize_outbound_recipient_accepts_phone_and_url() -> None:
    provider = build_provider()
    assert provider._normalize_outbound_recipient("+54 9 11 5348-4587") == "5491153484587"
    assert provider._normalize_outbound_recipient("https://wa.me/5491153484587") == "5491153484587"
    assert provider._normalize_outbound_recipient("(011) 15 5702-2416") == "5491157022416"


def test_parse_optional_int_reads_valid_app_id() -> None:
    assert WhatsAppProvider._parse_optional_int("4069143956635777", env_name="WA_APP_ID") == 4069143956635777
    assert WhatsAppProvider._parse_optional_int("", env_name="WA_APP_ID") is None
    assert WhatsAppProvider._parse_optional_int("not-a-number", env_name="WA_APP_ID") is None


def test_resolve_webhook_challenge_delay() -> None:
    assert WhatsAppProvider._resolve_webhook_challenge_delay("20") == 20
    assert WhatsAppProvider._resolve_webhook_challenge_delay("") == 10
    assert WhatsAppProvider._resolve_webhook_challenge_delay("-1") == 10
    assert WhatsAppProvider._resolve_webhook_challenge_delay("abc") == 10


def test_resolve_inbound_max_age_seconds() -> None:
    assert WhatsAppProvider._resolve_inbound_max_age_seconds("120") == 120
    assert WhatsAppProvider._resolve_inbound_max_age_seconds("") == 3600
    assert WhatsAppProvider._resolve_inbound_max_age_seconds("abc") == 3600


def test_configured_depends_on_initialized_pywa_client() -> None:
    provider = build_provider()
    provider._wa = None
    assert provider.configured is False
    provider._wa = object()
    assert provider.configured is True


def test_detects_meta_oauth_101_validation_error() -> None:
    exc = RuntimeError(
        "WhatsAppError(code=101, message='Error validating application. Cannot get application info due to a system error.', type='OAuthException')"
    )
    assert WhatsAppProvider._is_meta_app_validation_error(exc) is True
    assert WhatsAppProvider._is_meta_app_validation_error(RuntimeError("generic timeout")) is False


def test_init_disables_provider_when_pywa_client_init_fails(monkeypatch) -> None:
    class BrokenWhatsApp:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "WhatsAppError(code=101, message='Error validating application. Cannot get application info due to a system error.', type='OAuthException')"
            )

    monkeypatch.setenv("WA_PHONE_ID", "881994095003323")
    monkeypatch.setenv("WA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("WA_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("WA_CALLBACK_URL", "https://example.com/webhook/wa")
    monkeypatch.setattr(providers, "WhatsApp", BrokenWhatsApp)

    async def _on_inbound(_event):
        return None

    provider = WhatsAppProvider(FastAPI(), _on_inbound)
    assert provider.configured is False
    asyncio.run(provider.close())


def test_init_blocks_provider_when_webhook_bootstrap_fails(monkeypatch) -> None:
    init_calls: list[dict[str, object]] = []

    class FlakyWhatsApp:
        def __init__(self, *args, **kwargs):
            init_calls.append(dict(kwargs))
            if kwargs.get("callback_url") is not None:
                raise RuntimeError(
                    "WhatsAppError(code=101, message='Error validating application. Cannot get application info due to a system error.', type='OAuthException')"
                )

        def on_message(self):
            raise AssertionError("webhook handlers should not register when webhook client init fails")

        def on_callback_button(self):
            raise AssertionError("webhook handlers should not register when webhook client init fails")

        def on_callback_selection(self):
            raise AssertionError("webhook handlers should not register when webhook client init fails")

    monkeypatch.setenv("WA_PHONE_ID", "881994095003323")
    monkeypatch.setenv("WA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("WA_APP_SECRET", "fake-secret")
    monkeypatch.setenv("WA_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("WA_CALLBACK_URL", "https://example.com/webhook/wa")
    monkeypatch.setattr(providers, "WhatsApp", FlakyWhatsApp)

    async def _on_inbound(_event):
        return None

    provider = WhatsAppProvider(FastAPI(), _on_inbound)

    assert provider.configured is False
    assert len(init_calls) == 1
    assert init_calls[0]["server"] is not None
    assert init_calls[0]["verify_token"] == "verify-token"
    assert init_calls[0]["webhook_endpoint"] == "/webhook/wa"
    assert init_calls[0]["app_secret"] == "fake-secret"
    assert init_calls[0]["callback_url_scope"].name == "PHONE"
    assert init_calls[0]["callback_url"] == "https://example.com"

    asyncio.run(provider.close())


def test_init_allows_missing_callback_url(monkeypatch) -> None:
    init_calls: list[dict[str, object]] = []

    class WorkingWhatsApp:
        def __init__(self, *args, **kwargs):
            init_calls.append(dict(kwargs))

        def on_message(self):
            return lambda fn: fn

        def on_callback_button(self):
            return lambda fn: fn

        def on_callback_selection(self):
            return lambda fn: fn

        def on_message_status(self):
            return lambda fn: fn

    monkeypatch.setenv("WA_PHONE_ID", "881994095003323")
    monkeypatch.setenv("WA_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("WA_VERIFY_TOKEN", "verify-token")
    monkeypatch.delenv("WA_CALLBACK_URL", raising=False)
    monkeypatch.setattr(providers, "WhatsApp", WorkingWhatsApp)

    async def _on_inbound(_event):
        return None

    provider = WhatsAppProvider(FastAPI(), _on_inbound)

    assert provider.configured is True
    assert len(init_calls) == 1
    assert init_calls[0]["server"] is not None
    assert init_calls[0]["verify_token"] == "verify-token"
    assert init_calls[0]["webhook_endpoint"] == "/"
    assert "callback_url" not in init_calls[0]
    assert "callback_url_scope" not in init_calls[0]

    asyncio.run(provider.close())


def test_build_message_status_event_maps_supported_statuses() -> None:
    provider = build_provider()
    status_update = SimpleNamespace(
        id="wamid.outbound.1",
        status=SimpleNamespace(value="delivered"),
    )

    event = provider._build_message_status_event(status_update)

    assert event is not None
    assert event.external_id == "wamid.outbound.1"
    assert event.status == "delivered"
