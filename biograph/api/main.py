"""
BioGraph MVP v8.3 - Production API Entrypoint

This is the ONLY production API runtime.

Per Section 27: Single API Runtime (LOCKED)
- FastAPI is the sole supported framework
- All endpoints under /api/v1/*
- OpenAPI documentation at /docs and /openapi.json

Per Section 29: Database Connection Management (LOCKED)
- Connection pooling required
- Pool created at startup, closed at shutdown

Per Section 30: Error Handling & Safe Responses (LOCKED)
- No stack traces to clients
- Structured JSON errors with request_id

Per Section 31: Required Operational Endpoints (LOCKED)
- GET /healthz (health check)
"""

import os
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import structlog

from biograph.api.dependencies import (
    init_connection_pool,
    close_connection_pool,
    generate_request_id
)
from biograph.api.v1 import issuers, health, admin

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Startup:
    - Initialize database connection pool
    - Log startup message

    Shutdown:
    - Close database connection pool
    - Log shutdown message
    """
    # Startup
    logger.info("app.startup", version="8.3.0")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("app.startup.failed", error="DATABASE_URL not set")
        raise RuntimeError("DATABASE_URL environment variable required")

    db_pool_min = int(os.getenv("DB_POOL_MIN_SIZE", "5"))
    db_pool_max = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
    db_pool_timeout = float(os.getenv("DB_POOL_TIMEOUT", "10.0"))

    init_connection_pool(
        database_url=database_url,
        min_size=db_pool_min,
        max_size=db_pool_max,
        timeout=db_pool_timeout
    )

    logger.info("app.ready", status="healthy")

    yield

    # Shutdown
    logger.info("app.shutdown")
    close_connection_pool()


# Create FastAPI app
app = FastAPI(
    title="BioGraph API",
    description="Investor-grade intelligence graph for life sciences",
    version="8.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# Middleware: Request ID
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    """
    Add request_id to request state for tracing.

    Per Section 30: Structured logs with request_id.
    """
    request_id = generate_request_id()
    request.state.request_id = request_id

    # Add to response headers
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    return response


# Middleware: CORS (restrictive by default)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",")
if not CORS_ORIGINS or CORS_ORIGINS == [""]:
    CORS_ORIGINS = ["http://localhost:3000", "http://localhost:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler.

    Per Section 30: No stack traces to clients.
    Returns structured JSON error with request_id.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    logger.error(
        "unhandled_exception",
        exc_info=exc,
        request_id=request_id,
        path=request.url.path,
        method=request.method
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
                "request_id": request_id
            }
        }
    )


# Include routers
app.include_router(health.router, tags=["health"])
app.include_router(issuers.router, tags=["issuers"])
app.include_router(admin.router, tags=["admin"])


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint redirect to docs."""
    return {
        "message": "BioGraph API v8.3",
        "docs": "/docs",
        "health": "/healthz"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "biograph.api.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info"
    )
