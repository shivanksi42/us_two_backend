"""Application configuration using pydantic-settings.

Loads all settings from environment variables / .env file.
Adapted from Project1's production-grade config for us-two.
"""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Application ──
    APP_NAME: str = "us-two"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # ── Database ──
    DATABASE_URL: str = "sqlite:///./us_two.db"

    # ── Security ──
    SECRET_KEY: str = Field(
        default="local-development-secret-change-me",
        validation_alias=AliasChoices("SECRET_KEY", "JWT_SECRET"),
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 90

    # ── Account Lockout ──
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15

    # ── CORS ──
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # ── Frontend ──
    FRONTEND_URL: str = "http://localhost:5173"

    # ── Google Sign-In ──
    # OAuth web client ID. This identifier is public; no client secret is
    # used because the API verifies the Google-issued ID token server-side.
    GOOGLE_CLIENT_ID: str = ""

    # ── Cloudinary ──
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENVIRONMENT == "development"


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()


settings = get_settings()
