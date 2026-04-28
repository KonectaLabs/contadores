"""Runtime logging helpers for the stateless bot."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any

WAITING_LOG_INTERVAL_SECONDS = 60.0


class ErrorOnlyAccessFilter(logging.Filter):
    """Keep only failing HTTP access logs from Uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) < 5:
            return True
        try:
            return int(args[4]) >= 400
        except (TypeError, ValueError):
            return True


@dataclass
class BotLogState:
    """Track repetitive bot log state so the console stays quiet."""

    last_waiting_fingerprint: tuple[Any, ...] | None = None
    last_waiting_logged_at: float = 0.0
    backend_issue_active: bool = False
    last_backend_issue: str | None = None


def configure_runtime_logging() -> logging.Logger:
    """Configure concise runtime logging for operators."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    for logger_name in [
        "httpx",
        "httpcore",
        "urllib3",
        "agentmail",
        "svix",
        "openai",
    ]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(current, ErrorOnlyAccessFilter) for current in access_logger.filters):
        access_logger.addFilter(ErrorOnlyAccessFilter())

    return logging.getLogger(__name__)


def note_backend_issue(logger: logging.Logger, state: BotLogState, message: str) -> None:
    """Log backend problems only when the situation changes."""
    if state.backend_issue_active and state.last_backend_issue == message:
        return
    state.backend_issue_active = True
    state.last_backend_issue = message
    logger.warning("⚠️ %s", message)


def note_backend_recovered(logger: logging.Logger, state: BotLogState) -> None:
    """Log backend recovery once after an outage."""
    if not state.backend_issue_active:
        return
    state.backend_issue_active = False
    state.last_backend_issue = None
    logger.info("✅ Backend connection restored.")


def log_dispatch_activity(logger: logging.Logger, results: list[Any], state: BotLogState) -> None:
    """Log only meaningful outbound queue activity."""
    if not results:
        state.last_waiting_fingerprint = None
        state.last_waiting_logged_at = 0.0
        return

    email_sent = sum(1 for item in results if item.status in {"sent", "delivered"} and item.channel == "email")
    whatsapp_sent = sum(1 for item in results if item.status == "delivered" and item.channel in {"whatsapp", "phone"})
    failed = [item for item in results if item.status == "failed"]

    if email_sent:
        logger.info("📧 Sent %s. Delivery confirmation will arrive by webhook.", _count_phrase(email_sent, "email"))
    if whatsapp_sent:
        logger.info(
            "📲 Sent %s. Delivery confirmation will arrive later.",
            _count_phrase(whatsapp_sent, "WhatsApp message"),
        )

    for item in failed:
        logger.error(
            "❌ Could not send %s to %s: %s",
            _channel_label(item.channel).lower(),
            _target_label(item),
            _humanize_error(item.error),
        )

    waiting_message, fingerprint = _build_waiting_message(results)
    if not waiting_message:
        state.last_waiting_fingerprint = None
        state.last_waiting_logged_at = 0.0
        return

    now = monotonic()
    if fingerprint == state.last_waiting_fingerprint and (now - state.last_waiting_logged_at) < WAITING_LOG_INTERVAL_SECONDS:
        return

    state.last_waiting_fingerprint = fingerprint
    state.last_waiting_logged_at = now
    logger.info(waiting_message)


def log_whatsapp_inbound_activity(logger: logging.Logger, result: dict[str, Any]) -> None:
    """Log one inbound WhatsApp outcome in plain language."""
    status = str(result.get("status", "")).strip().lower()
    referral = result.get("referral") if isinstance(result.get("referral"), dict) else {}
    if status == "processed":
        if referral:
            logger.info(
                "📥 Saved a WhatsApp reply to the conversation (route=%s phone=%s profile_name=%s referral_source_id=%s ctwa_clid=%s).",
                result.get("route") or "-",
                result.get("phone") or "-",
                result.get("profile_name") or "-",
                referral.get("source_id") or "-",
                referral.get("ctwa_clid") or "-",
            )
            return
        logger.info(
            "📥 Saved a WhatsApp reply to the conversation (phone=%s profile_name=%s).",
            result.get("phone") or "-",
            result.get("profile_name") or "-",
        )
        return
    if status == "ignored":
        logger.warning(
            "⚠️ Ignored a WhatsApp reply (reason=%s route=%s phone=%s external_id=%s in_reply_to=%s "
            "referral_source_type=%s referral_source_id=%s ctwa_clid=%s headline=%r).",
            result.get("reason") or "unknown",
            result.get("route") or "-",
            result.get("phone") or "-",
            result.get("external_id") or "-",
            result.get("in_reply_to") or "-",
            referral.get("source_type") or "-",
            referral.get("source_id") or "-",
            referral.get("ctwa_clid") or "-",
            referral.get("headline") or "",
        )
        return
    logger.info("📥 Processed a WhatsApp webhook update.")


def log_whatsapp_status_activity(logger: logging.Logger, result: dict[str, Any]) -> None:
    """Log one outbound WhatsApp delivery update."""
    delivery_status = str(result.get("delivery_status") or result.get("status") or "").strip().lower()
    provider_status = str(result.get("provider_status") or "").strip().lower()
    effective_status = "read" if provider_status == "read" else delivery_status
    message_id = result.get("id")
    message_label = f"message #{message_id}" if message_id else "WhatsApp message"

    if delivery_status == "ignored":
        logger.debug(
            "Ignored WhatsApp delivery update for external_id=%s reason=%s",
            result.get("external_id"),
            result.get("reason"),
        )
        return
    if effective_status == "delivered":
        logger.info("✅ %s was delivered.", message_label)
        return
    if effective_status == "failed":
        logger.error("❌ %s failed to deliver.", message_label)
        return
    if effective_status:
        logger.info("📲 %s status changed to %s.", message_label, effective_status)
        return
    logger.info("📲 Received a WhatsApp delivery update.")


def _build_waiting_message(results: list[Any]) -> tuple[str | None, tuple[Any, ...] | None]:
    delayed_by_channel: dict[str, list[float]] = {}
    paused_reasons: Counter[str] = Counter()

    for item in results:
        if item.status != "deferred":
            continue
        error = str(item.error or "").strip()
        if error in {"email_delay_not_elapsed", "whatsapp_delay_not_elapsed"}:
            delayed_by_channel.setdefault(_channel_group(item.channel), []).append(float(item.wait_seconds or 0.0))
            continue
        paused_reasons[_humanize_pause_reason(error, item.channel)] += 1

    total_waiting = sum(len(values) for values in delayed_by_channel.values()) + sum(paused_reasons.values())
    if total_waiting == 0:
        return None, None

    parts: list[str] = []
    fingerprint_parts: list[Any] = []

    if delayed_by_channel:
        delayed_parts: list[str] = []
        for channel in _ordered_channels(delayed_by_channel):
            waits = delayed_by_channel[channel]
            count = len(waits)
            soonest_wait = min(waits)
            delayed_parts.append(
                f"{_count_phrase(count, _channel_label(channel))} (next in {_format_wait(soonest_wait)})"
            )
            fingerprint_parts.append(("delay", channel, count, _wait_bucket(soonest_wait)))
        parts.append("waiting for send time: " + ", ".join(delayed_parts))

    if paused_reasons:
        paused_parts: list[str] = []
        for reason, count in sorted(paused_reasons.items()):
            paused_parts.append(f"{reason} ({count})")
            fingerprint_parts.append(("pause", reason, count))
        parts.append("paused: " + ", ".join(paused_parts))

    verb = "is" if total_waiting == 1 else "are"
    prefix = "⚠️" if paused_reasons and not delayed_by_channel else "⏳"
    return (
        f"{prefix} {_count_phrase(total_waiting, 'outgoing message')} {verb} not sent yet: {'; '.join(parts)}.",
        tuple(fingerprint_parts),
    )


def _ordered_channels(delayed_by_channel: dict[str, list[float]]) -> list[str]:
    order = {"email": 0, "whatsapp": 1}
    return sorted(delayed_by_channel, key=lambda value: (order.get(value, 99), value))


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def _channel_group(channel: Any) -> str:
    normalized = str(channel or "").strip().lower()
    if normalized in {"whatsapp", "phone"}:
        return "whatsapp"
    if normalized == "email":
        return "email"
    return normalized or "message"


def _channel_label(channel: Any) -> str:
    normalized = _channel_group(channel)
    if normalized == "email":
        return "email"
    if normalized == "whatsapp":
        return "WhatsApp message"
    return f"{normalized} message"


def _target_label(item: Any) -> str:
    value = str(getattr(item, "contact_value", "") or "").strip()
    if value:
        return value
    message_id = getattr(item, "message_id", None)
    if message_id is not None:
        return f"message #{message_id}"
    return "the recipient"


def _humanize_pause_reason(error: str, channel: Any) -> str:
    normalized = str(error or "").strip()
    if normalized == "email_provider_not_configured":
        return "email sending is not configured"
    if normalized == "whatsapp_provider_not_configured":
        return "WhatsApp sending is not configured"
    if normalized == "unsupported_contact_type":
        return f"unsupported channel {_channel_group(channel)}"
    return _humanize_error(normalized)


def _humanize_error(error: Any) -> str:
    clean = " ".join(str(error or "unknown error").split()).strip()
    if not clean:
        return "unknown error"
    clean = clean.replace("_", " ")
    return clean[:180]


def _format_wait(seconds: float) -> str:
    remaining = max(0, int(round(seconds)))
    if remaining < 60:
        return f"{remaining}s"
    minutes, seconds_part = divmod(remaining, 60)
    if minutes < 60:
        if seconds_part == 0:
            return f"{minutes}m"
        return f"{minutes}m {seconds_part}s"
    hours, minutes_part = divmod(minutes, 60)
    if minutes_part == 0:
        return f"{hours}h"
    return f"{hours}h {minutes_part}m"


def _wait_bucket(seconds: float) -> int:
    remaining = max(0, int(round(seconds)))
    if remaining < 60:
        return (remaining // 15) * 15
    if remaining < 3600:
        return (remaining // 60) * 60
    return (remaining // 300) * 300
