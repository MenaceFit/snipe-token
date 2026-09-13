"""Shared pytest fixtures."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.database.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """In-memory SQLite session for unit tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.setex = AsyncMock(return_value=True)
    r.exists = AsyncMock(return_value=0)
    r.ping = AsyncMock(return_value=True)
    return r


def make_timestamp() -> datetime:
    return datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
