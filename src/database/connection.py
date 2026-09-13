"""Async database engine, session factory and Redis client."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.db_pool_size if hasattr(settings, "db_pool_size") else 20,
    max_overflow=settings.db_max_overflow if hasattr(settings, "db_max_overflow") else 40,
    pool_pre_ping=True,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

_redis_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_connections() -> None:
    global _redis_pool
    await engine.dispose()
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None
