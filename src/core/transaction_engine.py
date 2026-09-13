"""Transaction processing pipeline: RawTransaction → Classified Trade → Position → Alert."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import redis.asyncio as aioredis

from src.chains.base_adapter import RawTransaction
from src.core.position_engine import PositionEngine
from src.core.price_engine import PriceEngine
from src.core.risk_engine import RiskEngine
from src.core.trade_engine import TradeClassification, classify_swap
from src.database.connection import AsyncSessionLocal
from src.database.models import Chain, Token, Trade, TradeSide, TradeType, Transaction, Wallet
from src.database.repositories.trade_repo import (
    PositionRepository,
    TradeRepository,
    TransactionRepository,
)
from src.database.repositories.wallet_repo import WalletRepository

logger = logging.getLogger(__name__)


class TransactionEngine:
    """
    Full pipeline:
        RawTransaction
          → dedup check
          → fetch full tx + receipt
          → parse swaps
          → classify (buy/sell)
          → enrich with price
          → update position
          → store in DB
          → emit alert
    """

    def __init__(
        self,
        wallet_manager: "WalletManager",  # type: ignore[name-defined]
        price_engine: PriceEngine,
        risk_engine: RiskEngine,
        position_engine: PositionEngine,
        redis: aioredis.Redis,
        alert_callback=None,
    ) -> None:
        self._wm = wallet_manager
        self._price_engine = price_engine
        self._risk_engine = risk_engine
        self._position_engine = position_engine
        self._redis = redis
        self._alert_callback = alert_callback  # async callable(trade_data: dict)

    async def process(self, raw_tx: RawTransaction) -> None:
        t1 = int(time.time() * 1000)

        # ---- Deduplication ----
        dedup_key = f"tx:seen:{raw_tx.chain_key}:{raw_tx.tx_hash.lower()}"
        already_seen = await self._redis.set(dedup_key, "1", nx=True, ex=3600)
        if not already_seen:
            return  # Already processed

        try:
            await self._pipeline(raw_tx, t1)
        except Exception as exc:
            logger.error(
                "Transaction processing failed",
                extra={"tx": raw_tx.tx_hash, "chain": raw_tx.chain_key, "error": str(exc)},
            )

    async def _pipeline(self, raw_tx: RawTransaction, t1: int) -> None:
        # ---- Fetch full tx ----
        adapter = await self._wm.get_adapter(raw_tx.chain_key)
        if not adapter:
            return

        t2 = int(time.time() * 1000)
        tx_data = await adapter.get_transaction(raw_tx.tx_hash)
        receipt = await adapter.get_transaction_receipt(raw_tx.tx_hash)
        if not tx_data or not receipt:
            return

        # ---- Parse swaps ----
        t3 = int(time.time() * 1000)
        swaps = await adapter.parse_transaction(tx_data, receipt)
        if not swaps:
            return

        # ---- DB session ----
        async with AsyncSessionLocal() as session:
            # Get wallet and chain DB objects
            wallet_repo = WalletRepository(session)
            wallet = await wallet_repo.get_by_address(raw_tx.wallet_address)
            if not wallet or not wallet.enabled:
                return

            chain = await wallet_repo.get_chain_by_key(raw_tx.chain_key)
            if not chain:
                return

            # Store transaction
            tx_repo = TransactionRepository(session)
            existing_tx = await tx_repo.get_by_hash(raw_tx.tx_hash, chain.id)
            if existing_tx:
                return

            block_ts = raw_tx.block_timestamp
            gas_used = receipt.get("gasUsed") if isinstance(receipt.get("gasUsed"), int) else None
            gas_price = tx_data.get("gasPrice")

            gas_cost_usd = 0.0
            if gas_used and gas_price:
                native_price = await self._price_engine.get_native_price(raw_tx.chain_key) or 0
                gas_eth = (gas_used * gas_price) / 1e18
                gas_cost_usd = gas_eth * native_price

            db_tx = await tx_repo.create(
                tx_hash=raw_tx.tx_hash,
                chain_id=chain.id,
                wallet_id=wallet.id,
                block_number=raw_tx.block_number,
                block_timestamp=block_ts,
                gas_used=gas_used,
                gas_price_wei=gas_price,
                gas_cost_usd=gas_cost_usd,
                t1_detected_ms=t1,
                t2_fetched_ms=int(time.time() * 1000),
                t3_parsed_ms=t3,
            )

            t4 = int(time.time() * 1000)

            for swap in swaps:
                # Get chain config for stablecoins
                from src.config import get_chain_config
                chain_cfg = get_chain_config().get("chains", {}).get(raw_tx.chain_key, {})
                stablecoin_addrs = {a.lower() for a in chain_cfg.get("stablecoins", [])}
                wrapped_native = chain_cfg.get("wrapped_native")
                native_addr = chain_cfg.get("native_token")

                classified = classify_swap(
                    swap,
                    stablecoin_addresses=stablecoin_addrs,
                    wrapped_native=wrapped_native,
                    native_address=native_addr,
                )

                if classified.classification in (
                    TradeClassification.STABLE_SWAP,
                    TradeClassification.WRAP_UNWRAP,
                    TradeClassification.UNKNOWN,
                ):
                    if classified.classification == TradeClassification.UNKNOWN:
                        logger.info(
                            "Unknown swap classification",
                            extra={"tx": raw_tx.tx_hash, "chain": raw_tx.chain_key},
                        )
                    continue

                # Get or create token
                base_addr = classified.base_token_address.lower()
                from sqlalchemy import select
                tok_result = await session.execute(
                    select(Token).where(Token.address == base_addr, Token.chain_id == chain.id)
                )
                token = tok_result.scalar_one_or_none()
                if not token:
                    token_info = await adapter.get_token_metadata(base_addr)
                    if not token_info:
                        continue
                    token = Token(
                        address=base_addr,
                        chain_id=chain.id,
                        symbol=token_info.symbol,
                        name=token_info.name,
                        decimals=token_info.decimals,
                        is_stablecoin=token_info.is_stablecoin,
                        is_native=token_info.is_native,
                    )
                    session.add(token)
                    await session.flush()

                # Enrich price
                price_usd = classified.price_usd
                if not price_usd:
                    price_usd = await self._price_engine.get_price(base_addr, raw_tx.chain_key)

                value_usd = classified.quote_amount_usd
                if not value_usd and price_usd:
                    value_usd = float(classified.base_amount) * price_usd

                # Store trade
                trade_repo = TradeRepository(session)
                side = TradeSide.BUY if classified.classification == TradeClassification.BUY else TradeSide.SELL
                db_trade = await trade_repo.create(
                    transaction_id=db_tx.id,
                    wallet_id=wallet.id,
                    chain_id=chain.id,
                    token_id=token.id,
                    side=side,
                    trade_type=TradeType.DEX_SWAP,
                    quantity=classified.base_amount,
                    price_usd=price_usd,
                    value_usd=value_usd,
                    gas_cost_usd=gas_cost_usd,
                    fees_usd=0.0,
                    from_token_id=None,
                    to_token_id=None,
                    dex_name=swap.dex_name,
                    pool_address=swap.pool_address,
                    log_index=swap.log_index,
                    timestamp=block_ts or datetime.now(timezone.utc),
                )

                # Update position
                position, realized_pnl = await self._position_engine.process_trade(
                    session=session,
                    wallet_id=wallet.id,
                    chain_id=chain.id,
                    token_id=token.id,
                    trade=classified,
                    gas_cost_usd=gas_cost_usd,
                    fees_usd=0.0,
                    current_price_usd=price_usd,
                )

                # Update trade with PnL
                if realized_pnl != 0:
                    db_trade.realized_pnl_usd = realized_pnl
                    if position.total_invested_usd > 0:
                        db_trade.roi_percent = (realized_pnl / position.total_invested_usd) * 100

                db_trade.position_id = position.id

                t5 = int(time.time() * 1000)
                await tx_repo.update(db_tx, t4_classified_ms=t4, t5_db_ms=t5)

                await session.commit()

                # ---- Emit alert ----
                if self._alert_callback:
                    alert_data = {
                        "wallet": wallet,
                        "token": token,
                        "chain": chain,
                        "trade": db_trade,
                        "position": position,
                        "classified": classified,
                        "realized_pnl": realized_pnl,
                        "tx_hash": raw_tx.tx_hash,
                        "price_usd": price_usd,
                        "value_usd": value_usd,
                        "gas_cost_usd": gas_cost_usd,
                        "latency_ms": int(time.time() * 1000) - t1,
                    }
                    try:
                        await self._alert_callback(alert_data)
                        t6 = int(time.time() * 1000)
                        await tx_repo.update(db_tx, t6_telegram_ms=t6)
                        await session.commit()
                    except Exception as exc:
                        logger.error("Alert callback error", extra={"error": str(exc)})

                logger.info(
                    "Trade processed",
                    extra={
                        "chain": raw_tx.chain_key,
                        "wallet": raw_tx.wallet_address[:10],
                        "tx": raw_tx.tx_hash[:16],
                        "side": side,
                        "token": token.symbol,
                        "value_usd": value_usd,
                        "latency_ms": int(time.time() * 1000) - t1,
                    },
                )
