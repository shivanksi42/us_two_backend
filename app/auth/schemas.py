"""Auth module Pydantic schemas.

Request and response schemas for all authentication flows.
Never exposes internal fields (password_hash, etc.).
Adapted from Project1's production-grade schemas for us-two.
"""

import re
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# ── BASE SCHEMA ──


class BaseSchema(BaseModel):
    """Base schema with shared configuration."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
    )


# ── PASSWORD VALIDATION ──

PASSWORD_MIN_LENGTH = 8
PASSWORD_PATTERN_UPPER = re.compile(r"[A-Z]")
PASSWORD_PATTERN_LOWER = re.compile(r"[a-z]")
PASSWORD_PATTERN_DIGIT = re.compile(r"\d")
PASSWORD_PATTERN_SPECIAL = re.compile(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]")


def validate_password_strength(password: str) -> str:
    """Validate password meets strength requirements.

    Rules:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character

    Args:
        password: The password to validate.

    Returns:
        The password if valid.

    Raises:
        ValueError: With a clear message describing what's missing.
    """
    errors = []
    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if not PASSWORD_PATTERN_UPPER.search(password):
        errors.append("Password must contain at least one uppercase letter")
    if not PASSWORD_PATTERN_LOWER.search(password):
        errors.append("Password must contain at least one lowercase letter")
    if not PASSWORD_PATTERN_DIGIT.search(password):
        errors.append("Password must contain at least one digit")
    if not PASSWORD_PATTERN_SPECIAL.search(password):
        errors.append("Password must contain at least one special character")

    if errors:
        raise ValueError("; ".join(errors))
    return password


# ── REQUEST SCHEMAS ──


class RegisterRequest(BaseSchema):
    """Registration request payload."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        """Validate password strength requirements."""
        return validate_password_strength(v)


class LoginRequest(BaseSchema):
    """Login request payload."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        """Normalize email to lowercase."""
        return v.strip().lower()


class RefreshTokenRequest(BaseSchema):
    """Refresh token request payload."""

    refresh_token: Optional[str] = Field(default=None)


class DeleteAccountRequest(BaseSchema):
    """Account deletion request payload — requires password confirmation."""

    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseSchema):
    """Change password request payload."""

    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        """Validate password strength requirements."""
        return validate_password_strength(v)


# ── RESPONSE SCHEMAS ──


class UserResponse(BaseSchema):
    """Safe user representation — never exposes internal fields."""

    id: str
    email: str
    is_active: bool
    last_login_at: Optional[str] = None
