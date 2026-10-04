"""Memories module route handlers.

Handles CRUD operations for memories, days, and entries.
"""

import os
from datetime import datetime, timezone

import cloudinary
import cloudinary.utils
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import settings
from app.connect.models import PartnerConnection
from app.dependencies import get_current_user, get_db
from app.memories.models import Memory, MemoryDay, MemoryEntry
from app.memories.schemas import BulkEntriesIn, DayIn, EntryIn, MemoryIn

router = APIRouter(prefix="/api", tags=["Memories"])


def dump_entry(entry: MemoryEntry) -> dict:
    """Serialize a memory entry."""
    return {
        "id": entry.id,
        "type": entry.type,
        "url": entry.photo_url,
        "publicId": entry.photo_public_id,
        "caption": entry.caption,
        "text": entry.body,
        "color": entry.color,
    }


def dump_memory(memory: Memory) -> dict:
    """Serialize a memory with all its days and entries."""
    return {
        "id": memory.id,
        "title": memory.title,
        "place": memory.place,
        "dates": memory.date_label,
        "color": memory.color,
        "cover": memory.cover,
        "days": [
            {
                "id": day.id,
                "date": day.day_date,
                "label": day.title,
                "entries": [
                    dump_entry(e)
                    for e in sorted(day.entries, key=lambda x: x.created_at)
                ],
            }
            for day in sorted(memory.days, key=lambda x: x.day_date)
        ],
    }


@router.get("/memories")
def list_memories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all memories for the current user and their connected partner."""
    # Find connected partner (if any)
    accepted = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.status == "accepted",
            or_(
                PartnerConnection.requester_id == user.id,
                PartnerConnection.partner_id == user.id,
            ),
        )
    )
    user_ids = [user.id]
    if accepted:
        other_id = (
            accepted.partner_id
            if accepted.requester_id == user.id
            else accepted.requester_id
        )
        if other_id:
            user_ids.append(other_id)

    memories = db.scalars(
        select(Memory)
        .where(Memory.user_id.in_(user_ids))
        .order_by(Memory.created_at.desc())
    ).unique()
    return [dump_memory(m) for m in memories]


@router.post("/memories", status_code=201)
def create_memory(
    payload: MemoryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new memory."""
    memory = Memory(user_id=user.id, **payload.model_dump())
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return dump_memory(memory)


@router.post("/memories/{memory_id}/days", status_code=201)
def create_day(
    memory_id: str,
    payload: DayIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a day to a memory."""
    memory = db.scalar(
        select(Memory).where(Memory.id == memory_id, Memory.user_id == user.id)
    )
    if not memory:
        raise HTTPException(404, "Memory not found.")
    day = MemoryDay(memory_id=memory.id, **payload.model_dump())
    db.add(day)
    db.commit()
    db.refresh(day)
    return {"id": day.id, "date": day.day_date, "label": day.title, "entries": []}


@router.post("/days/{day_id}/entries", status_code=201)
def create_entry(
    day_id: str,
    payload: EntryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an entry to a day."""
    day = db.scalar(
        select(MemoryDay)
        .join(Memory)
        .where(MemoryDay.id == day_id, Memory.user_id == user.id)
    )
    if not day:
        raise HTTPException(404, "Day not found.")
    entry = MemoryEntry(day_id=day.id, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return dump_entry(entry)


@router.post("/days/{day_id}/entries/bulk", status_code=201)
def create_entries_bulk(
    day_id: str,
    payload: BulkEntriesIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add multiple entries to a day in a single batch transaction."""
    day = db.scalar(
        select(MemoryDay)
        .join(Memory)
        .where(MemoryDay.id == day_id, Memory.user_id == user.id)
    )
    if not day:
        raise HTTPException(404, "Day not found.")

    new_entries = [
        MemoryEntry(day_id=day.id, **entry_data.model_dump())
        for entry_data in payload.entries
    ]
    db.add_all(new_entries)
    db.commit()
    for e in new_entries:
        db.refresh(e)

    return [dump_entry(e) for e in new_entries]


@router.get("/uploads/signature")
def cloudinary_signature(user: User = Depends(get_current_user)):
    """Generate a Cloudinary upload signature."""
    cloud_name = settings.CLOUDINARY_CLOUD_NAME or os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = settings.CLOUDINARY_API_KEY or os.getenv("CLOUDINARY_API_KEY")
    api_secret = settings.CLOUDINARY_API_SECRET or os.getenv("CLOUDINARY_API_SECRET")

    if not all([cloud_name, api_key, api_secret]):
        raise HTTPException(503, "Cloudinary is not configured on the backend.")

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    timestamp = int(datetime.now(timezone.utc).timestamp())
    params = {"timestamp": timestamp, "folder": f"us-two/{user.id}"}
    return {
        "timestamp": timestamp,
        "folder": f"us-two/{user.id}",
        "signature": cloudinary.utils.api_sign_request(params, api_secret),
        "api_key": api_key,
        "cloud_name": cloud_name,
    }
