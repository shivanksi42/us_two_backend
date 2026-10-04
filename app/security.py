"""Security utilities for hashing and token management.

Provides:
- Password hashing and verification (bcrypt)
- JWT access token creation and verification with JTI denylist support
- Secure token generation for refresh tokens
- Token hashing for secure storage

Adapted from Project1 — stripped email encryption (not needed for us-two).
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt

from app.config import settings
from app.exceptions import TokenExpiredError, TokenInvalidError


# ── PASSWORD HASHING ──


def hash_password(password: str) -> str:
    """Hash a password using bcrypt with 12 salt rounds.

    Args:
        password: Plain-text password.

    Returns:
        Bcrypt hash string.
    """
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash.

    Args:
        plain: Plain-text password.
        hashed: Bcrypt hash to compare against.

    Returns:
        True if the password matches, False otherwise.
    """
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT TOKENS ──


def create_access_token(data: dict) -> str:
    """Create a HS256 JWT access token.

    Injects a unique `jti` (JWT ID) for denylist support,
    and sets an expiry based on ACCESS_TOKEN_EXPIRE_MINUTES.

    Args:
        data: Payload dict containing user_id, etc.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update(
        {
            "exp": expire,
            "jti": str(uuid4()),
            "iat": datetime.now(timezone.utc),
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Verify and decode a JWT access token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded payload dictionary.

    Raises:
        TokenExpiredError: If the token has expired.
        TokenInvalidError: If the token is malformed or has an invalid signature.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.PyJWTError:
        raise TokenInvalidError()


# ── SECURE TOKEN GENERATION ──


def generate_secure_token() -> str:
    """Generate a cryptographically secure URL-safe token.

    Used for refresh tokens, verification tokens, etc.

    Returns:
        URL-safe token string (32 bytes of randomness).
    """
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a raw token with SHA-256 for secure storage.

    Args:
        token: Raw token string.

    Returns:
        SHA-256 hex digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
