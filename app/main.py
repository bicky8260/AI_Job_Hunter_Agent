"""
FastAPI application entrypoint.

Sets up:
- All API routers
- Static files + dashboard
- Database initialization
- APScheduler
- Logging
- Lifespan events (startup/shutdown)
"""
import asyncio
import logging
import logging.config
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import ensure_directories, get_settings
from app.database.database import create_tables, init_engine
from app.scheduler.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def setup_logging():
    """Configure structured logging."""
    settings = get_settings()
    log_level = settings.log_level.upper()

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "standard",
                "level": log_level,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": "logs/app.log",
                "maxBytes": 10 * 1024 * 1024,  # 10 MB
                "backupCount": 5,
                "formatter": "standard",
                "level": log_level,
            },
        },
        "root": {
            "handlers": ["console", "file"],
            "level": log_level,
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "apscheduler": {"level": "INFO"},
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
        },
    })


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    # ── Startup ──────────────────────────────────────────────
    ensure_directories()   # Must come FIRST — creates logs/ before logging init
    setup_logging()

    logger.info("=" * 60)
    logger.info("AI Job Hunter starting up")
    logger.info("=" * 60)

    # Initialize database
    try:
        init_engine()
        await create_tables()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database initialization failed: {e!r}")
        logger.error("Make sure PostgreSQL is running and DATABASE_URL is correct")
        # Don't exit — let the app start so we can see error in dashboard

    # Start scheduler
    try:
        start_scheduler()
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Scheduler startup failed: {e!r}")

    settings = get_settings()
    logger.info(f"LLM provider: {settings.llm_provider}")
    logger.info(f"Email configured: {settings.is_email_configured}")
    logger.info(f"Scheduler: {settings.scheduler_hour:02d}:{settings.scheduler_minute:02d} {settings.scheduler_timezone}")
    logger.info("Application ready — visit http://localhost:8000")
    logger.info("=" * 60)

    yield

    # ── Shutdown ─────────────────────────────────────────────
    logger.info("Shutting down...")
    stop_scheduler()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="AI Job Hunter",
        description="Personal AI-powered job search agent",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── API Routes ────────────────────────────────────────────
    from app.api.routes_agent import router as agent_router
    from app.api.routes_jobs import router as jobs_router
    from app.api.routes_preferences import router as prefs_router
    from app.api.routes_resume import router as resume_router

    api_prefix = "/api"
    app.include_router(agent_router, prefix=api_prefix, tags=["Agent"])
    app.include_router(jobs_router, prefix=api_prefix, tags=["Jobs"])
    app.include_router(prefs_router, prefix=api_prefix, tags=["Preferences"])
    app.include_router(resume_router, prefix=api_prefix, tags=["Resume"])

    # ── Dashboard (served at root) ────────────────────────────
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard():
        dashboard_path = TEMPLATES_DIR / "dashboard.html"
        return FileResponse(str(dashboard_path))

    # ── Health ────────────────────────────────────────────────
    @app.get("/health", include_in_schema=False)
    async def root_health():
        return {"status": "ok"}

    return app


# Create the application
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
