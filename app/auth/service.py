"""Auth module business logic service.

Contains all authentication flow implementations.
Every method takes db: Session as the first argument.
Routers contain zero business logic — all logic lives here.

Adapted from Project1's production-grade auth service for us-two.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.exceptions import (
    AccountDeletedError,
    AccountLockedError,
    AccountSuspendedError,
    AlreadyExistsError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from app.security import (
    create_access_token,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_access_token,
    verify_password,
)
from app.auth.models import (
    LoginAttempt,
    RefreshToken,
    TokenDenylist,
    User,
)

logger = logging.getLogger("us-two.auth")


class AuthService:
    """Authentication service implementing all auth flows."""

    # ── REGISTRATION ──

    @staticmethod
    def register(db: Session, email: str, password: str) -> dict:
        """Register a new user account.

        Args:
            db: Database session.
            email: User's email address.
            password: Plain-text password.

        Returns:
            Dict with user data and access/refresh tokens.

        Raises:
            AlreadyExistsError: If email is already registered.
        """
        email = email.strip().lower()
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            raise AlreadyExistsError("Account")

        pw_hash = hash_password(password)

        user = User(
            email=email,
            password_hash=pw_hash,
        )
        db.add(user)
        db.flush()  # Get user.id before commit

        # Issue tokens immediately on registration
        access_token = create_access_token({"user_id": user.id, "email": user.email})

        raw_refresh = generate_secure_token()
        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.add(refresh_record)

        db.commit()

        logger.info("User registered · user_id=%s", user.id)

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user": {"id": user.id, "email": user.email},
            "message": "Account created successfully",
        }

    # ── LOGIN ──

    @staticmethod
    def login(
        db: Session,
        email: str,
        password: str,
        device_info: Optional[str] = None,
        ip_address: str = "unknown",
    ) -> dict:
        """Authenticate a user and issue tokens.

        Implements account lockout after MAX_LOGIN_ATTEMPTS failed attempts.

        Args:
            db: Database session.
            email: User's email address.
            password: Plain-text password.
            device_info: User-Agent string.
            ip_address: Client IP address.

        Returns:
            Dict with access/refresh tokens and user data.

        Raises:
            InvalidCredentialsError: Wrong email or password.
            AccountLockedError: Too many failed attempts.
            AccountSuspendedError: Account is deactivated.
            AccountDeletedError: Account is soft-deleted.
        """
        email = email.strip().lower()
        user = db.query(User).filter(User.email == email).first()

        if not user:
            logger.warning("Login attempt for non-existent email=%s", email[:4] + "***")
            raise InvalidCredentialsError()

        # Account lock check
        if user.locked_until:
            lock_time = user.locked_until
            if lock_time.tzinfo is None:
                lock_time = lock_time.replace(tzinfo=timezone.utc)
            if lock_time > datetime.now(timezone.utc):
                remaining = int(
                    (lock_time - datetime.now(timezone.utc)).total_seconds() / 60
                ) + 1
                raise AccountLockedError(minutes_remaining=remaining)
            else:
                user.failed_login_attempts = 0
                user.locked_until = None

        # Account state checks
        if not user.is_active:
            raise AccountSuspendedError()

        if user.is_deleted:
            raise AccountDeletedError()

        # Password verification
        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            login_attempt = LoginAttempt(
                user_id=user.id,
                ip_address=ip_address,
                was_successful=False,
            )
            db.add(login_attempt)

            if user.failed_login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.LOCKOUT_DURATION_MINUTES
                )
                db.commit()
                raise AccountLockedError(
                    minutes_remaining=settings.LOCKOUT_DURATION_MINUTES
                )

            db.commit()
            raise InvalidCredentialsError()

        # Password correct — reset counters
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)

        login_attempt = LoginAttempt(
            user_id=user.id,
            ip_address=ip_address,
            was_successful=True,
        )
        db.add(login_attempt)

        # JWT access token
        access_token = create_access_token({"user_id": user.id, "email": user.email})

        # Refresh token
        raw_refresh = generate_secure_token()
        refresh_record = RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw_refresh),
            device_info=device_info,
            ip_address=ip_address,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.add(refresh_record)
        db.commit()

        logger.info("User logged in: user_id=%s", user.id)

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "user": {"id": user.id, "email": user.email},
            "message": "Login successful",
        }

    # ── SILENT REFRESH (TOKEN ROTATION) ──

    @staticmethod
    def refresh_token(
        db: Session,
        raw_refresh_token: str,
        ip_address: str = "unknown",
    ) -> dict:
        """Rotate refresh token and issue new access token.

        Implements token reuse detection: if a revoked token is reused,
        all refresh tokens for the user are revoked as a security measure.

        Args:
            db: Database session.
            raw_refresh_token: The current raw refresh token.
            ip_address: Client IP address.

        Returns:
            Dict with new access/refresh tokens.

        Raises:
            TokenInvalidError: If token not found.
            TokenRevokedError: If token reuse detected.
            TokenExpiredError: If token has expired.
        """
        token_hashed = hash_token(raw_refresh_token)
        stored = (
            db.query(RefreshToken)
            .filter(RefreshToken.token_hash == token_hashed)
            .first()
        )

        if not stored:
            logger.warning("Refresh token not found — suspicious activity")
            raise TokenInvalidError()

        # Token reuse detection
        if stored.revoked_at is not None:
            logger.warning(
                "Token reuse detected for user_id=%s — revoking all sessions",
                stored.user_id,
            )
            db.query(RefreshToken).filter(
                RefreshToken.user_id == stored.user_id,
                RefreshToken.revoked_at.is_(None),
            ).update({"revoked_at": datetime.now(timezone.utc)})
            db.commit()
            raise TokenRevokedError()

        # Expiry check
        expires = stored.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise TokenExpiredError()

        # Revoke old token
        stored.revoked_at = datetime.now(timezone.utc)
        stored.last_used_at = datetime.now(timezone.utc)

        # Issue new refresh token (rotation)
        new_raw_refresh = generate_secure_token()
        new_refresh = RefreshToken(
            user_id=stored.user_id,
            token_hash=hash_token(new_raw_refresh),
            ip_address=ip_address,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        db.add(new_refresh)

        # Get user for access token payload
        user = db.query(User).filter(User.id == stored.user_id).first()

        # New access token
        access_token = create_access_token({"user_id": user.id, "email": user.email})

        db.commit()

        return {
            "access_token": access_token,
            "refresh_token": new_raw_refresh,
            "token_type": "bearer",
            "message": "Token refreshed successfully",
        }

    # ── LOGOUT ──

    @staticmethod
    def logout(
        db: Session,
        raw_refresh_token: Optional[str],
        access_token: Optional[str],
    ) -> dict:
        """Logout by revoking the refresh token and denylisting the access token.

        Args:
            db: Database session.
            raw_refresh_token: The current raw refresh token.
            access_token: The current raw access token (JWT).

        Returns:
            Dict with success message.
        """
        if raw_refresh_token:
            token_hashed = hash_token(raw_refresh_token)
            stored = (
                db.query(RefreshToken)
                .filter(RefreshToken.token_hash == token_hashed)
                .first()
            )
            if stored and stored.revoked_at is None:
                stored.revoked_at = datetime.now(timezone.utc)
            elif not stored:
                logger.warning("Logout with unknown refresh token")

        # Denylist access token
        if access_token:
            try:
                payload = verify_access_token(access_token)
                jti = payload.get("jti")
                exp = payload.get("exp")
                user_id = payload.get("user_id")

                if jti and user_id:
                    denied = TokenDenylist(
                        jti=jti,
                        user_id=user_id,
                        reason="logout",
                        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc)
                        if exp
                        else datetime.now(timezone.utc) + timedelta(hours=1),
                    )
                    db.add(denied)
            except Exception:
                logger.debug("Could not denylist access token during logout")

        db.commit()
        return {"message": "Logged out successfully"}

    # ── LOGOUT ALL DEVICES ──

    @staticmethod
    def logout_all(db: Session, user_id: str) -> dict:
        """Revoke all refresh tokens for a user (terminate all sessions).

        Args:
            db: Database session.
            user_id: The user's UUID.

        Returns:
            Dict with success message.
        """
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})
        db.commit()

        logger.info("All sessions terminated for user_id=%s", user_id)
        return {"message": "All sessions terminated"}

    # ── CHANGE PASSWORD ──

    @staticmethod
    def change_password(
        db: Session,
        user: User,
        current_password: str,
        new_password: str,
    ) -> dict:
        """Change user's password and revoke all sessions.

        Args:
            db: Database session.
            user: The authenticated User model instance.
            current_password: Current password for verification.
            new_password: The new password.

        Returns:
            Dict with success message.

        Raises:
            InvalidCredentialsError: If current password is incorrect.
        """
        if not verify_password(current_password, user.password_hash):
            raise InvalidCredentialsError()

        user.password_hash = hash_password(new_password)

        # Revoke all refresh tokens (force re-login)
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})

        db.commit()
        logger.info("Password changed for user_id=%s", user.id)

        return {"message": "Password changed successfully. Please log in again."}

    # ── DELETE ACCOUNT ──

    @staticmethod
    def delete_account(
        db: Session,
        user: User,
        password: str,
        access_token: Optional[str],
    ) -> dict:
        """Soft-delete a user account after password confirmation.

        Args:
            db: Database session.
            user: The authenticated User model instance.
            password: User's current password for confirmation.
            access_token: Current access token JWT for denylisting.

        Returns:
            Dict with success message.

        Raises:
            InvalidCredentialsError: If password is incorrect.
        """
        if not verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        # Soft-delete
        user.is_deleted = True
        user.deleted_at = datetime.now(timezone.utc)

        # Revoke all refresh tokens
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})

        # Denylist current access token
        if access_token:
            try:
                payload = verify_access_token(access_token)
                jti = payload.get("jti")
                exp = payload.get("exp")
                if jti:
                    denied = TokenDenylist(
                        jti=jti,
                        user_id=str(user.id),
                        reason="account_deleted",
                        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc)
                        if exp
                        else datetime.now(timezone.utc) + timedelta(hours=1),
                    )
                    db.add(denied)
            except Exception:
                logger.debug("Could not denylist access token during account deletion")

        db.commit()
        logger.info("Account deleted (soft): user_id=%s", user.id)

        return {"message": "Account deleted successfully"}

    # ── GET CURRENT USER ──

    @staticmethod
    def get_me(db: Session, user_id: str) -> dict:
        """Get current user profile data.

        Args:
            db: Database session.
            user_id: The user's ID.

        Returns:
            Dict with user data.
        """
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise TokenInvalidError()

        return {"id": user.id, "email": user.email}
