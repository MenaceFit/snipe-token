"""Compute and persist wallet performance statistics."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Position, PositionStatus, Trade, TradeSide, WalletMetrics

logger = logging.getLogger(__name__)


async def compute_wallet_stats(
    session: AsyncSession,
    wallet_id: int,
    chain_key: Optional[str] = None,
) -> WalletMetrics:
    """Recompute all metrics for a wallet (and optionally a specific chain)."""

    # Fetch closed positions with at least one sell
    q = (
        select(Trade)
        .where(
            Trade.wallet_id == wallet_id,
            Trade.side == TradeSide.SELL,
            Trade.realized_pnl_usd.isnot(None),
        )
        .order_by(Trade.timestamp)
    )
    if chain_key:
        from src.database.models import Chain
        from sqlalchemy import join
        q = q.join(Chain, Chain.id == Trade.chain_id).where(Chain.chain_key == chain_key)

    result = await session.execute(q)
    sell_trades = list(result.scalars().all())

    # Also count total trades (buys + sells)
    buy_q = select(Trade).where(Trade.wallet_id == wallet_id, Trade.side == TradeSide.BUY)
    buy_result = await session.execute(buy_q)
    buy_trades = list(buy_result.scalars().all())

    total_trades = len(buy_trades)
    if total_trades == 0:
        # Return empty metrics
        return await _upsert_metrics(session, wallet_id, chain_key, {})

    # Gather per-position ROIs
    rois: list[float] = []
    pnls: list[float] = []
    winning = 0
    losing = 0
    total_pnl = 0.0
    profits: list[float] = []
    losses: list[float] = []

    # Compute per-position stats from closed positions
    pos_q = select(Position).where(
        Position.wallet_id == wallet_id,
        Position.status == PositionStatus.CLOSED,
        Position.realized_pnl_usd.isnot(None),
    )
    pos_result = await session.execute(pos_q)
    closed_positions = list(pos_result.scalars().all())

    holding_times: list[int] = []
    equity_curve: list[float] = [0.0]

    for pos in closed_positions:
        roi = pos.roi_percent or 0.0
        pnl = pos.realized_pnl_usd or 0.0
        rois.append(roi)
        pnls.append(pnl)
        total_pnl += pnl
        equity_curve.append(equity_curve[-1] + pnl)

        if pnl > 0:
            winning += 1
            profits.append(pnl)
        elif pnl < 0:
            losing += 1
            losses.append(abs(pnl))

        if pos.first_buy_at and pos.closed_at:
            hold_secs = int((pos.closed_at - pos.first_buy_at).total_seconds())
            holding_times.append(hold_secs)

    completed_positions = len(closed_positions)
    win_rate = (winning / completed_positions * 100) if completed_positions > 0 else 0.0

    avg_roi = sum(rois) / len(rois) if rois else 0.0
    median_roi = _median(rois) if rois else 0.0
    avg_profit = sum(profits) / len(profits) if profits else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    profit_factor = sum(profits) / sum(losses) if losses and sum(losses) > 0 else 0.0
    avg_hold_secs = int(sum(holding_times) / len(holding_times)) if holding_times else None
    best_roi = max(rois) if rois else 0.0
    worst_roi = min(rois) if rois else 0.0
    best_pnl = max(pnls) if pnls else 0.0
    worst_pnl = min(pnls) if pnls else 0.0
    max_drawdown = _max_drawdown(equity_curve)

    stats = {
        "total_trades": total_trades,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": win_rate,
        "total_pnl_usd": total_pnl,
        "average_roi": avg_roi,
        "median_roi": median_roi,
        "average_profit_usd": avg_profit,
        "average_loss_usd": avg_loss,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "avg_holding_seconds": avg_hold_secs,
        "best_trade_roi": best_roi,
        "worst_trade_roi": worst_roi,
        "best_trade_pnl_usd": best_pnl,
        "worst_trade_pnl_usd": worst_pnl,
    }
    return await _upsert_metrics(session, wallet_id, chain_key, stats)


async def _upsert_metrics(
    session: AsyncSession,
    wallet_id: int,
    chain_key: Optional[str],
    stats: dict,
) -> WalletMetrics:
    result = await session.execute(
        select(WalletMetrics).where(
            WalletMetrics.wallet_id == wallet_id,
            WalletMetrics.chain_key == chain_key,
        )
    )
    metrics = result.scalar_one_or_none()
    if not metrics:
        metrics = WalletMetrics(wallet_id=wallet_id, chain_key=chain_key)
        session.add(metrics)

    for k, v in stats.items():
        if hasattr(metrics, k):
            setattr(metrics, k, v)

    metrics.computed_at = datetime.now(timezone.utc)
    await session.flush()
    return metrics


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 != 0 else (s[mid - 1] + s[mid]) / 2


def _max_drawdown(equity: list[float]) -> float:
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd * 100  # percentage
