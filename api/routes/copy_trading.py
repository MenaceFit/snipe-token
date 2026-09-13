"""Copy trading control endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db
from src.database.models import CopyOrder, CopyOrderStatus

router = APIRouter(prefix="/copy_trading", tags=["copy_trading"])


@router.get("/orders")
async def list_orders(
    wallet_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(CopyOrder).order_by(desc(CopyOrder.created_at))
    if wallet_id:
        q = q.where(CopyOrder.wallet_id == wallet_id)
    if status:
        q = q.where(CopyOrder.status == CopyOrderStatus(status))

    result = await db.execute(q.limit(limit))
    orders = result.scalars().all()
    return [
        {
            "id": o.id,
            "wallet_id": o.wallet_id,
            "token_id": o.token_id,
            "side": o.side.value if o.side else None,
            "mode": o.mode.value if o.mode else None,
            "status": o.status.value if o.status else None,
            "amount_usd": o.amount_usd,
            "executed_price_usd": o.executed_price_usd,
            "tx_hash": o.tx_hash,
            "error_message": o.error_message,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]


@router.get("/summary")
async def copy_trading_summary(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func

    result = await db.execute(
        select(
            CopyOrder.status,
            func.count().label("count"),
            func.sum(CopyOrder.amount_usd).label("total_usd"),
        ).group_by(CopyOrder.status)
    )
    rows = result.all()
    return {
        "by_status": [
            {"status": r.status.value if r.status else None, "count": r.count, "total_usd": float(r.total_usd or 0)}
            for r in rows
        ]
    }
