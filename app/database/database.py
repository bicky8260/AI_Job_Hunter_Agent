"""
SQLAlchemy async database setup.
Provides engine, session factory, and FastAPI dependency.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all models."""
    pass


def get_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


# Module-level engine and session factory (created once)
_engine = None
_session_factory = None


def init_engine():
    """Initialize the global engine and session factory."""
    global _engine, _session_factory
    _engine = get_engine()
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    return _engine, _session_factory


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        init_engine()
    return _session_factory


def get_db_engine():
    global _engine
    if _engine is None:
        init_engine()
    return _engine


async def create_tables():
    """Create all database tables (for development/testing)."""
    from app.database import models  # noqa: F401 — register models

    engine = get_db_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Drop all database tables (for testing)."""
    engine = get_db_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager version for use outside of FastAPI request context."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
