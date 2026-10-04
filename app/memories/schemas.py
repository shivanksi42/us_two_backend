"""Memories module Pydantic schemas."""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class MemoryIn(BaseModel):
    """Create a new memory."""
    title: str = Field(min_length=1, max_length=200)
    place: Optional[str] = None
    date_label: Optional[str] = None
    color: str = "#C45B38"
    cover: Optional[str] = None


class DayIn(BaseModel):
    """Create a new day within a memory."""
    day_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    title: str = Field(min_length=1, max_length=200)


class EntryIn(BaseModel):
    """Create a new entry within a day."""
    type: Literal["photo", "text"]
    photo_url: Optional[str] = None
    photo_public_id: Optional[str] = None
    caption: Optional[str] = None
    body: Optional[str] = None
    color: Optional[str] = None


class BulkEntriesIn(BaseModel):
    """Create multiple entries within a day in a single batch."""
    entries: list[EntryIn] = Field(..., min_length=1, max_length=100)
