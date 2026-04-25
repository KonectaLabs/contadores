#!/usr/bin/env python3
"""Send one WhatsApp intro template, wait for inbound, and mirror it back."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI
from httpx import AsyncClient
from uvicorn import Config, Server

BOT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BOT_DIR.parent
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from providers import WhatsAppInboundEvent, WhatsAppProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "E2E WhatsApp check: send template to one number, "
            "wait for one inbound webhook event, mirror it back."
        )
    )
    parser.add_argument("--to", required=True, help="Target WhatsApp phone in E.164 format")
    parser.add_argument("--template-name", default="konecta_intro_es_v2")
    parser.add_argument("--template-language", default="es", help="es or en_US")
    parser.add_argument("--client-name", default="Mateo")
    parser.add_argument("--company-url", default="https://konectalabs.com")
    parser.add_argument("--echo-prefix", default="ECO: ")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--callback-url",
        default="",
        help="Override WA_CALLBACK_URL for this test run only",
    )
    parser.add_argument(
        "--use-ngrok",
        action="store_true",
        help="Create temporary ngrok tunnel and use it as callback URL",
    )
    parser.add_argument("--callback-path", default="/webhook/wa")
    parser.add_argument("--ngrok-bin", default="ngrok")
    parser.add_argument("--ngrok-api-url", default="http://127.0.0.1:4040/api/tunnels")
    parser.add_argument("--ngrok-start-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--server-start-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--log-level", default="info")
    return parser.parse_args()


async def wait_server_started(server: Server, timeout_seconds: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if getattr(server, "started", False):
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("Timed out waiting for local webhook server startup")


def normalize_callback_url(base_url: str, callback_path: str) -> str:
    parsed = urlparse(base_url)
    scheme = parsed.scheme or "https"
    if not parsed.netloc:
        raise ValueError(f"Invalid callback base URL: {base_url}")
    path = (callback_path or "/webhook/wa").strip() or "/webhook/wa"
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{scheme}://{parsed.netloc}{path.rstrip('/')}"


async def start_ngrok_tunnel(
    *,
    ngrok_bin: str,
    port: int,
    api_url: str,
    timeout_seconds: float,
) -> tuple[asyncio.subprocess.Process, str]:
    process = await asyncio.create_subprocess_exec(
        ngrok_bin,
        "http",
        str(port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    async with AsyncClient(timeout=2.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                output = ""
                if process.stdout is not None:
                    raw = await process.stdout.read()
                    output = raw.decode("utf-8", errors="ignore").strip()
                raise RuntimeError(f"ngrok exited early ({process.returncode}): {output}")
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                payload = response.json()
                tunnels = payload.get("tunnels") if isinstance(payload, dict) else None
                if not isinstance(tunnels, list):
                    await asyncio.sleep(0.5)
                    continue
                for tunnel in tunnels:
                    if not isinstance(tunnel, dict):
                        continue
                    public_url = str(tunnel.get("public_url", "")).strip()
                    if public_url.startswith("https://"):
                        return process, public_url
            except Exception:
                await asyncio.sleep(0.5)
                continue
            await asyncio.sleep(0.5)
    process.terminate()
    with suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=5.0)
    raise TimeoutError("Timed out waiting for ngrok public URL")


async def run(args: argparse.Namespace) -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logger = logging.getLogger("wa-template-echo-test")
    if args.use_ngrok and args.callback_url.strip():
        logger.error("Use either --callback-url or --use-ngrok, not both")
        return 2

    inbound_queue: asyncio.Queue[WhatsAppInboundEvent] = asyncio.Queue()
    ngrok_process: asyncio.subprocess.Process | None = None
    callback_url_override = args.callback_url.strip()
    if args.use_ngrok:
        ngrok_process, ngrok_public_url = await start_ngrok_tunnel(
            ngrok_bin=args.ngrok_bin,
            port=args.port,
            api_url=args.ngrok_api_url,
            timeout_seconds=args.ngrok_start_timeout_seconds,
        )
        callback_url_override = normalize_callback_url(ngrok_public_url, args.callback_path)
        logger.info("ngrok tunnel ready: %s", callback_url_override)
    elif callback_url_override:
        callback_url_override = normalize_callback_url(callback_url_override, args.callback_path)

    if callback_url_override:
        os.environ["WA_CALLBACK_URL"] = callback_url_override
        logger.info("Using callback URL override: %s", callback_url_override)

    async def on_inbound(event: WhatsAppInboundEvent) -> None:
        logger.info("Inbound webhook event: phone=%s external_id=%s text=%r", event.phone, event.external_id, event.text)
        await inbound_queue.put(event)

    app = FastAPI(title="WhatsApp template echo test")
    provider = WhatsAppProvider(app, on_inbound)
    if not provider.configured:
        logger.error(
            "WhatsApp provider is not configured/initialized. "
            "Check WA_* env vars and Meta app/token status."
        )
        return 2

    server = Server(
        Config(
            app=app,
            host=args.host,
            port=args.port,
            log_level=args.log_level.lower(),
            access_log=False,
        )
    )
    server_task = asyncio.create_task(server.serve())

    try:
        await wait_server_started(server, args.server_start_timeout_seconds)
        logger.info("Webhook server listening on http://%s:%s", args.host, args.port)

        template_receipt = await provider.send_intro_template(
            to=args.to,
            template_name=args.template_name,
            template_language=args.template_language,
            client_name=args.client_name,
            company_url=args.company_url,
        )
        logger.info(
            "Template sent: to=%s message_id=%s delivered_text=%r",
            args.to,
            template_receipt.external_id,
            template_receipt.delivered_text,
        )
        print(f"SENT_TEMPLATE:{template_receipt.external_id}")
        print(f"WAITING_INBOUND_FOR_SECONDS:{args.timeout_seconds}")

        inbound_event = await asyncio.wait_for(inbound_queue.get(), timeout=args.timeout_seconds)
        print(f"INBOUND_RECEIVED:{inbound_event.external_id or 'none'}:{inbound_event.text}")

        mirrored_text = f"{args.echo_prefix}{inbound_event.text}"
        echo_receipt = await provider.send_message(inbound_event.phone, mirrored_text)
        logger.info(
            "Mirror message sent: to=%s message_id=%s text=%r",
            inbound_event.phone,
            echo_receipt.external_id,
            mirrored_text,
        )
        print(f"SENT_ECHO:{echo_receipt.external_id}:{mirrored_text}")
        return 0
    except TimeoutError:
        logger.error(
            "No inbound webhook received within %ss. "
            "If template was delivered, check WA_CALLBACK_URL routing to this running script.",
            args.timeout_seconds,
        )
        print("TIMEOUT_WAITING_INBOUND")
        return 3
    finally:
        server.should_exit = True
        await provider.close()
        with suppress(Exception):
            await asyncio.wait_for(server_task, timeout=10.0)
        if ngrok_process is not None and ngrok_process.returncode is None:
            ngrok_process.terminate()
            with suppress(Exception):
                await asyncio.wait_for(ngrok_process.wait(), timeout=5.0)


def main() -> int:
    args = parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
