from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "app_conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "app_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("app_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(24), default="done")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "app_jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(24), index=True)
    objective: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("app_conversations.id"), nullable=True
    )
    message_id: Mapped[str | None] = mapped_column(ForeignKey("app_messages.id"), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "app_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("app_jobs.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class Document(Base):
    __tablename__ = "app_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str] = mapped_column(ForeignKey("app_jobs.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def connect(url):
    engine = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def serialize(row):
    return {
        c.name: (
            value.isoformat() if isinstance(value := getattr(row, c.name), datetime) else value
        )
        for c in row.__table__.columns
    }
