"""Audio transcription helpers for inbound WhatsApp media."""

from __future__ import annotations

import logging
import mimetypes
import shutil
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI

from backend.config import (
    AUDIO_TRANSCRIPTION_MODEL,
    AUDIO_TRANSCRIPTION_PROMPT,
    OPENAI_API_KEY,
)
from backend.database import DATA_DIR

logger = logging.getLogger(__name__)

SUPPORTED_TRANSCRIPTION_SUFFIXES = {
    ".m4a",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpga",
    ".wav",
    ".webm",
}
OGG_AUDIO_SUFFIXES = {".ogg", ".opus"}


class AudioTranscriptionError(RuntimeError):
    """Raised when inbound audio cannot be transcribed safely."""


def resolve_audio_media_path(media_path: str | None) -> Path | None:
    """Resolve a stored data/... media path inside the shared data directory."""
    clean_path = (media_path or "").strip()
    if not clean_path:
        return None

    candidate = Path(clean_path).expanduser()
    data_dir = DATA_DIR.expanduser().resolve()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        relative_parts = parts[1:] if parts and parts[0] == "data" else parts
        resolved = data_dir.joinpath(*relative_parts).resolve()

    try:
        resolved.relative_to(data_dir)
    except ValueError:
        return None
    return resolved


def _needs_ffmpeg_conversion(path: Path, mime_type: str | None) -> bool:
    """Return True when the audio format is not directly accepted by OpenAI."""
    suffix = path.suffix.lower()
    clean_mime = (mime_type or mimetypes.guess_type(path.name)[0] or "").lower()
    if suffix in OGG_AUDIO_SUFFIXES:
        return True
    if clean_mime.startswith("audio/ogg") or clean_mime.startswith("audio/opus"):
        return True
    return suffix not in SUPPORTED_TRANSCRIPTION_SUFFIXES


def _convert_audio_for_transcription(source_path: Path, target_dir: Path) -> Path:
    """Convert WhatsApp audio to a compact MP3 accepted by the transcription API."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise AudioTranscriptionError("ffmpeg is not installed for audio conversion")

    target_path = target_dir / f"{source_path.stem or 'audio'}-transcription.mp3"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-b:a",
        "64k",
        str(target_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not target_path.exists():
        error_text = " ".join((completed.stderr or completed.stdout or "").split())[:500]
        raise AudioTranscriptionError(f"ffmpeg could not convert audio: {error_text}")
    return target_path


def _transcription_source_path(path: Path, mime_type: str | None, temp_dir: Path) -> Path:
    """Return a file path that can be sent to the OpenAI transcription endpoint."""
    if _needs_ffmpeg_conversion(path, mime_type):
        return _convert_audio_for_transcription(path, temp_dir)
    return path


def transcribe_audio_media(media_path: str | None, *, mime_type: str | None = None) -> str:
    """Transcribe one persisted inbound WhatsApp audio file to plain text."""
    if not OPENAI_API_KEY:
        raise AudioTranscriptionError("OPENAI_API_KEY is not configured")

    source_path = resolve_audio_media_path(media_path)
    if source_path is None or not source_path.exists() or not source_path.is_file():
        raise AudioTranscriptionError("audio media file is not available")

    with tempfile.TemporaryDirectory(prefix="contadores-audio-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        upload_path = _transcription_source_path(source_path, mime_type, temp_dir)
        client = OpenAI(api_key=OPENAI_API_KEY)
        with upload_path.open("rb") as audio_file:
            response = client.audio.transcriptions.create(
                file=audio_file,
                model=AUDIO_TRANSCRIPTION_MODEL,
                prompt=AUDIO_TRANSCRIPTION_PROMPT,
                response_format="text",
            )

    if isinstance(response, str):
        transcript = response
    else:
        transcript = str(getattr(response, "text", "") or "")

    clean_transcript = " ".join(transcript.split()).strip()
    if not clean_transcript:
        raise AudioTranscriptionError("transcription returned empty text")
    logger.info("Transcribed inbound WhatsApp audio from %s.", media_path)
    return clean_transcript
