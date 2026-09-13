"""Trade history REST endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db
from src.database.models import Trade, TradeSide

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/")
async def list_trades(
    wallet_id: Optional[int] = Query(None),
    chain_id: Optional[int] = Query(None),
    side: Optional[str] = Query(None),
    min_roi: Optional[float] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Trade).order_by(desc(Trade.timestamp))

    if wallet_id:
        q = q.where(Trade.wallet_id == wallet_id)
    if chain_id:
        q = q.where(Trade.chain_id == chain_id)
    if side:
        q = q.where(Trade.side == TradeSide(side))
    if min_roi is not None:
        q = q.where(Trade.roi_percent >= min_roi)

    result = await db.execute(q.limit(limit).offset(offset))
    trades = result.scalars().all()
    return [_serialize_trade(t) for t in trades]


@router.get("/{trade_id}")
async def get_trade(trade_id: int, db: AsyncSession = Depends(get_db)):
    from fastapi import HTTPException

    result = await db.execute(select(Trade).where(Trade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return _serialize_trade(trade)


def _serialize_trade(t: Trade) -> dict:
    return {
        "id": t.id,
        "wallet_id": t.wallet_id,
        "chain_id": t.chain_id,
        "token_id": t.token_id,
        "tx_hash": t.tx_hash,
        "side": t.side.value if t.side else None,
        "trade_type": t.trade_type.value if t.trade_type else None,
        "quantity": t.quantity,
        "price_usd": t.price_usd,
        "value_usd": t.value_usd,
        "gas_cost_usd": t.gas_cost_usd,
        "realized_pnl_usd": t.realized_pnl_usd,
        "roi_percent": t.roi_percent,
        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
    }
