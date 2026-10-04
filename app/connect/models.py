"""Partner connection database model.

A connection links two user accounts so they share the same memory archive.
Connections use an invite/accept flow keyed by email address.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PartnerConnection(Base):
    """Represents a partner connection between two users.

    Lifecycle:
    - User A sends invite → status='pending', requester_id=A, invitee_email=B's email
    - User B accepts    → status='accepted', partner_id=B's user id
    """

    __tablename__ = "partner_connections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Who sent the invite
    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Email of who was invited
    invitee_email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)

    # Filled in once accepted
    partner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # 'pending' | 'accepted' | 'rejected' | 'cancelled'
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    requester = relationship("User", foreign_keys=[requester_id])
    partner = relationship("User", foreign_keys=[partner_id])
