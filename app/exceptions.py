"""Application exception hierarchy.

All exceptions inherit from AppException with structured error
codes, status codes, and optional detail payloads.
Ported from Project1's production-grade exception system.
"""

from typing import Any


class AppException(Exception):
    """Base exception for the us-two application.

    Attributes:
        message: Human-readable error message.
        status_code: HTTP status code.
        error_code: Machine-readable error code string.
        details: Optional additional error details.
    """

    def __init__(
        self,
        message: str = "An unexpected error occurred",
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: Any = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details
        super().__init__(self.message)


# ── AUTHENTICATION ERRORS (401) ──


class AuthenticationError(AppException):
    """Generic authentication failure."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_code="AUTHENTICATION_ERROR",
        )


class InvalidCredentialsError(AppException):
    """Invalid email or password."""

    def __init__(self) -> None:
        super().__init__(
            message="Invalid email or password",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )


class TokenExpiredError(AppException):
    """JWT or verification token has expired."""

    def __init__(self) -> None:
        super().__init__(
            message="Token has expired",
            status_code=401,
            error_code="TOKEN_EXPIRED",
        )


class TokenInvalidError(AppException):
    """Token is malformed or has an invalid signature."""

    def __init__(self) -> None:
        super().__init__(
            message="Invalid token",
            status_code=401,
            error_code="TOKEN_INVALID",
        )


class TokenRevokedError(AppException):
    """Token has been revoked (denylisted)."""

    def __init__(self) -> None:
        super().__init__(
            message="Token has been revoked",
            status_code=401,
            error_code="TOKEN_REVOKED",
        )


class AccountDeletedError(AppException):
    """User account has been soft-deleted."""

    def __init__(self) -> None:
        super().__init__(
            message="This account has been deleted",
            status_code=401,
            error_code="ACCOUNT_DELETED",
        )


class AccountSuspendedError(AppException):
    """User account has been suspended/deactivated."""

    def __init__(self) -> None:
        super().__init__(
            message="This account has been suspended",
            status_code=401,
            error_code="ACCOUNT_SUSPENDED",
        )


# ── AUTHORIZATION ERRORS (403) ──


class EmailNotVerifiedError(AppException):
    """User email is not yet verified."""

    def __init__(self) -> None:
        super().__init__(
            message="Email address has not been verified",
            status_code=403,
            error_code="EMAIL_NOT_VERIFIED",
        )


class PermissionDeniedError(AppException):
    """User lacks permission for the requested action."""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(
            message=message,
            status_code=403,
            error_code="PERMISSION_DENIED",
        )


# ── RESOURCE ERRORS (404, 409) ──


class NotFoundError(AppException):
    """Requested resource was not found."""

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            message=f"{resource} not found",
            status_code=404,
            error_code="NOT_FOUND",
            details={"resource": resource},
        )


class AlreadyExistsError(AppException):
    """Resource already exists (unique constraint violation)."""

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            message=f"{resource} already exists",
            status_code=409,
            error_code="ALREADY_EXISTS",
            details={"resource": resource},
        )


# ── VALIDATION ERRORS (422) ──


class ValidationError(AppException):
    """Request validation failure."""

    def __init__(self, message: str = "Validation error", details: Any = None) -> None:
        super().__init__(
            message=message,
            status_code=422,
            error_code="VALIDATION_ERROR",
            details=details,
        )


# ── RATE LIMITING (429) ──


class AccountLockedError(AppException):
    """Account is locked due to too many failed login attempts."""

    def __init__(self, minutes_remaining: int = 0) -> None:
        super().__init__(
            message=f"Account is locked. Try again in {minutes_remaining} minutes",
            status_code=429,
            error_code="ACCOUNT_LOCKED",
            details={"minutes_remaining": minutes_remaining},
        )


class RateLimitError(AppException):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Too many requests") -> None:
        super().__init__(
            message=message,
            status_code=429,
            error_code="RATE_LIMIT_EXCEEDED",
        )
