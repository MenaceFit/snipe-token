"""Backtesting engine — simulates copy trading on historical data."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.analytics.smart_money_score import compute_score
from src.database.connection import AsyncSessionLocal
from src.database.models import Position, PositionStatus, Trade, TradeSide, Wallet, WalletMetrics

logger = logging.getLogger(__name__)

PERIOD_MAP = {
    "7d": 7, "14d": 14, "30d": 30, "60d": 60, "90d": 90, "180d": 180, "365d": 365
}


class BacktestEngine:
    async def run(
        self,
        wallet_address: str,
        period: str,
        initial_capital_usd: float = 10_000.0,
        copy_pct: float = 10.0,
    ) -> Optional[dict]:
        days = PERIOD_MAP.get(period.lower())
        if not days:
            return None

        async with AsyncSessionLocal() as session:
            wallet = await session.execute(
                select(Wallet).where(Wallet.address == wallet_address.lower())
            )
            wallet = wallet.scalar_one_or_none()
            if not wallet:
                return None

            cutoff = datetime.now(timezone.utc) - timedelta(days=days)

            # Get all closed positions in period
            positions = await session.execute(
                select(Position).where(
                    Position.wallet_id == wallet.id,
                    Position.status == PositionStatus.CLOSED,
                    Position.first_buy_at >= cutoff,
                    Position.realized_pnl_usd.isnot(None),
                )
            )
            positions = list(positions.scalars().all())

            if not positions:
                return None

            capital = initial_capital_usd
            equity_curve = [capital]
            rois: list[float] = []
            pnls: list[float] = []
            winning = 0
            losing = 0
            holding_times: list[int] = []

            for pos in positions:
                roi = pos.roi_percent or 0.0
                pnl = pos.realized_pnl_usd or 0.0
                # Scale PnL to copy_pct
                scaled_pnl = pnl * (copy_pct / 100)

                capital += scaled_pnl
                equity_curve.append(capital)
                rois.append(roi)
                pnls.append(scaled_pnl)

                if scaled_pnl > 0:
                    winning += 1
                elif scaled_pnl < 0:
                    losing += 1

                if pos.first_buy_at and pos.closed_at:
                    hold_secs = int((pos.closed_at - pos.first_buy_at).total_seconds())
                    holding_times.append(hold_secs)

            total_trades = len(positions)
            win_rate = winning / total_trades * 100 if total_trades else 0
            avg_roi = sum(rois) / len(rois) if rois else 0
            total_pnl = sum(pnls)

            # Max drawdown
            peak = equity_curve[0]
            max_dd = 0.0
            for val in equity_curve:
                peak = max(peak, val)
                dd = (peak - val) / peak * 100 if peak > 0 else 0
                max_dd = max(max_dd, dd)

            profits = [p for p in pnls if p > 0]
            losses = [abs(p) for p in pnls if p < 0]
            profit_factor = sum(profits) / sum(losses) if losses and sum(losses) > 0 else 0.0

            # Quick score based on backtest results
            score_approx = min(100, (
                win_rate * 0.4 +
                min(100, avg_roi * 0.5) * 0.3 +
                (100 - min(100, max_dd * 2)) * 0.3
            ))

            return {
                "label": wallet.label or wallet.address[:10],
                "address": wallet.address,
                "period": period,
                "trades": total_trades,
                "win_rate": win_rate,
                "avg_roi": avg_roi,
                "total_pnl": total_pnl,
                "starting_capital": initial_capital_usd,
                "ending_capital": capital,
                "roi_total": (capital - initial_capital_usd) / initial_capital_usd * 100,
                "max_dd": max_dd,
                "best_roi": max(rois) if rois else 0,
                "worst_roi": min(rois) if rois else 0,
                "profit_factor": profit_factor,
                "score": score_approx,
                "avg_hold_seconds": int(sum(holding_times) / len(holding_times)) if holding_times else None,
                "equity_curve": equity_curve,
            }
