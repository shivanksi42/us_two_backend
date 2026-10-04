"""Shared dependency injection functions.

Provides:
- get_db(): Database session with automatic rollback/cleanup
- get_current_user(): JWT + user state verification
Adapted from Project1's 4-layer auth dependency.
"""

from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.exceptions import (
    AccountDeletedError,
    AccountSuspendedError,
    AuthenticationError,
    TokenInvalidError,
    TokenRevokedError,
)
from app.security import verify_access_token

import logging

logger = logging.getLogger("us-two.deps")

auth_scheme = HTTPBearer(auto_error=False)


def get_db():
    """Yield a SQLAlchemy session, rolling back on error and always closing.

    Yields:
        SQLAlchemy Session instance.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(auth_scheme),
    db: Session = Depends(get_db),
):
    """Authenticate and return the current user via JWT.

    Performs 4 layers of verification:
    1. Verify JWT signature and expiry
    2. Check token_denylist by jti
    3. Check user.is_deleted
    4. Check user.is_active

    Args:
        request: The incoming HTTP request.
        credentials: Bearer token from Authorization header.
        db: Database session.

    Returns:
        User model instance.

    Raises:
        AuthenticationError: If no token is provided.
        TokenExpiredError: If the token has expired.
        TokenInvalidError: If the token signature is invalid.
        TokenRevokedError: If the token jti is denylisted.
        AccountDeletedError: If the user account is soft-deleted.
        AccountSuspendedError: If the user account is deactivated.
    """
    token = credentials.credentials if credentials else None

    if not token:
        raise AuthenticationError()

    # LAYER 1: Verify JWT signature and expiry
    payload = verify_access_token(token)

    user_id = payload.get("user_id")
    jti = payload.get("jti")

    if not user_id or not jti:
        raise TokenInvalidError()

    # LAYER 2: Check token_denylist by jti
    from app.auth.models import TokenDenylist
    denied = db.query(TokenDenylist).filter(TokenDenylist.jti == jti).first()
    if denied:
        logger.warning("Denylisted token used: jti=%s, user_id=%s", jti, user_id)
        raise TokenRevokedError()

    # LAYER 3 & 4: Check user state
    from app.auth.models import User
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise TokenInvalidError()

    if user.is_deleted:
        raise AccountDeletedError()

    if not user.is_active:
        raise AccountSuspendedError()

    return user
