"""Backtesting REST endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from src.backtesting.engine import BacktestEngine

router = APIRouter(prefix="/backtest", tags=["backtesting"])

_engine = BacktestEngine()


@router.get("/")
async def run_backtest(
    wallet_address: str = Query(...),
    period: str = Query("30d"),
    initial_capital_usd: float = Query(10_000.0),
    copy_pct: float = Query(10.0, ge=0.1, le=100.0),
):
    result = await _engine.run(
        wallet_address=wallet_address,
        period=period,
        initial_capital_usd=initial_capital_usd,
        copy_pct=copy_pct,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No closed positions found for this wallet/period.",
        )
    return result
