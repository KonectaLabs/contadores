import mimetypes
import os
from base64 import b64decode, b64encode
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from deepagents.backends.utils import create_file_data, file_data_to_string
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from httpx import AsyncClient, HTTPStatusError
from langgraph_sdk import get_client
from pydantic import BaseModel, Field
from pywa_async import WhatsApp, types

from backend.database import (
    Message,
    User,
    add_message,
    add_whatsapp_message,
    create_database,
    create_user,
    finish_message,
    get_or_create_user,
    get_user,
    get_whatsapp_message,
    get_whatsapp_message_for_message,
    list_messages,
    list_users,
    mark_whatsapp_reply_sent,
)

ROOT = Path(__file__).parent.parent
FRONTEND = ROOT / "frontend"
AGENT_SERVER_URL = os.getenv("AGENT_SERVER_URL", "http://agent-server:8000")
AGENT_RUNTIME_API_KEY = os.getenv("AGENT_RUNTIME_API_KEY") or None
WEBHOOK_TOKEN = os.getenv("RUN_WEBHOOK_TOKEN", "website-agent-local")
RUN_WEBHOOK_URL = f"http://app:8000/api/agent-runs?token={WEBHOOK_TOKEN}"
WA_PHONE_ID = os.getenv("WA_PHONE_ID", "")
WA_ACCESS_TOKEN = os.getenv("WA_ACCESS_TOKEN", "")
WA_APP_ID = os.getenv("WA_APP_ID", "")
WA_WABA_ID = os.getenv("WA_WABA_ID", "")
WA_APP_SECRET = os.getenv("WA_APP_SECRET", "")
WA_VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "")
WA_MEDIA_MAX_BYTES = 25 * 1024 * 1024
client = get_client(url=AGENT_SERVER_URL, api_key=AGENT_RUNTIME_API_KEY)
whatsapp_session: AsyncClient | None = None
whatsapp: WhatsApp | None = None


class CreateUser(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)


class AgentReply(BaseModel):
    message: str = Field(min_length=1)


class AgentRunWebhook(BaseModel):
    status: str
    metadata: dict[str, Any]
    values: dict[str, Any] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    create_database()
    yield
    if whatsapp_session:
        await whatsapp_session.aclose()


app = FastAPI(title="Website Agent", lifespan=lifespan)

if all((WA_PHONE_ID, WA_ACCESS_TOKEN, WA_APP_ID, WA_WABA_ID, WA_APP_SECRET, WA_VERIFY_TOKEN)):
    whatsapp_session = AsyncClient()
    whatsapp = WhatsApp(
        phone_id=WA_PHONE_ID,
        token=WA_ACCESS_TOKEN,
        app_id=int(WA_APP_ID),
        business_account_id=WA_WABA_ID,
        app_secret=WA_APP_SECRET,
        verify_token=WA_VERIFY_TOKEN,
        session=whatsapp_session,
        server=app,
        webhook_endpoint="/webhook/wa",
    )


def message_content(message: Message) -> str:
    attachments = "\n".join(f"- {item['name']} ({item['content_type']}): {item['path']}" for item in message.attachments)
    return "\n\n".join(part for part in (message.text, f"Archivos adjuntos:\n{attachments}" if attachments else "") if part) or "El usuario envió un archivo sin texto."


async def upload_user_file(user_id: str, path: str, content: bytes) -> None:
    try:
        value = create_file_data(content.decode())
    except UnicodeDecodeError:
        value = create_file_data(b64encode(content).decode(), encoding="base64")
    await client.store.put_item((user_id, "files"), path, value)


async def read_user_file(user_id: str, path: str) -> bytes:
    try:
        item = await client.store.get_item((user_id, "files"), path)
    except HTTPStatusError as error:
        if error.response.status_code == 404:
            raise FileNotFoundError(path) from error
        raise
    value = item["value"]
    content = file_data_to_string(value)
    return b64decode(content) if value.get("encoding") == "base64" else content.encode()


async def enqueue_agent_message(message: Message) -> Message:
    assert message.id is not None
    try:
        await client.runs.create(
            message.user_id,
            "website-agent",
            input={"messages": message_content(message)},
            context={"user_id": message.user_id},
            metadata={"user_id": message.user_id, "message_id": message.id},
            multitask_strategy="interrupt",
            if_not_exists="create",
            webhook=RUN_WEBHOOK_URL,
        )
    except Exception:
        finish_message(message.id, "failed")
        raise
    finish_message(message.id, "processing")
    message.status = "processing"
    return message


async def download_whatsapp_media(wa: WhatsApp, media: Any) -> bytes | None:
    content = bytearray()
    async for chunk in wa.stream_media(await media.get_media_url()):
        content.extend(chunk)
        if len(content) > WA_MEDIA_MAX_BYTES:
            return None
    return bytes(content)


async def handle_whatsapp_message(wa: WhatsApp, incoming: types.Message) -> None:
    external_id = str(incoming.id)
    existing = get_whatsapp_message(external_id)
    if existing:
        _, message = existing
        if message.status == "failed":
            await enqueue_agent_message(message)
        return

    phone = str(incoming.from_user.wa_id)
    user = get_or_create_user(incoming.from_user.name or phone, phone)
    media = incoming.media
    attachments = []
    if media:
        content = await download_whatsapp_media(wa, media)
        if content is not None:
            content_type = media.mime_type or "application/octet-stream"
            name = Path(getattr(media, "filename", "") or f"{media.id}{mimetypes.guess_extension(content_type) or ''}").name
            path = f"/uploads/{uuid4().hex}{Path(name).suffix.lower()}"
            await upload_user_file(user.id, path, content)
            attachments.append({"path": path, "name": name, "content_type": content_type})

    media_type = getattr(incoming.type, "value", str(incoming.type))
    text = (incoming.text or incoming.caption or "").strip() or f"[{media_type}]"
    message, created = add_whatsapp_message(user.id, text, attachments, external_id)
    if created:
        await enqueue_agent_message(message)


async def send_whatsapp_reply(message_id: int, text: str) -> None:
    record = get_whatsapp_message_for_message(message_id)
    if record is None or record[0].outbound_id:
        return
    assert whatsapp is not None, "WhatsApp is not configured"
    _, message = record
    user = get_user(message.user_id)
    assert user is not None
    sent = await whatsapp.send_message(to=user.phone, text=text)
    mark_whatsapp_reply_sent(message_id, sent.id)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "whatsapp": "configured" if whatsapp else "disabled"}


@app.get("/api/users", response_model=list[User])
async def get_users() -> list[User]:
    return list_users()


@app.post("/api/users", response_model=User)
async def post_user(command: CreateUser) -> User:
    return create_user(command.name.strip(), command.phone.strip())


@app.get("/api/users/{user_id}/messages", response_model=list[Message])
async def get_messages(user_id: str) -> list[Message]:
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return list_messages(user_id)


@app.post("/api/users/{user_id}/messages", response_model=Message)
async def post_message(
    user_id: str,
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> Message:
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    uploads = files or []
    if not text.strip() and not uploads:
        raise HTTPException(status_code=422, detail="Send text or at least one file")

    attachments = []
    for upload in uploads:
        name = Path(upload.filename or "file").name
        path = f"/uploads/{uuid4().hex}{Path(name).suffix.lower()}"
        content = await upload.read()
        if not content:
            raise HTTPException(status_code=422, detail=f"{name} is empty")
        await upload_user_file(user_id, path, content)
        attachments.append({"path": path, "name": name, "content_type": upload.content_type or "application/octet-stream"})

    message = add_message(user_id, "user", text.strip(), attachments, "queued")
    return await enqueue_agent_message(message)


@app.post("/api/agent-runs")
async def agent_run_finished(run: AgentRunWebhook, token: str) -> dict[str, str]:
    if token != WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    message_id = int(run.metadata["message_id"])
    if run.status == "success":
        assert run.values is not None
        reply = AgentReply.model_validate(run.values["structured_response"])
        await send_whatsapp_reply(message_id, reply.message)
        finish_message(message_id, "read", reply.message)
    elif run.status == "interrupted":
        finish_message(message_id, "read")
    else:
        finish_message(message_id, "failed")
    return {"status": "ok"}


@app.get("/api/users/{user_id}/files/{file_path:path}")
async def get_file(user_id: str, file_path: str) -> Response:
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        content = await read_user_file(user_id, f"/{file_path}")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="File not found") from error
    return Response(content, media_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream")


@app.get("/preview/{user_id}/{file_path:path}")
@app.get("/preview/{user_id}/")
async def preview(user_id: str, file_path: str = "index.html") -> Response:
    if get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        content = await read_user_file(user_id, f"/website/{file_path}")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Website not published") from error
    return Response(content, media_type=mimetypes.guess_type(file_path)[0] or "text/html")


if whatsapp:
    @whatsapp.on_message()
    async def whatsapp_message(wa: WhatsApp, message: types.Message) -> None:
        await handle_whatsapp_message(wa, message)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
