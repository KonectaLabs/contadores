"""Durable webhook inbox for WhatsApp inbound events."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from .providers import WhatsAppInboundEvent
except ImportError:
    from providers import WhatsAppInboundEvent


DEFAULT_INBOX_PATH = "/app/data/bot-webhook-inbox.sqlite"
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class SavedWhatsAppInboundEvent:
    """One saved inbound webhook waiting for backend delivery."""

    event_key: str
    payload: dict[str, Any]
    status: str
    attempts: int

    def to_event(self) -> WhatsAppInboundEvent:
        """Return the typed WhatsApp inbound event."""
        return WhatsAppInboundEvent.model_validate(self.payload)


class WhatsAppInboundInbox:
    """Small SQLite-backed inbox for inbound WhatsApp webhooks."""

    def __init__(
        self,
        path: str | Path,
        *,
        processing_timeout_seconds: int = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.processing_timeout_seconds = max(30, int(processing_timeout_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> "WhatsAppInboundInbox":
        """Build the inbox from environment configuration."""
        path = (os.getenv("BOT_WEBHOOK_INBOX_PATH", "") or "").strip() or DEFAULT_INBOX_PATH
        timeout_seconds = int(
            (os.getenv("BOT_WEBHOOK_INBOX_PROCESSING_TIMEOUT_SECONDS", "") or "").strip()
            or DEFAULT_PROCESSING_TIMEOUT_SECONDS
        )
        return cls(path, processing_timeout_seconds=timeout_seconds)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp_inbound_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_events_status_updated
                ON whatsapp_inbound_events(status, updated_at)
                """
            )

    @staticmethod
    def payload_for_event(event: WhatsAppInboundEvent) -> dict[str, Any]:
        """Return the exact backend payload for one inbound event."""
        return {
            "phone": event.phone,
            "text": event.text,
            "profile_name": event.profile_name,
            "external_id": event.external_id,
            "in_reply_to": event.in_reply_to,
            "referral": event.referral.model_dump(exclude_none=True) if event.referral else None,
            "media_type": event.media_type,
            "media_path": event.media_path,
            "media_caption": event.media_caption,
            "media_mime_type": event.media_mime_type,
            "media_filename": event.media_filename,
            "media_sha256": event.media_sha256,
            "media_id": event.media_id,
        }

    @classmethod
    def event_key_for_payload(cls, payload: dict[str, Any]) -> str:
        """Return a stable dedupe key for one provider event."""
        external_id = str(payload.get("external_id") or "").strip()
        if external_id:
            return f"whatsapp:external:{external_id}"
        stable_json = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(stable_json.encode("utf-8")).hexdigest()
        return f"whatsapp:fingerprint:{digest}"

    @classmethod
    def event_key_for_event(cls, event: WhatsAppInboundEvent) -> str:
        """Return a stable dedupe key for one typed event."""
        return cls.event_key_for_payload(cls.payload_for_event(event))

    def save_event(self, event: WhatsAppInboundEvent) -> str:
        """Persist one inbound event before any backend work starts."""
        payload = self.payload_for_event(event)
        event_key = self.event_key_for_payload(payload)
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO whatsapp_inbound_events (
                    event_key, payload_json, status, created_at, updated_at
                )
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (event_key, payload_json, now, now),
            )
        return event_key

    def reserve_event(self, event_key: str) -> bool:
        """Atomically reserve one pending event for delivery."""
        now = datetime.now(timezone.utc)
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_events
                SET status = 'processing', updated_at = ?
                WHERE event_key = ?
                  AND (
                    status IN ('pending', 'failed')
                    OR (status = 'processing' AND updated_at <= ?)
                  )
                """,
                (now.isoformat(), event_key, stale_before),
            )
            return cursor.rowcount > 0

    def mark_delivered(self, event_key: str) -> None:
        """Mark one event as safely delivered to the backend."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE whatsapp_inbound_events
                SET status = 'delivered', updated_at = ?, delivered_at = ?, last_error = NULL
                WHERE event_key = ?
                """,
                (now, now, event_key),
            )

    def mark_failed(self, event_key: str, error: str) -> None:
        """Mark one event for retry after a delivery failure."""
        now = datetime.now(timezone.utc).isoformat()
        clean_error = " ".join((error or "unknown error").split())[:1000]
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE whatsapp_inbound_events
                SET status = 'failed',
                    attempts = attempts + 1,
                    last_error = ?,
                    updated_at = ?
                WHERE event_key = ?
                """,
                (clean_error, now, event_key),
            )

    def list_retryable(self, *, limit: int = 50) -> list[SavedWhatsAppInboundEvent]:
        """List saved events that still need backend delivery."""
        now = datetime.now(timezone.utc)
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, payload_json, status, attempts
                FROM whatsapp_inbound_events
                WHERE status IN ('pending', 'failed')
                   OR (status = 'processing' AND updated_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (stale_before, max(1, int(limit))),
            ).fetchall()
        return [
            SavedWhatsAppInboundEvent(
                event_key=str(row["event_key"]),
                payload=json.loads(str(row["payload_json"])),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    def pending_count(self) -> int:
        """Return the number of events that are not delivered yet."""
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=self.processing_timeout_seconds)
        ).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM whatsapp_inbound_events
                WHERE status IN ('pending', 'failed')
                   OR (status = 'processing' AND updated_at <= ?)
                """,
                (stale_before,),
            ).fetchone()
        return int(row["count"] if row else 0)
