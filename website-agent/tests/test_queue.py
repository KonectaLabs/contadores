import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlmodel import SQLModel, create_engine

from backend import database, main
from backend.database import create_user, list_messages


def test_agent_server_interrupts_active_run_and_webhook_completes_messages(tmp_path, monkeypatch):
    database.engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(database.engine)
    user = create_user("María", "+54 9 11 2345 6789")
    create_run = AsyncMock(return_value={"run_id": "run"})
    monkeypatch.setattr(main, "client", SimpleNamespace(runs=SimpleNamespace(create=create_run)))

    first = asyncio.run(main.post_message(user.id, "Quiero una web para mi estudio", None))
    second = asyncio.run(main.post_message(user.id, "Y que sea verde", None))

    assert create_run.await_count == 2
    assert all(call.args == (user.id, "website-agent") for call in create_run.await_args_list)
    assert all(call.kwargs["multitask_strategy"] == "interrupt" for call in create_run.await_args_list)
    assert all(call.kwargs["if_not_exists"] == "create" for call in create_run.await_args_list)

    interrupted = main.AgentRunWebhook(status="interrupted", metadata={"message_id": first.id})
    completed = main.AgentRunWebhook(status="success", metadata={"message_id": second.id}, values={"structured_response": {"message": "Segunda respuesta"}})
    asyncio.run(main.agent_run_finished(interrupted, main.WEBHOOK_TOKEN))
    asyncio.run(main.agent_run_finished(completed, main.WEBHOOK_TOKEN))

    messages = list_messages(user.id)
    assert [message.status for message in messages if message.role == "user"] == ["read", "read"]
    assert [message.text for message in messages if message.role == "assistant"] == ["Segunda respuesta"]


def test_whatsapp_media_is_queued_and_replies_are_idempotent(tmp_path, monkeypatch):
    database.engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(database.engine)
    create_run = AsyncMock(return_value={"run_id": "run"})
    put_item = AsyncMock()
    monkeypatch.setattr(main, "client", SimpleNamespace(runs=SimpleNamespace(create=create_run), store=SimpleNamespace(put_item=put_item)))

    class Media:
        id = "media-1"
        filename = "estudio.jpg"
        mime_type = "image/jpeg"

        async def get_media_url(self):
            return "https://media.example/image"

    class FakeWhatsApp:
        async def stream_media(self, _url):
            yield b"image"

    incoming = SimpleNamespace(
        id="wamid.inbound.1",
        from_user=SimpleNamespace(wa_id="5491100000000", name="Martín"),
        media=Media(),
        type=SimpleNamespace(value="image"),
        text=None,
        caption="Este es mi estudio",
    )

    asyncio.run(main.handle_whatsapp_message(FakeWhatsApp(), incoming))
    asyncio.run(main.handle_whatsapp_message(FakeWhatsApp(), incoming))

    assert create_run.await_count == 1
    assert put_item.await_count == 1
    user = database.get_or_create_user("Martín", "5491100000000")
    inbound = list_messages(user.id)[0]
    send_message = AsyncMock(return_value=SimpleNamespace(id="wamid.outbound.1"))
    monkeypatch.setattr(main, "whatsapp", SimpleNamespace(send_message=send_message))
    run = main.AgentRunWebhook(status="success", metadata={"message_id": inbound.id}, values={"structured_response": {"message": "Respuesta"}})

    asyncio.run(main.agent_run_finished(run, main.WEBHOOK_TOKEN))
    asyncio.run(main.agent_run_finished(run, main.WEBHOOK_TOKEN))

    assert send_message.await_count == 1
    assert [message.text for message in list_messages(user.id) if message.role == "assistant"] == ["Respuesta"]
