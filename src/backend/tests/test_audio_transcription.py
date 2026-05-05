"""Tests for inbound WhatsApp audio transcription helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import backend.audio_transcription as audio_transcription


def test_transcribe_audio_media_converts_ogg_before_openai(monkeypatch, tmp_path) -> None:
    """WhatsApp OGG audio should be converted before calling the transcription API."""
    data_dir = tmp_path / "data"
    source_path = data_dir / "contadores" / "inbound_media" / "audio.ogg"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"ogg bytes")
    converted_paths: list[Path] = []

    def fake_convert(source: Path, target_dir: Path) -> Path:
        assert source == source_path
        target = target_dir / "audio-transcription.mp3"
        target.write_bytes(b"mp3 bytes")
        converted_paths.append(target)
        return target

    class FakeTranscriptions:
        def create(self, *, file, model, prompt, response_format):
            assert file.name.endswith(".mp3")
            assert model == "gpt-4o-transcribe"
            assert "WhatsApp" in prompt
            assert response_format == "text"
            return " Hola, cuanto cuesta? "

    class FakeAudio:
        transcriptions = FakeTranscriptions()

    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            assert api_key == "test-key"
            self.audio = FakeAudio()

    monkeypatch.setattr(audio_transcription, "DATA_DIR", data_dir)
    monkeypatch.setattr(audio_transcription, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(audio_transcription, "_convert_audio_for_transcription", fake_convert)
    monkeypatch.setattr(audio_transcription, "OpenAI", FakeOpenAI)

    transcript = audio_transcription.transcribe_audio_media(
        "data/contadores/inbound_media/audio.ogg",
        mime_type="audio/ogg",
    )

    assert transcript == "Hola, cuanto cuesta?"
    assert len(converted_paths) == 1


def test_transcribe_audio_media_uses_supported_file_without_conversion(monkeypatch, tmp_path) -> None:
    """Supported files should be sent directly to OpenAI."""
    data_dir = tmp_path / "data"
    source_path = data_dir / "contadores" / "inbound_media" / "audio.mp3"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"mp3 bytes")

    class FakeTranscriptions:
        def create(self, *, file, model, prompt, response_format):
            del prompt
            del response_format
            assert file.name.endswith(".mp3")
            assert model == "gpt-4o-transcribe"
            return SimpleNamespace(text="Hola directo")

    class FakeAudio:
        transcriptions = FakeTranscriptions()

    class FakeOpenAI:
        def __init__(self, *, api_key: str):
            del api_key
            self.audio = FakeAudio()

    def fail_convert(source: Path, target_dir: Path) -> Path:
        del source
        del target_dir
        raise AssertionError("conversion should not run")

    monkeypatch.setattr(audio_transcription, "DATA_DIR", data_dir)
    monkeypatch.setattr(audio_transcription, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(audio_transcription, "_convert_audio_for_transcription", fail_convert)
    monkeypatch.setattr(audio_transcription, "OpenAI", FakeOpenAI)

    transcript = audio_transcription.transcribe_audio_media(
        "data/contadores/inbound_media/audio.mp3",
        mime_type="audio/mpeg",
    )

    assert transcript == "Hola directo"
