"""Background scheduler — periodic metrics refresh, PnL updates, score recomputation."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from src.analytics.smart_money_score import compute_score
from src.analytics.wallet_stats import compute_wallet_stats
from src.core.price_engine import PriceEngine
from src.database.connection import AsyncSessionLocal
from src.database.models import Position, PositionStatus, Wallet

logger = logging.getLogger(__name__)


class BackgroundScheduler:
    def __init__(self, price_engine: PriceEngine) -> None:
        self._price = price_engine
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._loop_unrealized_pnl(interval=60)),
            asyncio.create_task(self._loop_wallet_metrics(interval=3600)),
        ]
        logger.info("Background scheduler started")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop_unrealized_pnl(self, interval: int) -> None:
        while self._running:
            try:
                await self._refresh_unrealized_pnl()
            except Exception:
                logger.exception("Error refreshing unrealized PnL")
            await asyncio.sleep(interval)

    async def _loop_wallet_metrics(self, interval: int) -> None:
        while self._running:
            try:
                await self._recompute_all_wallet_metrics()
            except Exception:
                logger.exception("Error recomputing wallet metrics")
            await asyncio.sleep(interval)

    async def _refresh_unrealized_pnl(self) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Position).where(Position.status == PositionStatus.OPEN)
            )
            positions = result.scalars().all()

            for pos in positions:
                try:
                    # Fetch token address via join — simplified: use cached price
                    token_result = await db.execute(
                        select(__import__("src.database.models", fromlist=["Token"]).Token)
                        .where(__import__("src.database.models", fromlist=["Token"]).Token.id == pos.token_id)
                    )
                    token = token_result.scalar_one_or_none()
                    if not token:
                        continue

                    chain_result = await db.execute(
                        select(__import__("src.database.models", fromlist=["Chain"]).Chain)
                        .where(__import__("src.database.models", fromlist=["Chain"]).Chain.id == token.chain_id)
                    )
                    chain = chain_result.scalar_one_or_none()
                    chain_key = chain.chain_key if chain else "ethereum"

                    price = await self._price.get_price(token.address, chain_key)
                    if price and price > 0:
                        pos.current_price_usd = price
                        pos.current_value_usd = float(pos.quantity_remaining or 0) * price
                        cost = float(pos.average_entry_usd or 0) * float(pos.quantity_remaining or 0)
                        pos.unrealized_pnl_usd = pos.current_value_usd - cost
                        if cost > 0:
                            pos.roi_percent = (pos.unrealized_pnl_usd / cost) * 100
                except Exception:
                    logger.exception("Error updating position %d", pos.id)

            await db.commit()

    async def _recompute_all_wallet_metrics(self) -> None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Wallet).where(Wallet.enabled == True)
            )
            wallets = result.scalars().all()

            for wallet in wallets:
                try:
                    async with AsyncSessionLocal() as session:
                        await compute_wallet_stats(session, wallet.id)
                        metrics_result = await session.execute(
                            select(__import__("src.database.models", fromlist=["WalletMetrics"]).WalletMetrics)
                            .where(
                                __import__("src.database.models", fromlist=["WalletMetrics"]).WalletMetrics.wallet_id == wallet.id,
                                __import__("src.database.models", fromlist=["WalletMetrics"]).WalletMetrics.chain_key == None,
                            )
                        )
                        metrics = metrics_result.scalar_one_or_none()
                        if metrics:
                            score = compute_score(metrics)
                            wallet_upd = await session.get(Wallet, wallet.id)
                            if wallet_upd:
                                wallet_upd.smart_money_score = score.final_score
                            await session.commit()
                except Exception:
                    logger.exception("Error recomputing metrics for wallet %d", wallet.id)
