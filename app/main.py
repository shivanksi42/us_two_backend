"""us-two backend application.

Production-grade FastAPI application with:
- Modular auth system (ported from Project1)
- Structured error handling
- Request logging middleware
- Token rotation with reuse detection
- Account lockout protection
"""

from __future__ import annotations

import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings
from app.database import Base, engine
from app.exceptions import AppException

# ── Logging ──

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("us-two")


# ── App ──

app = FastAPI(
    title="us-two API",
    description="Private memory archive for couples",
    version="2.0.0",
)


# ── Middleware ──


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assign a unique request ID and log request timing."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = uuid4().hex[:8]
        request.state.request_id = request_id

        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "%s %s → %d (%.1fms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )

        response.headers["X-Request-ID"] = request_id
        return response


# Middleware registration order matters in Starlette:
# They execute in REVERSE order, so the LAST one added is the OUTERMOST.
# CORS must be outermost so OPTIONS preflights are handled before anything else.
app.add_middleware(RequestLoggingMiddleware)

# In development, accept any localhost/127.0.0.1 port (Vite can pick 5174, 5175, etc.)
# In production, restrict to explicit FRONTEND_ORIGIN list.
_explicit_origins = [x.strip() for x in settings.FRONTEND_ORIGIN.split(",")]
_origin_regex = r"http://(localhost|127\.0\.0\.1)(:\d+)?" if settings.is_development else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_explicit_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# ── Error Handlers ──


def _get_request_id(request: Request) -> str:
    """Safely extract request_id from request state."""
    return getattr(request.state, "request_id", "unknown")


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle application-level exceptions with structured response."""
    request_id = _get_request_id(request)

    if exc.status_code >= 500:
        logger.error("[%s] %s: %s", request_id, exc.error_code, exc.message)
    else:
        logger.warning("[%s] %s: %s", request_id, exc.error_code, exc.message)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "request_id": request_id,
            },
            "detail": exc.message,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle standard HTTP exceptions."""
    request_id = _get_request_id(request)
    message = str(exc.detail) if exc.detail else "HTTP error"

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": "HTTP_ERROR",
                "message": message,
                "details": None,
                "request_id": request_id,
            },
            "detail": message,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic / FastAPI request validation errors."""
    request_id = _get_request_id(request)

    errors = []
    for error in exc.errors():
        errors.append(
            {
                "field": " → ".join(str(loc) for loc in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
        )

    logger.warning("[%s] Validation error: %s", request_id, errors)
    primary_msg = errors[0]["message"] if errors else "Request validation failed"

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": primary_msg,
                "details": errors,
                "request_id": request_id,
            },
            "detail": primary_msg,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions — never expose internal details."""
    request_id = _get_request_id(request)

    logger.error(
        "[%s] Unhandled exception: %s: %s",
        request_id,
        type(exc).__name__,
        str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
                "details": None,
                "request_id": request_id,
            },
            "detail": "An unexpected error occurred",
        },
    )


# ── Routers ──

from app.auth.router import router as auth_router
from app.connect.router import router as connect_router
from app.memories.router import router as memories_router

app.include_router(auth_router)
app.include_router(connect_router)
app.include_router(memories_router)


# ── Startup ──


@app.on_event("startup")
def startup():
    """Create tables and apply the small backwards-compatible schema upgrade."""
    # Import all models to ensure they're registered with Base.metadata
    import app.auth.models  # noqa: F401
    import app.connect.models  # noqa: F401
    import app.memories.models  # noqa: F401
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    if inspector.has_table("memories"):
        columns = {column["name"] for column in inspector.get_columns("memories")}
        with engine.begin() as connection:
            for name in ("date_start", "date_end"):
                if name not in columns:
                    connection.execute(text(f"ALTER TABLE memories ADD COLUMN {name} VARCHAR(10)"))
                    logger.info("Added memories.%s", name)
    if inspector.has_table("users"):
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        with engine.begin() as connection:
            if "google_sub" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)"))
                logger.info("Added users.google_sub")
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub ON users (google_sub)"
            ))
    if inspector.has_table("memory_entries"):
        entry_columns = {column["name"] for column in inspector.get_columns("memory_entries")}
        if "sort_order" not in entry_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE memory_entries ADD COLUMN sort_order INTEGER"))
                logger.info("Added memory_entries.sort_order")
    logger.info("Database tables created/verified")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "2.0.0"}
