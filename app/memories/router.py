"""Memories module route handlers.

Handles CRUD operations for memories, days, and entries.
"""

import os
import logging
from datetime import date, datetime, timezone
from typing import Optional

import cloudinary
import cloudinary.api
import cloudinary.utils
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.config import settings
from app.connect.models import PartnerConnection
from app.dependencies import get_current_user, get_db
from app.memories.models import Memory, MemoryDay, MemoryEntry
from app.memories.schemas import (
    BulkEntriesIn, DayIn, DayUpdate, EntryIn, EntryUpdate, MemoryIn, MemoryUpdate,
)

router = APIRouter(prefix="/api", tags=["Memories"])
logger = logging.getLogger("us-two.memories")


def journey_label(
    date_start: Optional[str], date_end: Optional[str], fallback: Optional[str]
) -> Optional[str]:
    """Return the consistent human-readable label used across the journal."""
    if not date_start or not date_end:
        return fallback
    start, end = date.fromisoformat(date_start), date.fromisoformat(date_end)
    return f"Our Journey: {start.day} {start.strftime('%b')} · Through: {end.day} {end.strftime('%b')}"


def shared_user_ids(db: Session, user_id: str) -> list[str]:
    """Return both account ids for an accepted couple, otherwise just the user."""
    connection = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.status == "accepted",
            or_(
                PartnerConnection.requester_id == user_id,
                PartnerConnection.partner_id == user_id,
            ),
        )
    )
    if not connection:
        return [user_id]
    partner_id = connection.partner_id if connection.requester_id == user_id else connection.requester_id
    return [user_id, partner_id] if partner_id else [user_id]


def accessible_memory(db: Session, memory_id: str, user_id: str) -> Optional[Memory]:
    """Find a memory either partner is allowed to change."""
    return db.scalar(
        select(Memory).where(
            Memory.id == memory_id,
            Memory.user_id.in_(shared_user_ids(db, user_id)),
        )
    )


def accessible_day(db: Session, day_id: str, user_id: str) -> Optional[MemoryDay]:
    """Find a day either partner is allowed to change."""
    return db.scalar(
        select(MemoryDay)
        .join(Memory)
        .where(MemoryDay.id == day_id, Memory.user_id.in_(shared_user_ids(db, user_id)))
    )


def configure_cloudinary() -> tuple[str, str, str]:
    """Configure Cloudinary and return its credentials or a clear API error."""
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
    return cloud_name, api_key, api_secret


def delete_cloudinary_media(entries: list[MemoryEntry]) -> None:
    """Delete Cloudinary image/video assets before their DB rows disappear."""
    media_by_type: dict[str, set[str]] = {"image": set(), "video": set()}
    for entry in entries:
        if entry.photo_public_id and entry.type in {"photo", "video"}:
            resource_type = "video" if entry.type == "video" else "image"
            media_by_type[resource_type].add(entry.photo_public_id)
    if not any(media_by_type.values()):
        return
    configure_cloudinary()
    try:
        for resource_type, public_ids in media_by_type.items():
            if not public_ids:
                continue
            result = cloudinary.api.delete_resources(
                sorted(public_ids), resource_type=resource_type, invalidate=True,
            )
            deleted = result.get("deleted", {})
            failed = [public_id for public_id in public_ids if deleted.get(public_id) not in {"deleted", "not_found"}]
            if failed:
                logger.error("Cloudinary did not delete %s asset(s): %s", resource_type, failed)
                raise HTTPException(502, "Could not delete the uploaded media. Please try again.")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Cloudinary media deletion failed")
        raise HTTPException(502, "Could not delete the uploaded media. Please try again.")


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
        "sortOrder": entry.sort_order,
    }


def dump_memory(memory: Memory) -> dict:
    """Serialize a memory with all its days and entries."""
    return {
        "id": memory.id,
        "title": memory.title,
        "place": memory.place,
        "dates": journey_label(memory.date_start, memory.date_end, memory.date_label),
        "startDate": memory.date_start,
        "endDate": memory.date_end,
        "color": memory.color,
        "cover": memory.cover,
        "heroPositionX": memory.hero_position_x,
        "heroPositionY": memory.hero_position_y,
        "days": [
            {
                "id": day.id,
                "date": day.day_date,
                "label": day.title,
                "entries": [
                    dump_entry(e)
                    for e in sorted(day.entries, key=lambda x: (x.sort_order is None, x.sort_order or 0, x.created_at))
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
    user_ids = shared_user_ids(db, user.id)

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
    data = payload.model_dump()
    data["date_label"] = journey_label(data["date_start"], data["date_end"], data["date_label"])
    memory = Memory(user_id=user.id, **data)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return dump_memory(memory)


@router.put("/memories/{memory_id}")
def update_memory(
    memory_id: str,
    payload: MemoryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a shared memory; either connected partner may do so."""
    memory = accessible_memory(db, memory_id, user.id)
    if not memory:
        raise HTTPException(404, "Memory not found.")
    data = payload.model_dump()
    data["date_label"] = journey_label(data["date_start"], data["date_end"], data["date_label"])
    for key, value in data.items():
        setattr(memory, key, value)
    db.commit()
    db.refresh(memory)
    return dump_memory(memory)


@router.delete("/memories/{memory_id}", status_code=204)
def delete_memory(
    memory_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a memory and its days/moments for both connected partners."""
    memory = accessible_memory(db, memory_id, user.id)
    if not memory:
        raise HTTPException(404, "Memory not found.")
    delete_cloudinary_media([
        entry for day in memory.days for entry in day.entries
    ])
    db.delete(memory)
    db.commit()


@router.post("/memories/{memory_id}/days", status_code=201)
def create_day(
    memory_id: str,
    payload: DayIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a day to a memory."""
    memory = accessible_memory(db, memory_id, user.id)
    if not memory:
        raise HTTPException(404, "Memory not found.")
    day = MemoryDay(memory_id=memory.id, **payload.model_dump())
    db.add(day)
    db.commit()
    db.refresh(day)
    return {"id": day.id, "date": day.day_date, "label": day.title, "entries": []}


@router.put("/days/{day_id}")
def update_day(
    day_id: str,
    payload: DayUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    day = accessible_day(db, day_id, user.id)
    if not day:
        raise HTTPException(404, "Day not found.")
    day.day_date, day.title = payload.day_date, payload.title
    db.commit()
    db.refresh(day)
    return {"id": day.id, "date": day.day_date, "label": day.title, "entries": [dump_entry(e) for e in day.entries]}


@router.delete("/days/{day_id}", status_code=204)
def delete_day(
    day_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    day = accessible_day(db, day_id, user.id)
    if not day:
        raise HTTPException(404, "Day not found.")
    delete_cloudinary_media(list(day.entries))
    db.delete(day)
    db.commit()


@router.post("/days/{day_id}/entries", status_code=201)
def create_entry(
    day_id: str,
    payload: EntryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add an entry to a day."""
    day = accessible_day(db, day_id, user.id)
    if not day:
        raise HTTPException(404, "Day not found.")
    next_order = max((entry.sort_order or 0 for entry in day.entries), default=-1) + 1
    entry = MemoryEntry(day_id=day.id, sort_order=next_order, **payload.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return dump_entry(entry)


@router.put("/entries/{entry_id}")
def update_entry(
    entry_id: str,
    payload: EntryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.scalar(
        select(MemoryEntry)
        .join(MemoryDay)
        .join(Memory)
        .where(MemoryEntry.id == entry_id, Memory.user_id.in_(shared_user_ids(db, user.id)))
    )
    if not entry:
        raise HTTPException(404, "Moment not found.")
    for key, value in payload.model_dump().items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return dump_entry(entry)


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(
    entry_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.scalar(
        select(MemoryEntry)
        .join(MemoryDay)
        .join(Memory)
        .where(MemoryEntry.id == entry_id, Memory.user_id.in_(shared_user_ids(db, user.id)))
    )
    if not entry:
        raise HTTPException(404, "Moment not found.")
    delete_cloudinary_media([entry])
    db.delete(entry)
    db.commit()


@router.post("/days/{day_id}/entries/bulk", status_code=201)
def create_entries_bulk(
    day_id: str,
    payload: BulkEntriesIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add multiple entries to a day in a single batch transaction."""
    day = accessible_day(db, day_id, user.id)
    if not day:
        raise HTTPException(404, "Day not found.")

    # Normalize the current sequence, then insert the new batch at the
    # requested visual position. This remains deterministic for both partners.
    existing = sorted(day.entries, key=lambda x: (x.sort_order is None, x.sort_order or 0, x.created_at))
    insert_at = len(existing) if payload.insert_at is None else min(payload.insert_at, len(existing))
    for index, entry in enumerate(existing):
        entry.sort_order = index if index < insert_at else index + len(payload.entries)
    new_entries = [
        MemoryEntry(day_id=day.id, sort_order=insert_at + index, **entry_data.model_dump())
        for index, entry_data in enumerate(payload.entries)
    ]
    db.add_all(new_entries)
    db.commit()
    for e in new_entries:
        db.refresh(e)

    return [dump_entry(e) for e in new_entries]


@router.get("/uploads/signature")
def cloudinary_signature(user: User = Depends(get_current_user)):
    """Generate a Cloudinary upload signature."""
    cloud_name, api_key, api_secret = configure_cloudinary()
    timestamp = int(datetime.now(timezone.utc).timestamp())
    params = {"timestamp": timestamp, "folder": f"us-two/{user.id}"}
    return {
        "timestamp": timestamp,
        "folder": f"us-two/{user.id}",
        "signature": cloudinary.utils.api_sign_request(params, api_secret),
        "api_key": api_key,
        "cloud_name": cloud_name,
    }
