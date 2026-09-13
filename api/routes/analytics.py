"""Analytics REST endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.ranking import get_wallet_ranking
from src.database.connection import get_db
from src.database.models import Position, PositionStatus, Trade, TradeSide, Wallet

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/ranking")
async def ranking(
    chain: Optional[str] = Query(None),
    min_score: float = Query(0),
    min_trades: int = Query(0),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await get_wallet_ranking(
        db, chain_key=chain, min_score=min_score, min_trades=min_trades, limit=limit
    )


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)):
    wallets_count = await db.execute(
        select(func.count()).select_from(Wallet).where(Wallet.enabled == True)
    )
    trades_today_count = await db.execute(
        select(func.count()).select_from(Trade)
    )
    open_positions = await db.execute(
        select(func.count()).select_from(Position).where(Position.status == PositionStatus.OPEN)
    )
    win_rate_result = await db.execute(
        select(
            func.count().filter(Trade.realized_pnl_usd > 0).label("wins"),
            func.count().filter(Trade.realized_pnl_usd != None).label("total"),
            func.sum(Trade.realized_pnl_usd).label("total_pnl"),
        ).select_from(Trade).where(Trade.side == TradeSide.SELL)
    )
    wr_row = win_rate_result.first()

    wins = wr_row.wins or 0
    total_closed = wr_row.total or 0
    total_pnl = float(wr_row.total_pnl or 0)
    win_rate = wins / total_closed * 100 if total_closed > 0 else 0

    return {
        "tracked_wallets": wallets_count.scalar_one(),
        "total_trades": trades_today_count.scalar_one(),
        "open_positions": open_positions.scalar_one(),
        "win_rate": round(win_rate, 1),
        "total_pnl_usd": round(total_pnl, 2),
    }


@router.get("/top_trades")
async def top_trades(
    min_roi: float = Query(50),
    min_usd: float = Query(100),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Trade)
        .where(
            Trade.side == TradeSide.SELL,
            Trade.roi_percent >= min_roi,
            Trade.value_usd >= min_usd,
        )
        .order_by(desc(Trade.roi_percent))
        .limit(limit)
    )
    trades = result.scalars().all()
    return [
        {
            "trade_id": t.id,
            "wallet_id": t.wallet_id,
            "chain_id": t.chain_id,
            "token_id": t.token_id,
            "roi_percent": t.roi_percent,
            "realized_pnl_usd": t.realized_pnl_usd,
            "value_usd": t.value_usd,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in trades
    ]


@router.get("/positions")
async def positions(
    wallet_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Position)
    if wallet_id:
        q = q.where(Position.wallet_id == wallet_id)
    if status:
        q = q.where(Position.status == PositionStatus(status))
    else:
        q = q.where(Position.status == PositionStatus.OPEN)

    result = await db.execute(q.limit(100))
    positions = result.scalars().all()
    return [
        {
            "id": p.id,
            "wallet_id": p.wallet_id,
            "token_id": p.token_id,
            "status": p.status,
            "average_entry_usd": p.average_entry_usd,
            "current_price_usd": p.current_price_usd,
            "current_value_usd": p.current_value_usd,
            "total_invested_usd": p.total_invested_usd,
            "realized_pnl_usd": p.realized_pnl_usd,
            "unrealized_pnl_usd": p.unrealized_pnl_usd,
            "roi_percent": p.roi_percent,
            "percentage_sold": p.percentage_sold,
            "first_buy_at": p.first_buy_at.isoformat() if p.first_buy_at else None,
        }
        for p in positions
    ]
