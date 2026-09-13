"""Health check endpoint."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db, redis_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/")
async def health(db: AsyncSession = Depends(get_db)):
    checks: dict[str, str] = {}

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        r = await redis_client()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    status = "ok" if all(v == "ok" for v in checks.items()) else "degraded"
    return {"status": status, "checks": checks, "ts": int(time.time())}
