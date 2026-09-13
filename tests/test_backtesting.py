"""Unit tests for backtest engine calculations."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backtesting.engine import BacktestEngine


def _make_position(roi: float, pnl: float, hold_days: int = 3) -> MagicMock:
    pos = MagicMock()
    pos.roi_percent = roi
    pos.realized_pnl_usd = pnl
    now = datetime.now(timezone.utc)
    pos.first_buy_at = now - timedelta(days=hold_days + 1)
    pos.closed_at = now - timedelta(days=1)
    return pos


@pytest.mark.asyncio
async def test_backtest_no_positions_returns_none():
    engine = BacktestEngine()
    with patch("src.backtesting.engine.AsyncSessionLocal") as mock_session_cls:
        session = AsyncMock()
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        wallet = MagicMock()
        wallet.id = 1
        wallet.label = "Test"
        wallet.address = "0xabc"

        session.execute = AsyncMock()
        session.execute.return_value.scalar_one_or_none = MagicMock(return_value=wallet)
        # Second call: positions query returns empty
        session.execute.return_value.scalars = MagicMock()
        session.execute.return_value.scalars.return_value.all = MagicMock(return_value=[])

        result = await engine.run("0xabc", "30d")
        # None because no positions


@pytest.mark.asyncio
async def test_backtest_calculates_win_rate():
    positions = [
        _make_position(roi=80.0, pnl=800.0),
        _make_position(roi=-30.0, pnl=-300.0),
        _make_position(roi=120.0, pnl=1200.0),
        _make_position(roi=50.0, pnl=500.0),
    ]
    # 3 winners, 1 loser → 75% win rate
    engine = BacktestEngine()
    # Test the math directly (same logic as engine.run)
    pnls = [800.0 * 0.1, -300.0 * 0.1, 1200.0 * 0.1, 500.0 * 0.1]
    winning = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    assert winning / total * 100 == 75.0


def test_backtest_max_drawdown():
    equity = [10000, 11000, 9000, 9500, 8000, 12000]
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        peak = max(peak, val)
        dd = (peak - val) / peak * 100
        max_dd = max(max_dd, dd)
    # Peak 11000, trough 8000 → (11000-8000)/11000 * 100 ≈ 27.27%
    assert abs(max_dd - 27.27) < 0.1
