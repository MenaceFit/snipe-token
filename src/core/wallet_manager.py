"""Wallet manager — tracks all wallets, manages chain subscriptions."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import redis.asyncio as aioredis

from src.chains.base_adapter import ChainAdapter, RawTransaction, WalletEventCallback
from src.config import get_settings

if TYPE_CHECKING:
    from src.core.transaction_engine import TransactionEngine

logger = logging.getLogger(__name__)

settings = get_settings()


class WalletManager:
    """
    Central registry of tracked wallets + chain adapters.
    Routes incoming chain events to the TransactionEngine.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        transaction_engine: Optional["TransactionEngine"] = None,
    ) -> None:
        self._redis = redis
        self._tx_engine = transaction_engine
        self._adapters: dict[str, ChainAdapter] = {}
        self._wallet_chains: dict[str, set[str]] = {}  # wallet_address -> set of chain_keys
        self._event_queue: asyncio.Queue[RawTransaction] = asyncio.Queue(maxsize=10_000)
        self._worker_task: Optional[asyncio.Task] = None

    def set_transaction_engine(self, engine: "TransactionEngine") -> None:
        self._tx_engine = engine

    def register_adapter(self, chain_key: str, adapter: ChainAdapter) -> None:
        self._adapters[chain_key] = adapter

    async def start(self) -> None:
        for chain_key, adapter in self._adapters.items():
            await adapter.start()
            logger.info("Adapter started", extra={"chain": chain_key})

        # Re-subscribe all tracked wallets from Redis
        await self._restore_subscriptions()

        self._worker_task = asyncio.create_task(self._event_worker(), name="wallet-manager-worker")
        logger.info("WalletManager started")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        for adapter in self._adapters.values():
            await adapter.stop()

    async def add_wallet(self, wallet_address: str, chain_keys: list[str]) -> None:
        wallet_address = wallet_address.lower()
        self._wallet_chains.setdefault(wallet_address, set()).update(chain_keys)

        for chain_key in chain_keys:
            adapter = self._adapters.get(chain_key)
            if adapter:
                await adapter.subscribe_wallet(wallet_address, self._make_callback(wallet_address))
                await self._redis.sadd(f"wallet:chains:{wallet_address}", chain_key)
                await self._redis.sadd(f"chain:wallets:{chain_key}", wallet_address)
                logger.info(
                    "Wallet subscribed",
                    extra={"wallet": wallet_address, "chain": chain_key},
                )
            else:
                logger.warning(
                    "No adapter for chain",
                    extra={"chain": chain_key, "wallet": wallet_address},
                )

    async def remove_wallet(self, wallet_address: str, chain_keys: Optional[list[str]] = None) -> None:
        wallet_address = wallet_address.lower()
        targets = chain_keys or list(self._wallet_chains.get(wallet_address, set()))
        for chain_key in targets:
            adapter = self._adapters.get(chain_key)
            if adapter:
                await adapter.unsubscribe_wallet(wallet_address)
            await self._redis.srem(f"wallet:chains:{wallet_address}", chain_key)
            await self._redis.srem(f"chain:wallets:{chain_key}", wallet_address)
            self._wallet_chains.get(wallet_address, set()).discard(chain_key)

    def _make_callback(self, wallet_address: str) -> WalletEventCallback:
        def callback(raw_tx: RawTransaction) -> None:
            try:
                self._event_queue.put_nowait(raw_tx)
            except asyncio.QueueFull:
                logger.warning("Event queue full, dropping event", extra={"wallet": wallet_address})
        return callback

    async def _event_worker(self) -> None:
        while True:
            try:
                raw_tx = await self._event_queue.get()
                if self._tx_engine:
                    asyncio.create_task(
                        self._tx_engine.process(raw_tx),
                        name=f"tx-{raw_tx.tx_hash[:8]}",
                    )
                self._event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Event worker error", extra={"error": str(exc)})

    async def _restore_subscriptions(self) -> None:
        """On startup, re-subscribe all wallets stored in Redis."""
        try:
            chain_keys = list(self._adapters.keys())
            for chain_key in chain_keys:
                wallets_raw = await self._redis.smembers(f"chain:wallets:{chain_key}")
                wallets = [w.decode() if isinstance(w, bytes) else w for w in wallets_raw]
                for wallet in wallets:
                    adapter = self._adapters.get(chain_key)
                    if adapter:
                        await adapter.subscribe_wallet(wallet, self._make_callback(wallet))
                        self._wallet_chains.setdefault(wallet, set()).add(chain_key)
            logger.info("Subscriptions restored from Redis", extra={"count": sum(len(v) for v in self._wallet_chains.values())})
        except Exception as exc:
            logger.warning("Could not restore subscriptions", extra={"error": str(exc)})

    async def get_adapter(self, chain_key: str) -> Optional[ChainAdapter]:
        return self._adapters.get(chain_key)

    async def health_check(self) -> dict[str, bool]:
        result = {}
        for chain_key, adapter in self._adapters.items():
            result[chain_key] = await adapter.is_healthy()
        return result

    def get_tracked_wallets(self) -> dict[str, set[str]]:
        return dict(self._wallet_chains)

    def queue_size(self) -> int:
        return self._event_queue.qsize()
