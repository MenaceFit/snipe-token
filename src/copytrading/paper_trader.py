"""Paper trading — simulates copy trades without executing anything real."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.risk_engine import RiskEngine
from src.database.connection import AsyncSessionLocal
from src.database.models import CopyMode, CopyOrder, CopyOrderStatus, TradeSide
from src.telegram.alerts import format_paper_trade

logger = logging.getLogger(__name__)
settings = get_settings()


class PaperTrader:
    """
    Simulates copy trades:
    - No real transactions
    - Records simulated positions in copy_orders
    - Tracks simulated PnL
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        redis: aioredis.Redis,
        default_amount_usd: float = 100.0,
        copy_pct: float = 5.0,
        min_wallet_score: float = 70.0,
        alert_callback=None,
    ) -> None:
        self._risk = risk_engine
        self._redis = redis
        self._default_amount = default_amount_usd
        self._copy_pct = copy_pct
        self._min_score = min_wallet_score
        self._alert_callback = alert_callback

    async def process_trade(
        self,
        session: AsyncSession,
        followed_wallet_id: int,
        followed_trade_id: int,
        chain_id: int,
        token_id: int,
        token_address: str,
        chain_key: str,
        side: TradeSide,
        price_usd: Optional[float],
        wallet_score: float,
        wallet_label: str,
        token_symbol: str,
        chain_name: str,
    ) -> Optional[CopyOrder]:

        if wallet_score < self._min_score:
            return None

        # Risk check
        risk_report = await self._risk.check_token(token_address, chain_key)
        if not self._risk.is_safe_to_trade(risk_report):
            logger.info(
                "Paper trade blocked by risk",
                extra={"token": token_address, "flags": risk_report.flags},
            )
            from src.telegram.alerts import format_risk_blocked
            if self._alert_callback:
                blocked_msg = format_risk_blocked(
                    token_symbol=token_symbol,
                    reason="High-risk token",
                    flags=risk_report.flags,
                )
                await self._alert_callback(blocked_msg, is_raw=True)
            return None

        amount_usd = self._default_amount * (self._copy_pct / 100) * (wallet_score / 100)

        order = CopyOrder(
            mode=CopyMode.PAPER,
            status=CopyOrderStatus.SIMULATED,
            followed_wallet_id=followed_wallet_id,
            followed_trade_id=followed_trade_id,
            chain_id=chain_id,
            token_id=token_id,
            side=side,
            copy_percent=self._copy_pct,
            target_amount_usd=amount_usd,
            executed_amount_usd=amount_usd,
            executed_price_usd=price_usd,
            executed_at=datetime.now(timezone.utc),
        )
        session.add(order)
        await session.flush()

        # Send paper trade notification
        if self._alert_callback and side == TradeSide.BUY:
            msg = format_paper_trade(
                wallet_label=wallet_label,
                token_symbol=token_symbol,
                token_address=token_address,
                chain_name=chain_name,
                simulated_amount_usd=amount_usd,
                entry_price=price_usd,
                copy_pct=self._copy_pct,
            )
            await self._alert_callback(msg, is_raw=True)

        logger.info(
            "Paper trade simulated",
            extra={
                "wallet": wallet_label,
                "token": token_symbol,
                "amount_usd": amount_usd,
                "side": side,
            },
        )
        return order
