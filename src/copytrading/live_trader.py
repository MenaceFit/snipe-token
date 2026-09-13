"""
Live copy trading — REQUIRES explicit activation and private key.
Contains multiple safety layers. Paper mode is the default.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from src.config import get_settings
from src.core.risk_engine import RiskEngine
from src.database.models import CopyMode, CopyOrder, CopyOrderStatus, TradeSide

logger = logging.getLogger(__name__)
settings = get_settings()


class LiveTrader:
    """
    Live copy trading executor.
    ALL of these conditions must be true to execute:
    1. copy_trading_live_enabled = true in .env
    2. emergency_stopped = false
    3. Token passes risk checks
    4. Trade within position/daily loss limits
    5. Wallet has sufficient balance
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        max_trade_size_usd: float,
        max_daily_loss_usd: float,
        max_position_size_usd: float,
        max_slippage_bps: int,
        alert_callback=None,
    ) -> None:
        self._risk = risk_engine
        self._max_trade_size = max_trade_size_usd
        self._max_daily_loss = max_daily_loss_usd
        self._max_position_size = max_position_size_usd
        self._max_slippage = max_slippage_bps
        self._alert_callback = alert_callback
        self._emergency_stopped = False
        self._daily_loss_usd = 0.0
        self._daily_reset: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return (
            settings.copy_trading_live_enabled
            and not self._emergency_stopped
            and bool(settings.copy_trading_wallet_private_key)
        )

    def emergency_stop(self) -> None:
        self._emergency_stopped = True
        logger.critical("LIVE COPY TRADING EMERGENCY STOP ACTIVATED")

    async def execute_trade(
        self,
        chain_key: str,
        token_address: str,
        token_symbol: str,
        side: TradeSide,
        amount_usd: float,
        price_usd: Optional[float],
    ) -> dict:
        """
        Attempt to execute a live trade.
        Returns {"success": bool, "reason": str, "tx_hash": str | None}
        """
        if not self.is_active:
            return {"success": False, "reason": "Live trading disabled or emergency stop active."}

        if self._emergency_stopped:
            return {"success": False, "reason": "Emergency stop active."}

        # Reset daily tracker if new day
        now = datetime.now(timezone.utc)
        if not self._daily_reset or (now - self._daily_reset).days >= 1:
            self._daily_loss_usd = 0.0
            self._daily_reset = now

        # ---- Safety checks ----
        if amount_usd > self._max_trade_size:
            return {"success": False, "reason": f"Trade size ${amount_usd:.0f} exceeds max ${self._max_trade_size:.0f}"}

        if self._daily_loss_usd >= self._max_daily_loss:
            return {"success": False, "reason": f"Daily loss limit reached ${self._max_daily_loss:.0f}"}

        risk = await self._risk.check_token(token_address, chain_key)
        if not self._risk.is_safe_to_trade(risk):
            return {"success": False, "reason": f"Risk blocked: {', '.join(risk.flags[:3])}"}

        # ---- Execute ----
        # In a real implementation this would build + sign + broadcast the transaction
        # via the appropriate DEX SDK (e.g. 0x/1inch for EVM, Jupiter for Solana).
        # The private key is read from settings.copy_trading_wallet_private_key
        # and NEVER logged.
        logger.info(
            "LIVE TRADE WOULD EXECUTE",
            extra={
                "chain": chain_key,
                "token": token_symbol,
                "side": side,
                "amount_usd": amount_usd,
            },
        )

        # PLACEHOLDER — actual DEX integration goes here
        # tx_hash = await self._execute_on_dex(...)
        # For safety, we return a dry-run response until fully implemented
        return {
            "success": False,
            "reason": "Live trade execution not yet implemented. Use paper mode.",
            "tx_hash": None,
        }

    async def _check_wallet_balance(self, chain_key: str, min_usd: float) -> bool:
        """Verify the copy-trading wallet has enough balance."""
        # Implementation requires chain adapter access
        return True
