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
    from .providers import WhatsAppInboundEvent, WhatsAppMessageStatusEvent
except ImportError:
    from providers import WhatsAppInboundEvent, WhatsAppMessageStatusEvent


DEFAULT_INBOX_PATH = "/app/data/bot-webhook-inbox.sqlite"
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 120
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RETRY_BASE_SECONDS = 30
DEFAULT_RETRY_MAX_SECONDS = 900
DEFAULT_DELIVERED_RETENTION_DAYS = 7
DEFAULT_TERMINAL_RETENTION_DAYS = 30
DEFAULT_STATUS_MAX_ATTEMPTS = 20
DEFAULT_STATUS_UNKNOWN_MAX_AGE_SECONDS = 600


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


@dataclass(frozen=True)
class SavedWhatsAppStatusEvent:
    """One saved WhatsApp status callback waiting for backend delivery."""

    event_key: str
    payload: dict[str, Any]
    status: str
    attempts: int

    def to_event(self) -> WhatsAppMessageStatusEvent:
        """Return the typed WhatsApp status event."""
        return WhatsAppMessageStatusEvent.model_validate(self.payload)


class WhatsAppInboundInbox:
    """Small SQLite-backed inbox for inbound WhatsApp webhooks."""

    def __init__(
        self,
        path: str | Path,
        *,
        processing_timeout_seconds: int = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
        retry_max_seconds: int = DEFAULT_RETRY_MAX_SECONDS,
        delivered_retention_days: int = DEFAULT_DELIVERED_RETENTION_DAYS,
        terminal_retention_days: int = DEFAULT_TERMINAL_RETENTION_DAYS,
    ) -> None:
        self.path = Path(path)
        self.processing_timeout_seconds = max(30, int(processing_timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(1, int(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, int(retry_max_seconds))
        self.delivered_retention_days = max(1, int(delivered_retention_days))
        self.terminal_retention_days = max(1, int(terminal_retention_days))
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
        max_attempts = int(
            (os.getenv("BOT_WEBHOOK_INBOX_MAX_ATTEMPTS", "") or "").strip()
            or DEFAULT_MAX_ATTEMPTS
        )
        retry_base_seconds = int(
            (os.getenv("BOT_WEBHOOK_INBOX_RETRY_BASE_SECONDS", "") or "").strip()
            or DEFAULT_RETRY_BASE_SECONDS
        )
        retry_max_seconds = int(
            (os.getenv("BOT_WEBHOOK_INBOX_RETRY_MAX_SECONDS", "") or "").strip()
            or DEFAULT_RETRY_MAX_SECONDS
        )
        delivered_retention_days = int(
            (os.getenv("BOT_WEBHOOK_INBOX_DELIVERED_RETENTION_DAYS", "") or "").strip()
            or DEFAULT_DELIVERED_RETENTION_DAYS
        )
        terminal_retention_days = int(
            (os.getenv("BOT_WEBHOOK_INBOX_TERMINAL_RETENTION_DAYS", "") or "").strip()
            or DEFAULT_TERMINAL_RETENTION_DAYS
        )
        return cls(
            path,
            processing_timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            delivered_retention_days=delivered_retention_days,
            terminal_retention_days=terminal_retention_days,
        )

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
                    next_attempt_at TEXT,
                    dead_lettered_at TEXT,
                    delivered_at TEXT
                )
                """
            )
            self._ensure_columns(
                connection,
                "whatsapp_inbound_events",
                {
                    "next_attempt_at": "TEXT",
                    "dead_lettered_at": "TEXT",
                },
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_events_status_updated
                ON whatsapp_inbound_events(status, updated_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_whatsapp_inbound_events_next_attempt
                ON whatsapp_inbound_events(status, next_attempt_at)
                """
            )

    @staticmethod
    def _ensure_columns(
        connection: sqlite3.Connection,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        """Add missing SQLite columns to an existing inbox table."""
        existing = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

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
        now_iso = now.isoformat()
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_inbound_events
                SET status = 'processing', updated_at = ?
                WHERE event_key = ?
                  AND (
                    status = 'pending'
                    OR (
                      status = 'failed'
                      AND attempts < ?
                      AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    )
                    OR (status = 'processing' AND updated_at <= ?)
                  )
                """,
                (now_iso, event_key, self.max_attempts, now_iso, stale_before),
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
        now = datetime.now(timezone.utc)
        clean_error = " ".join((error or "unknown error").split())[:1000]
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts FROM whatsapp_inbound_events WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            next_attempt = int(row["attempts"] if row else 0) + 1
            if next_attempt >= self.max_attempts:
                connection.execute(
                    """
                    UPDATE whatsapp_inbound_events
                    SET status = 'dead_letter',
                        attempts = ?,
                        last_error = ?,
                        updated_at = ?,
                        dead_lettered_at = ?,
                        next_attempt_at = NULL
                    WHERE event_key = ?
                    """,
                    (next_attempt, clean_error, now.isoformat(), now.isoformat(), event_key),
                )
                return
            retry_delay = min(
                self.retry_max_seconds,
                self.retry_base_seconds * (2 ** max(0, next_attempt - 1)),
            )
            next_retry_at = (now + timedelta(seconds=retry_delay)).isoformat()
            connection.execute(
                """
                UPDATE whatsapp_inbound_events
                SET status = 'failed',
                    attempts = ?,
                    last_error = ?,
                    updated_at = ?,
                    next_attempt_at = ?
                WHERE event_key = ?
                """,
                (next_attempt, clean_error, now.isoformat(), next_retry_at, event_key),
            )

    def list_retryable(self, *, limit: int = 50) -> list[SavedWhatsAppInboundEvent]:
        """List saved events that still need backend delivery."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, payload_json, status, attempts
                FROM whatsapp_inbound_events
                WHERE status = 'pending'
                   OR (
                     status = 'failed'
                     AND attempts < ?
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   )
                   OR (status = 'processing' AND updated_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (self.max_attempts, now_iso, stale_before, max(1, int(limit))),
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
        now = datetime.now(timezone.utc)
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM whatsapp_inbound_events
                WHERE status = 'pending'
                   OR status = 'failed'
                   OR (status = 'processing' AND updated_at <= ?)
                """,
                (stale_before,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def dead_letter_count(self) -> int:
        """Return the number of terminal failed inbound events."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM whatsapp_inbound_events WHERE status = 'dead_letter'"
            ).fetchone()
        return int(row["count"] if row else 0)

    def count_prunable(
        self,
        *,
        delivered_before: datetime | None = None,
        terminal_before: datetime | None = None,
    ) -> int:
        """Count rows whose raw payloads are past retention."""
        delivered_cutoff = delivered_before or (
            datetime.now(timezone.utc) - timedelta(days=self.delivered_retention_days)
        )
        terminal_cutoff = terminal_before or (
            datetime.now(timezone.utc) - timedelta(days=self.terminal_retention_days)
        )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM whatsapp_inbound_events
                WHERE (status = 'delivered' AND delivered_at IS NOT NULL AND delivered_at <= ?)
                   OR (status = 'dead_letter' AND dead_lettered_at IS NOT NULL AND dead_lettered_at <= ?)
                """,
                (delivered_cutoff.isoformat(), terminal_cutoff.isoformat()),
            ).fetchone()
        return int(row["count"] if row else 0)

    def prune_expired(
        self,
        *,
        delivered_before: datetime | None = None,
        terminal_before: datetime | None = None,
        dry_run: bool = False,
    ) -> int:
        """Delete delivered/terminal rows after retention; pending work is untouched."""
        delivered_cutoff = delivered_before or (
            datetime.now(timezone.utc) - timedelta(days=self.delivered_retention_days)
        )
        terminal_cutoff = terminal_before or (
            datetime.now(timezone.utc) - timedelta(days=self.terminal_retention_days)
        )
        if dry_run:
            return self.count_prunable(
                delivered_before=delivered_cutoff,
                terminal_before=terminal_cutoff,
            )
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM whatsapp_inbound_events
                WHERE (status = 'delivered' AND delivered_at IS NOT NULL AND delivered_at <= ?)
                   OR (status = 'dead_letter' AND dead_lettered_at IS NOT NULL AND dead_lettered_at <= ?)
                """,
                (delivered_cutoff.isoformat(), terminal_cutoff.isoformat()),
            )
            return int(cursor.rowcount or 0)


class WhatsAppStatusInbox:
    """Small SQLite-backed inbox for WhatsApp delivery-status callbacks."""

    def __init__(
        self,
        path: str | Path,
        *,
        processing_timeout_seconds: int = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_STATUS_MAX_ATTEMPTS,
        retry_base_seconds: int = DEFAULT_RETRY_BASE_SECONDS,
        retry_max_seconds: int = DEFAULT_RETRY_MAX_SECONDS,
        unknown_max_age_seconds: int = DEFAULT_STATUS_UNKNOWN_MAX_AGE_SECONDS,
    ) -> None:
        self.path = Path(path)
        self.processing_timeout_seconds = max(30, int(processing_timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(1, int(retry_base_seconds))
        self.retry_max_seconds = max(self.retry_base_seconds, int(retry_max_seconds))
        self.unknown_max_age_seconds = max(1, int(unknown_max_age_seconds))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @classmethod
    def from_env(cls) -> "WhatsAppStatusInbox":
        """Build the status inbox from environment configuration."""
        path = (os.getenv("BOT_WEBHOOK_INBOX_PATH", "") or "").strip() or DEFAULT_INBOX_PATH
        timeout_seconds = int(
            (os.getenv("BOT_WEBHOOK_INBOX_PROCESSING_TIMEOUT_SECONDS", "") or "").strip()
            or DEFAULT_PROCESSING_TIMEOUT_SECONDS
        )
        max_attempts = int(
            (os.getenv("BOT_STATUS_INBOX_MAX_ATTEMPTS", "") or "").strip()
            or DEFAULT_STATUS_MAX_ATTEMPTS
        )
        retry_base_seconds = int(
            (os.getenv("BOT_STATUS_INBOX_RETRY_BASE_SECONDS", "") or "").strip()
            or DEFAULT_RETRY_BASE_SECONDS
        )
        retry_max_seconds = int(
            (os.getenv("BOT_STATUS_INBOX_RETRY_MAX_SECONDS", "") or "").strip()
            or DEFAULT_RETRY_MAX_SECONDS
        )
        unknown_max_age_seconds = int(
            (os.getenv("BOT_STATUS_INBOX_UNKNOWN_MAX_AGE_SECONDS", "") or "").strip()
            or DEFAULT_STATUS_UNKNOWN_MAX_AGE_SECONDS
        )
        return cls(
            path,
            processing_timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
            unknown_max_age_seconds=unknown_max_age_seconds,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS whatsapp_status_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_attempt_at TEXT,
                    delivered_at TEXT,
                    dead_lettered_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_whatsapp_status_events_status_next
                ON whatsapp_status_events(status, next_attempt_at)
                """
            )

    @staticmethod
    def payload_for_event(event: WhatsAppMessageStatusEvent) -> dict[str, Any]:
        """Return the exact backend payload for one status callback."""
        return event.model_dump(exclude_none=True)

    @classmethod
    def event_key_for_payload(cls, payload: dict[str, Any]) -> str:
        """Return a stable dedupe key for one provider status callback."""
        stable_json = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(stable_json.encode("utf-8")).hexdigest()
        external_id = str(payload.get("external_id") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        prefix = f"whatsapp-status:{external_id}:{status}" if external_id and status else "whatsapp-status"
        return f"{prefix}:{digest}"

    def save_event(self, event: WhatsAppMessageStatusEvent) -> str:
        """Persist one status callback before backend processing starts."""
        payload = self.payload_for_event(event)
        event_key = self.event_key_for_payload(payload)
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO whatsapp_status_events (
                    event_key, payload_json, status, created_at, updated_at
                )
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (event_key, payload_json, now, now),
            )
        return event_key

    def reserve_event(self, event_key: str) -> bool:
        """Atomically reserve one pending status callback."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE whatsapp_status_events
                SET status = 'processing', updated_at = ?
                WHERE event_key = ?
                  AND (
                    status = 'pending'
                    OR (
                      status = 'failed'
                      AND attempts < ?
                      AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                    )
                    OR (status = 'processing' AND updated_at <= ?)
                  )
                """,
                (now_iso, event_key, self.max_attempts, now_iso, stale_before),
            )
            return cursor.rowcount > 0

    def mark_delivered(self, event_key: str) -> None:
        """Mark one status callback as applied to the backend."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE whatsapp_status_events
                SET status = 'delivered',
                    updated_at = ?,
                    delivered_at = ?,
                    last_error = NULL,
                    next_attempt_at = NULL
                WHERE event_key = ?
                """,
                (now, now, event_key),
            )

    def mark_failed(
        self,
        event_key: str,
        error: str,
        *,
        unknown_external_id: bool = False,
    ) -> None:
        """Mark one status callback for retry or terminal diagnostics."""
        now = datetime.now(timezone.utc)
        clean_error = " ".join((error or "unknown error").split())[:1000]
        with self._connect() as connection:
            row = connection.execute(
                "SELECT attempts, created_at FROM whatsapp_status_events WHERE event_key = ?",
                (event_key,),
            ).fetchone()
            attempts = int(row["attempts"] if row else 0)
            created_at = self._parse_datetime(str(row["created_at"])) if row else now
            next_attempt = attempts + 1
            too_old_unknown = unknown_external_id and (
                now - created_at
            ).total_seconds() >= self.unknown_max_age_seconds
            if next_attempt >= self.max_attempts or too_old_unknown:
                connection.execute(
                    """
                    UPDATE whatsapp_status_events
                    SET status = 'dead_letter',
                        attempts = ?,
                        last_error = ?,
                        updated_at = ?,
                        dead_lettered_at = ?,
                        next_attempt_at = NULL
                    WHERE event_key = ?
                    """,
                    (next_attempt, clean_error, now.isoformat(), now.isoformat(), event_key),
                )
                return
            retry_delay = min(
                self.retry_max_seconds,
                self.retry_base_seconds * (2 ** max(0, next_attempt - 1)),
            )
            next_retry_at = (now + timedelta(seconds=retry_delay)).isoformat()
            connection.execute(
                """
                UPDATE whatsapp_status_events
                SET status = 'failed',
                    attempts = ?,
                    last_error = ?,
                    updated_at = ?,
                    next_attempt_at = ?
                WHERE event_key = ?
                """,
                (next_attempt, clean_error, now.isoformat(), next_retry_at, event_key),
            )

    def list_retryable(self, *, limit: int = 50) -> list[SavedWhatsAppStatusEvent]:
        """List status callbacks due for replay."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        stale_before = (now - timedelta(seconds=self.processing_timeout_seconds)).isoformat()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_key, payload_json, status, attempts
                FROM whatsapp_status_events
                WHERE status = 'pending'
                   OR (
                     status = 'failed'
                     AND attempts < ?
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   )
                   OR (status = 'processing' AND updated_at <= ?)
                ORDER BY id
                LIMIT ?
                """,
                (self.max_attempts, now_iso, stale_before, max(1, int(limit))),
            ).fetchall()
        return [
            SavedWhatsAppStatusEvent(
                event_key=str(row["event_key"]),
                payload=json.loads(str(row["payload_json"])),
                status=str(row["status"]),
                attempts=int(row["attempts"]),
            )
            for row in rows
        ]

    def pending_count(self) -> int:
        """Return status callbacks that are not delivered or dead-lettered."""
        stale_before = (
            datetime.now(timezone.utc) - timedelta(seconds=self.processing_timeout_seconds)
        ).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM whatsapp_status_events
                WHERE status = 'pending'
                   OR status = 'failed'
                   OR (status = 'processing' AND updated_at <= ?)
                """,
                (stale_before,),
            ).fetchone()
        return int(row["count"] if row else 0)

    def dead_letter_count(self) -> int:
        """Return status callbacks that reached a terminal failure state."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM whatsapp_status_events WHERE status = 'dead_letter'"
            ).fetchone()
        return int(row["count"] if row else 0)

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        """Parse one stored UTC timestamp."""
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return datetime.now(timezone.utc)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
