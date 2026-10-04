"""Auth module route handlers.

Contains zero business logic — all logic lives in AuthService.
Handles HTTP-specific concerns: cookies, headers, response formatting.
Adapted from Project1's production-grade auth router for us-two.
"""

from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.auth.schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    GoogleLoginRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
)
from app.auth.service import AuthService
from app.config import settings
from app.exceptions import InvalidCredentialsError

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Set an HTTP-only secure cookie for the refresh token.

    Args:
        response: FastAPI Response object.
        refresh_token: Raw refresh token value.
    """
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
        max_age=90 * 24 * 60 * 60,  # 90 days in seconds
        path="/api/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    """Clear the refresh token cookie.

    Args:
        response: FastAPI Response object.
    """
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=False,
        samesite="lax",
        path="/api/auth",
    )


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, checking X-Forwarded-For first."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── REGISTRATION ──


@router.post("/register", status_code=201)
def register(
    request: Request,
    response: Response,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user account.

    Creates user with hashed password and issues tokens immediately.
    """
    result = AuthService.register(
        db=db,
        email=payload.email,
        password=payload.password,
    )

    # Set refresh token as HTTP-only cookie
    _set_refresh_cookie(response, result["refresh_token"])

    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "user": result["user"],
        "message": result["message"],
    }


# ── LOGIN ──


@router.post("/login")
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate and issue access + refresh tokens.

    Sets refresh token as HTTP-only cookie and returns access token in body.
    """
    device_info = request.headers.get("User-Agent")
    ip_address = _get_client_ip(request)

    result = AuthService.login(
        db=db,
        email=payload.email,
        password=payload.password,
        device_info=device_info,
        ip_address=ip_address,
    )

    # Set refresh token as HTTP-only cookie
    _set_refresh_cookie(response, result["refresh_token"])

    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "user": result["user"],
        "message": result["message"],
    }


@router.post("/google")
def google_login(
    request: Request,
    response: Response,
    payload: GoogleLoginRequest,
    db: Session = Depends(get_db),
):
    """Validate a Google ID token, then create or sign in the local user."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google Sign-In is not configured.")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            payload.credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
        if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
            raise ValueError("Invalid Google token issuer")
        if not claims.get("email_verified") or not claims.get("email") or not claims.get("sub"):
            raise ValueError("Google account email is not verified")
    except Exception:
        raise InvalidCredentialsError()

    result = AuthService.login_with_google(
        db=db,
        email=claims["email"],
        google_sub=claims["sub"],
        device_info=request.headers.get("User-Agent"),
        ip_address=_get_client_ip(request),
    )
    _set_refresh_cookie(response, result["refresh_token"])
    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "user": result["user"],
        "message": result["message"],
    }


# ── SILENT REFRESH ──


@router.post("/refresh")
def refresh(
    request: Request,
    response: Response,
    payload: Optional[RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(default=None),
):
    """Rotate the refresh token and issue a new access token.

    Reads refresh token from HTTP-only cookie or request body.
    """
    # Determine refresh token source
    raw_token = refresh_token  # From cookie
    if not raw_token and payload and payload.refresh_token:
        raw_token = payload.refresh_token

    if not raw_token:
        from app.exceptions import TokenInvalidError
        raise TokenInvalidError()

    ip_address = _get_client_ip(request)

    result = AuthService.refresh_token(
        db=db,
        raw_refresh_token=raw_token,
        ip_address=ip_address,
    )

    # Set new refresh token cookie
    _set_refresh_cookie(response, result["refresh_token"])

    return {
        "access_token": result["access_token"],
        "token_type": result["token_type"],
        "message": result["message"],
    }


# ── LOGOUT ──


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    refresh_token: Optional[str] = Cookie(default=None),
):
    """Logout by revoking the refresh token and denylisting the access token.

    Clears the refresh token cookie.
    """
    # Extract access token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    access_token = None
    if auth_header.startswith("Bearer "):
        access_token = auth_header[7:]

    result = AuthService.logout(
        db=db,
        raw_refresh_token=refresh_token,
        access_token=access_token,
    )

    _clear_refresh_cookie(response)

    return {"message": result["message"]}


# ── LOGOUT ALL DEVICES ──


@router.post("/logout-all")
def logout_all(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Terminate all active sessions for the current user."""
    result = AuthService.logout_all(db=db, user_id=str(current_user.id))
    return {"message": result["message"]}


# ── CHANGE PASSWORD ──


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the current user's password.

    Revokes all sessions after password change.
    """
    result = AuthService.change_password(
        db=db,
        user=current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    return {"message": result["message"]}


# ── GET CURRENT USER ──


@router.get("/me")
def me(
    current_user=Depends(get_current_user),
):
    """Get current user profile."""
    return {"id": current_user.id, "email": current_user.email}


# ── DELETE ACCOUNT ──


@router.delete("/account")
def delete_account(
    request: Request,
    response: Response,
    payload: DeleteAccountRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete user account after password confirmation.

    Revokes all sessions and denylists the current access token.
    """
    auth_header = request.headers.get("Authorization", "")
    access_token = None
    if auth_header.startswith("Bearer "):
        access_token = auth_header[7:]

    result = AuthService.delete_account(
        db=db,
        user=current_user,
        password=payload.password,
        access_token=access_token,
    )

    _clear_refresh_cookie(response)

    return {"message": result["message"]}
