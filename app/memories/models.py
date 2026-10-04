"""Memory database models.

Contains the core data models for the us-two memory journal:
- Memory: A trip/event grouping
- MemoryDay: A day within a memory
- MemoryEntry: A photo or text entry within a day
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Memory(Base):
    """A memory (trip/event) belonging to a user."""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    place: Mapped[Optional[str]] = mapped_column(String(200))
    date_label: Mapped[Optional[str]] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(10), default="#C45B38")
    cover: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    days: Mapped[list["MemoryDay"]] = relationship(
        back_populates="memory", cascade="all, delete-orphan"
    )


class MemoryDay(Base):
    """A day within a memory."""

    __tablename__ = "memory_days"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"), index=True
    )
    day_date: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))

    memory: Mapped[Memory] = relationship(back_populates="days")
    entries: Mapped[list["MemoryEntry"]] = relationship(
        back_populates="day", cascade="all, delete-orphan"
    )


class MemoryEntry(Base):
    """A photo or text entry within a day."""

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    day_id: Mapped[str] = mapped_column(
        ForeignKey("memory_days.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(10))
    photo_url: Mapped[Optional[str]] = mapped_column(Text)
    photo_public_id: Mapped[Optional[str]] = mapped_column(Text)
    caption: Mapped[Optional[str]] = mapped_column(Text)
    body: Mapped[Optional[str]] = mapped_column(Text)
    color: Mapped[Optional[str]] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    day: Mapped[MemoryDay] = relationship(back_populates="entries")
