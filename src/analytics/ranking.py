"""Wallet ranking engine."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Wallet, WalletMetrics


async def get_wallet_ranking(
    session: AsyncSession,
    chain_key: Optional[str] = None,
    min_score: float = 0.0,
    min_trades: int = 0,
    min_roi: float = -999,
    limit: int = 20,
) -> list[dict]:
    q = (
        select(Wallet, WalletMetrics)
        .join(WalletMetrics, WalletMetrics.wallet_id == Wallet.id)
        .where(
            Wallet.enabled == True,
            WalletMetrics.chain_key == chain_key,
            WalletMetrics.smart_money_score >= min_score,
            WalletMetrics.total_trades >= min_trades,
            WalletMetrics.average_roi >= min_roi,
        )
        .order_by(desc(WalletMetrics.smart_money_score))
        .limit(limit)
    )

    result = await session.execute(q)
    rows = result.all()

    ranking = []
    for i, (wallet, metrics) in enumerate(rows, 1):
        ranking.append({
            "rank": i,
            "wallet_id": wallet.id,
            "address": wallet.address,
            "label": wallet.label or wallet.address[:10],
            "score": metrics.smart_money_score,
            "win_rate": metrics.win_rate,
            "average_roi": metrics.average_roi,
            "total_pnl_usd": metrics.total_pnl_usd,
            "total_trades": metrics.total_trades,
            "avg_hold_seconds": metrics.avg_holding_seconds,
            "flags": wallet.risk_flags or [],
        })
    return ranking
