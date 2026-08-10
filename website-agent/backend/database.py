from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, Session, SQLModel, create_engine, select

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
engine = create_engine(f"sqlite:///{DATA / 'website-agent.sqlite'}", connect_args={"check_same_thread": False})


class User(SQLModel, table=True):
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    name: str
    phone: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Message(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    role: str
    text: str = ""
    attachments: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = Field(index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)


class WhatsAppMessage(SQLModel, table=True):
    external_id: str = Field(primary_key=True)
    message_id: int = Field(foreign_key="message.id", unique=True, index=True)
    outbound_id: str | None = None


def create_database() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def create_user(name: str, phone: str) -> User:
    with Session(engine) as session:
        user = User(name=name, phone=phone)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user


def get_user(user_id: str) -> User | None:
    with Session(engine) as session:
        return session.get(User, user_id)


def get_or_create_user(name: str, phone: str) -> User:
    with Session(engine) as session:
        user = session.exec(select(User).where(User.phone == phone)).first()
        if user is None:
            user = User(name=name, phone=phone)
            session.add(user)
            session.commit()
            session.refresh(user)
        return user


def list_users() -> list[User]:
    with Session(engine) as session:
        return list(session.exec(select(User).order_by(User.created_at.desc())))


def add_message(user_id: str, role: str, text: str, attachments: list[dict[str, str]], status: str) -> Message:
    with Session(engine) as session:
        message = Message(user_id=user_id, role=role, text=text, attachments=attachments, status=status)
        session.add(message)
        session.commit()
        session.refresh(message)
        return message


def add_whatsapp_message(user_id: str, text: str, attachments: list[dict[str, str]], external_id: str) -> tuple[Message, bool]:
    with Session(engine) as session:
        existing = session.get(WhatsAppMessage, external_id)
        if existing:
            message = session.get(Message, existing.message_id)
            assert message is not None
            return message, False
        message = Message(user_id=user_id, role="user", text=text, attachments=attachments, status="queued")
        session.add(message)
        session.flush()
        assert message.id is not None
        session.add(WhatsAppMessage(external_id=external_id, message_id=message.id))
        session.commit()
        session.refresh(message)
        return message, True


def get_whatsapp_message(external_id: str) -> tuple[WhatsAppMessage, Message] | None:
    with Session(engine) as session:
        whatsapp_message = session.get(WhatsAppMessage, external_id)
        if whatsapp_message is None:
            return None
        message = session.get(Message, whatsapp_message.message_id)
        assert message is not None
        return whatsapp_message, message


def get_whatsapp_message_for_message(message_id: int) -> tuple[WhatsAppMessage, Message] | None:
    with Session(engine) as session:
        whatsapp_message = session.exec(select(WhatsAppMessage).where(WhatsAppMessage.message_id == message_id)).first()
        if whatsapp_message is None:
            return None
        message = session.get(Message, message_id)
        assert message is not None
        return whatsapp_message, message


def mark_whatsapp_reply_sent(message_id: int, outbound_id: str) -> None:
    with Session(engine) as session:
        whatsapp_message = session.exec(select(WhatsAppMessage).where(WhatsAppMessage.message_id == message_id)).one()
        whatsapp_message.outbound_id = outbound_id
        session.add(whatsapp_message)
        session.commit()


def list_messages(user_id: str) -> list[Message]:
    with Session(engine) as session:
        return list(session.exec(select(Message).where(Message.user_id == user_id).order_by(Message.created_at, Message.id)))


def finish_message(message_id: int, status: str, reply: str | None = None) -> None:
    with Session(engine) as session:
        message = session.get(Message, message_id)
        assert message is not None
        if message.status == "read":
            return
        message.status = status
        session.add(message)
        if reply is not None:
            session.add(Message(user_id=message.user_id, role="assistant", text=reply, status="sent"))
        session.commit()
