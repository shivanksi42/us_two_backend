"""Partner connection router.

Endpoints:
  POST /api/connect/invite          – send an invite to a partner email
  POST /api/connect/respond         – accept or reject a received invite
  GET  /api/connect/status          – get current user's connection status + partner info
  DELETE /api/connect               – disconnect from current partner
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.connect.models import PartnerConnection
from app.connect.schemas import RespondInviteRequest, SendInviteRequest
from app.dependencies import get_current_user, get_db

router = APIRouter(prefix="/api/connect", tags=["Partner Connection"])


def _get_accepted_connection(db: Session, user_id: str) -> Optional[PartnerConnection]:
    """Return the accepted connection record for this user (as either side)."""
    return db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.status == "accepted",
            or_(
                PartnerConnection.requester_id == user_id,
                PartnerConnection.partner_id == user_id,
            ),
        )
    )


def _partner_email(conn: PartnerConnection, current_user_id: str) -> str:
    """Return the partner's email from a connection, regardless of which side we are."""
    if conn.requester_id == current_user_id:
        return conn.partner.email if conn.partner else conn.invitee_email
    return conn.requester.email


@router.get("/status")
def connection_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current connection state and partner info."""
    # Check if already connected
    accepted = _get_accepted_connection(db, user.id)
    if accepted:
        partner = accepted.partner if accepted.requester_id == user.id else accepted.requester
        return {
            "status": "connected",
            "connection_id": accepted.id,
            "partner_email": partner.email if partner else accepted.invitee_email,
            "partner_id": partner.id if partner else None,
        }

    # Pending invites sent by me
    sent = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.requester_id == user.id,
            PartnerConnection.status == "pending",
        )
    )
    if sent:
        return {
            "status": "pending_sent",
            "connection_id": sent.id,
            "invitee_email": sent.invitee_email,
        }

    # Pending invites received by my email
    received = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.invitee_email == user.email,
            PartnerConnection.status == "pending",
        )
    )
    if received:
        requester = db.get(User, received.requester_id)
        return {
            "status": "pending_received",
            "connection_id": received.id,
            "from_email": requester.email if requester else "someone",
        }

    return {"status": "none"}


@router.post("/invite", status_code=201)
def send_invite(
    payload: SendInviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a partner connection invite by email."""
    if payload.partner_email == user.email:
        raise HTTPException(400, "You cannot connect with yourself.")

    # Already connected?
    if _get_accepted_connection(db, user.id):
        raise HTTPException(400, "You are already connected with a partner.")

    # Already sent a pending invite?
    existing = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.requester_id == user.id,
            PartnerConnection.status == "pending",
        )
    )
    if existing:
        raise HTTPException(400, "You already have a pending invite. Cancel it first.")

    conn = PartnerConnection(
        requester_id=user.id,
        invitee_email=payload.partner_email,
        status="pending",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)

    return {
        "message": f"Invite sent to {payload.partner_email}. They need to log in and accept.",
        "connection_id": conn.id,
    }


@router.post("/respond")
def respond_invite(
    payload: RespondInviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept or reject a received invite."""
    conn = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.id == payload.connection_id,
            PartnerConnection.invitee_email == user.email,
            PartnerConnection.status == "pending",
        )
    )
    if not conn:
        raise HTTPException(404, "Invite not found or already responded.")

    if payload.accept:
        # Can't accept if already connected
        if _get_accepted_connection(db, user.id):
            raise HTTPException(400, "You are already connected with another partner.")

        conn.status = "accepted"
        conn.partner_id = user.id
        db.commit()
        requester = db.get(User, conn.requester_id)
        return {
            "message": f"Connected with {requester.email if requester else 'your partner'}! You now share all memories.",
            "status": "connected",
        }
    else:
        conn.status = "rejected"
        db.commit()
        return {"message": "Invite declined.", "status": "rejected"}


@router.delete("")
def disconnect(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Disconnect from current partner."""
    conn = _get_accepted_connection(db, user.id)
    if not conn:
        raise HTTPException(400, "You are not connected with anyone.")

    conn.status = "cancelled"
    db.commit()
    return {"message": "Disconnected. Your individual memories remain intact."}


@router.delete("/cancel")
def cancel_invite(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending outgoing invite."""
    conn = db.scalar(
        select(PartnerConnection).where(
            PartnerConnection.requester_id == user.id,
            PartnerConnection.status == "pending",
        )
    )
    if not conn:
        raise HTTPException(404, "No pending invite to cancel.")

    conn.status = "cancelled"
    db.commit()
    return {"message": "Invite cancelled."}
