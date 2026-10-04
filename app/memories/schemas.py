"""Memories module Pydantic schemas."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class MemoryIn(BaseModel):
    """Create a new memory."""
    title: str = Field(min_length=1, max_length=200)
    place: Optional[str] = None
    date_label: Optional[str] = None
    date_start: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_end: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    color: str = "#C45B38"
    cover: Optional[str] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        """Require complete, chronological ranges when dates are supplied."""
        if bool(self.date_start) != bool(self.date_end):
            raise ValueError("Both journey start and end dates are required.")
        if self.date_start and self.date_end:
            if date.fromisoformat(self.date_end) < date.fromisoformat(self.date_start):
                raise ValueError("Journey end date must be on or after the start date.")
        return self


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
