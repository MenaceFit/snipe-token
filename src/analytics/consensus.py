"""Smart Money Consensus — detects when multiple tracked wallets buy the same token."""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Token, Trade, TradeSide, Wallet

logger = logging.getLogger(__name__)


class ConsensusDetector:
    def __init__(
        self,
        redis: aioredis.Redis,
        time_window_seconds: int = 3600,
        min_wallets: int = 2,
        min_smart_score: float = 70.0,
        alert_callback=None,
    ) -> None:
        self._redis = redis
        self._window = time_window_seconds
        self._min_wallets = min_wallets
        self._min_score = min_smart_score
        self._alert_callback = alert_callback

    async def record_buy(
        self,
        session: AsyncSession,
        wallet: Wallet,
        token: "Token",  # type: ignore
        chain_key: str,
        value_usd: float,
        tx_hash: str,
    ) -> Optional[dict]:
        """Record a buy and check for consensus."""
        if (wallet.smart_money_score or 0) < self._min_score:
            return None

        key = f"consensus:{chain_key}:{token.address.lower()}"
        entry = f"{wallet.id}:{wallet.label or wallet.address[:8]}:{value_usd:.0f}:{tx_hash}"

        await self._redis.zadd(key, {entry: datetime.now(timezone.utc).timestamp()})
        await self._redis.expire(key, self._window)

        # Clean old entries
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self._window)).timestamp()
        await self._redis.zremrangebyscore(key, "-inf", cutoff)

        # Check consensus
        buyers_raw = await self._redis.zrange(key, 0, -1, withscores=True)
        buyers_raw = [(m.decode() if isinstance(m, bytes) else m, s) for m, s in buyers_raw]

        # Deduplicate by wallet_id
        seen_wallets: dict[str, dict] = {}
        for member, ts in buyers_raw:
            parts = member.split(":", 3)
            if len(parts) < 3:
                continue
            wid = parts[0]
            wlabel = parts[1]
            wvalue = float(parts[2])
            if wid not in seen_wallets:
                seen_wallets[wid] = {"label": wlabel, "value_usd": wvalue, "wallet_id": int(wid)}

        if len(seen_wallets) >= self._min_wallets:
            total_usd = sum(w["value_usd"] for w in seen_wallets.values())
            consensus_data = {
                "token_address": token.address,
                "token_symbol": token.symbol,
                "chain_key": chain_key,
                "wallet_count": len(seen_wallets),
                "wallets": list(seen_wallets.values()),
                "total_usd": total_usd,
                "confidence": "HIGH" if len(seen_wallets) >= 3 else "MEDIUM",
            }

            if self._alert_callback:
                try:
                    await self._alert_callback(consensus_data)
                except Exception as exc:
                    logger.error("Consensus alert failed", extra={"error": str(exc)})

            return consensus_data
        return None
