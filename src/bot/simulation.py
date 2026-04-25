"""Simulated bot runtime: backend loop + DSPy generated inbound replies."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import dspy
import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

try:
    from .providers import DeliveryReceipt
    from .utils import (
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        backend_url,
        build_message_email_delay_key,
        build_backend_client,
        enforce_email_dispatch_spacing,
        fetch_pending_outbound,
        mark_backend_message_delivered,
        register_backend_inbound,
        resolve_backend_contact,
        wait_for_backend_ready,
    )
except ImportError:
    from providers import DeliveryReceipt
    from utils import (
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        backend_url,
        build_message_email_delay_key,
        build_backend_client,
        enforce_email_dispatch_spacing,
        fetch_pending_outbound,
        mark_backend_message_delivered,
        register_backend_inbound,
        resolve_backend_contact,
        wait_for_backend_ready,
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

SIMULATION_MAX_OUTBOUND_PER_CONTACT = max(
    1,
    int(os.getenv("SIMULATION_MAX_OUTBOUND_PER_CONTACT", "10")),
)
SIMULATION_MODEL = "openai/gpt-5-mini"
SIMULATION_SUPPORTED_CHANNELS = {"email", "whatsapp"}


class TranscriptMessage(BaseModel):
    """One persisted transcript row for simulation context."""

    from_me: bool
    text: str


class ContactMessagesResponse(BaseModel):
    """Contact transcript payload returned by backend."""

    company_id: str
    contact_id: str
    messages: list[TranscriptMessage] = Field(default_factory=list)


class SimulatedSellerReplyProgram(dspy.Module):
    """Generate simulated seller inbound replies from transcript context."""

    def __init__(self) -> None:
        super().__init__()
        self.lm = dspy.LM(
            SIMULATION_MODEL,
            temperature=1.0,
            max_tokens=16_384,
            reasoning_effort="low",
            verbosity="low",
            allowed_openai_params=["reasoning_effort", "verbosity"],
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        )

        class SimulatedSellerReplySignature(dspy.Signature):
            """Generate one short seller response for conversation simulation.

            <role>
            You are simulating the seller side of a commercial conversation.
            </role>

            <behavior>
            Reply naturally to the buyer's latest outbound message.
            Keep it concise and practical.
            Keep language consistent with the conversation.
            </behavior>

            <format>
            Return plain text only.
            Keep to 1-3 short sentences.
            </format>
            """

            channel: str = dspy.InputField(desc="email or whatsapp")
            conversation: str = dspy.InputField(desc="Full transcript with role tags")
            latest_outbound: str = dspy.InputField(desc="Latest buyer outbound message")
            reply: str = dspy.OutputField(desc="Seller's next inbound response")

        self.generator = dspy.ChainOfThought(SimulatedSellerReplySignature)

    def build_conversation(self, messages: list[TranscriptMessage]) -> str:
        """Build role-tagged transcript for the signature input."""
        return "\n".join(
            f"{'buyer' if row.from_me else 'seller'}: {row.text}"
            for row in messages
            if row.text.strip()
        )

    def normalize_reply(self, text: str) -> str:
        """Apply deterministic cleanup to generated reply text."""
        return text.strip()

    async def generate_reply(self, *, channel: str, conversation: str, latest_outbound: str) -> str:
        """Run DSPy signature and return generated reply text."""
        with dspy.context(lm=self.lm):
            prediction = await self.generator.acall(
                channel=channel,
                conversation=conversation,
                latest_outbound=latest_outbound,
            )
        return prediction.reply

    async def aforward(
        self,
        *,
        channel: str,
        messages: list[TranscriptMessage],
        latest_outbound: str,
    ) -> str:
        """Generate one simulated seller reply from transcript state."""
        conversation = self.build_conversation(messages)
        generated = await self.generate_reply(
            channel=channel,
            conversation=conversation,
            latest_outbound=latest_outbound,
        )
        return self.normalize_reply(generated)


def canonical_channel(raw_channel: str) -> str:
    """Normalize backend contact channel aliases."""
    value = (raw_channel or "").strip().lower()
    return "whatsapp" if value == "phone" else value


async def fetch_contact_messages(
    backend_client: httpx.AsyncClient,
    *,
    company_id: str,
    contact_id: str,
) -> ContactMessagesResponse:
    """Fetch full transcript for one contact."""
    response = await backend_client.get(
        backend_url(f"/api/companies/{company_id}/contacts/{contact_id}/messages")
    )
    response.raise_for_status()
    return ContactMessagesResponse.model_validate(response.json())


def count_outbound_messages(messages: list[TranscriptMessage]) -> int:
    """Count persisted outbound buyer messages in one transcript."""
    return len([row for row in messages if row.from_me])


def latest_outbound_text(messages: list[TranscriptMessage]) -> str:
    """Get latest outbound text from transcript."""
    for row in reversed(messages):
        if row.from_me and row.text.strip():
            return row.text.strip()
    return ""


def build_simulated_delivery_receipt(item) -> DeliveryReceipt:
    """Create deterministic fake delivery metadata for one pending message."""
    channel = canonical_channel(item.contact_type)
    if channel == "email":
        thread_id = (item.email_thread_id or "").strip() or f"sim-thread-{item.contact_id}"
        rfc_message_id = f"<sim-outbound-{item.message_id}@konecta-simulation.local>"
        return DeliveryReceipt(
            external_id=f"sim-email-{item.message_id}",
            thread_id=thread_id,
            rfc_message_id=rfc_message_id,
        )
    return DeliveryReceipt(external_id=f"sim-{channel}-{item.message_id}")


def build_simulated_inbound_external_id(message_id: int) -> str:
    """Create one deterministic-enough unique inbound external id."""
    return f"sim-inbound-{message_id}-{uuid.uuid4().hex[:10]}"


async def process_simulated_message(
    *,
    backend_client: httpx.AsyncClient,
    simulator: SimulatedSellerReplyProgram,
    item,
    blocked_contact_ids: set[str],
) -> dict[str, Any]:
    """Process one pending outbound message through simulated delivery + inbound."""
    channel = canonical_channel(item.contact_type)
    if channel not in SIMULATION_SUPPORTED_CHANNELS:
        return {
            "message_id": item.message_id,
            "contact_id": item.contact_id,
            "channel": channel,
            "status": "deferred",
            "reason": "unsupported_contact_type",
        }

    if item.contact_id in blocked_contact_ids:
        return {
            "message_id": item.message_id,
            "contact_id": item.contact_id,
            "channel": channel,
            "status": "ignored",
            "reason": "contact_limit_reached",
        }

    transcript = await fetch_contact_messages(
        backend_client,
        company_id=item.company_id,
        contact_id=item.contact_id,
    )
    outbound_count = count_outbound_messages(transcript.messages)
    if outbound_count > SIMULATION_MAX_OUTBOUND_PER_CONTACT:
        blocked_contact_ids.add(item.contact_id)
        return {
            "message_id": item.message_id,
            "contact_id": item.contact_id,
            "channel": channel,
            "status": "ignored",
            "reason": "contact_limit_reached",
            "outbound_count": outbound_count,
        }

    if channel == "email":
        if not await enforce_email_dispatch_spacing(
            delay_key=build_message_email_delay_key(item.message_id),
        ):
            return {
                "message_id": item.message_id,
                "contact_id": item.contact_id,
                "channel": channel,
                "status": "deferred",
                "reason": "email_delay_not_elapsed",
            }

    receipt = build_simulated_delivery_receipt(item)
    await mark_backend_message_delivered(
        backend_client,
        company_id=item.company_id,
        contact_id=item.contact_id,
        message_id=item.message_id,
        receipt=receipt,
    )

    outbound_text = latest_outbound_text(transcript.messages) or item.text.strip()
    simulated_reply = await simulator.aforward(
        channel=channel,
        messages=transcript.messages,
        latest_outbound=outbound_text,
    )

    resolved = await resolve_backend_contact(
        backend_client,
        channel=channel,
        value=item.contact_value,
        thread_id=receipt.thread_id if channel == "email" else None,
        in_reply_to=receipt.rfc_message_id if channel == "email" else None,
    )
    if not resolved:
        return {
            "message_id": item.message_id,
            "contact_id": item.contact_id,
            "channel": channel,
            "status": "failed",
            "reason": "contact_not_resolved_after_delivery",
        }

    inbound_external_id = build_simulated_inbound_external_id(item.message_id)
    inbound_thread_id = receipt.thread_id if channel == "email" else None
    inbound_in_reply_to = receipt.rfc_message_id if channel == "email" else None
    inbound_references = receipt.rfc_message_id if channel == "email" else None

    await register_backend_inbound(
        backend_client,
        resolved=resolved,
        message=simulated_reply,
        external_id=inbound_external_id,
        channel=channel,
        thread_id=inbound_thread_id,
        in_reply_to=inbound_in_reply_to,
        references=inbound_references,
    )

    return {
        "message_id": item.message_id,
        "contact_id": item.contact_id,
        "channel": channel,
        "status": "processed",
        "outbound_count": outbound_count,
    }


async def run_worker_iteration(
    *,
    backend_client: httpx.AsyncClient,
    simulator: SimulatedSellerReplyProgram,
    blocked_contact_ids: set[str],
) -> None:
    """Run one full simulated worker iteration."""
    pending = await fetch_pending_outbound(backend_client, limit=200)
    outcomes: list[dict[str, Any]] = []

    for item in pending:
        try:
            outcome = await process_simulated_message(
                backend_client=backend_client,
                simulator=simulator,
                item=item,
                blocked_contact_ids=blocked_contact_ids,
            )
        except Exception as exc:
            logger.exception(
                "Simulation failed for message_id=%s contact_id=%s",
                item.message_id,
                item.contact_id,
            )
            outcome = {
                "message_id": item.message_id,
                "contact_id": item.contact_id,
                "channel": canonical_channel(item.contact_type),
                "status": "failed",
                "reason": str(exc),
            }
        outcomes.append(outcome)

    processed = len([row for row in outcomes if row.get("status") == "processed"])
    ignored = len([row for row in outcomes if row.get("status") == "ignored"])
    failed = len([row for row in outcomes if row.get("status") == "failed"])
    deferred = len([row for row in outcomes if row.get("status") == "deferred"])
    logger.info(
        "Simulation iteration complete: pending=%s processed=%s ignored=%s failed=%s deferred=%s blocked_contacts=%s",
        len(pending),
        processed,
        ignored,
        failed,
        deferred,
        len(blocked_contact_ids),
    )


async def run_worker_loop(
    *,
    backend_client: httpx.AsyncClient,
    simulator: SimulatedSellerReplyProgram,
    blocked_contact_ids: set[str],
) -> None:
    """Run continuous simulation loop with per-tick fault isolation."""
    try:
        while True:
            try:
                await run_worker_iteration(
                    backend_client=backend_client,
                    simulator=simulator,
                    blocked_contact_ids=blocked_contact_ids,
                )
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else "unknown"
                request_url = str(exc.request.url) if exc.request else "unknown"
                logger.warning("Backend returned HTTP %s for %s", status_code, request_url)
            except httpx.RequestError as exc:
                logger.warning("Backend unavailable for simulation tick: %s", exc)
            except Exception:
                logger.exception("Simulation worker iteration failed")
            await asyncio.sleep(BOT_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("Simulation worker loop cancelled")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize backend client, simulation program, and worker loop."""
    logger.info("Starting Konecta simulation bot")

    backend_client = build_backend_client()
    backend_ready = await wait_for_backend_ready(
        backend_client,
        timeout_seconds=BACKEND_BOOT_TIMEOUT_SECONDS,
        poll_seconds=BACKEND_BOOT_POLL_SECONDS,
    )
    if backend_ready:
        logger.info("Backend is reachable")
    else:
        logger.warning(
            "Backend was not reachable after %ss; simulation worker will keep retrying",
            BACKEND_BOOT_TIMEOUT_SECONDS,
        )

    simulator = SimulatedSellerReplyProgram()
    blocked_contact_ids: set[str] = set()

    worker_task = asyncio.create_task(
        run_worker_loop(
            backend_client=backend_client,
            simulator=simulator,
            blocked_contact_ids=blocked_contact_ids,
        )
    )

    app.state.backend_client = backend_client
    app.state.simulator = simulator
    app.state.worker_task = worker_task

    try:
        yield
    finally:
        logger.info("Shutting down Konecta simulation bot")
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await backend_client.aclose()


app = FastAPI(
    title="Konecta Auditor Simulation Bot",
    description="FastAPI runtime + periodic worker loop with simulated inbound replies",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
