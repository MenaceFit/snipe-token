"""SQLAlchemy ORM models for the entire application."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---- Enums ----

class ChainType(str, enum.Enum):
    EVM = "evm"
    SOLANA = "solana"
    SUI = "sui"
    APTOS = "aptos"


class TradeSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    UNKNOWN = "unknown"


class TradeType(str, enum.Enum):
    DEX_SWAP = "dex_swap"
    BRIDGE = "bridge"
    TRANSFER = "transfer"
    AIRDROP = "airdrop"
    STAKING = "staking"
    UNSTAKING = "unstaking"
    LIQUIDITY_ADD = "liquidity_add"
    LIQUIDITY_REMOVE = "liquidity_remove"
    MINT = "mint"
    BURN = "burn"
    REWARD = "reward"
    UNKNOWN = "unknown"


class PositionStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"


class CopyMode(str, enum.Enum):
    PAPER = "paper"
    LIVE = "live"


class CopyOrderStatus(str, enum.Enum):
    PENDING = "pending"
    SIMULATED = "simulated"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class AlertType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    POSITION_UPDATE = "position_update"
    SYSTEM = "system"
    RISK = "risk"
    CONSENSUS = "consensus"
    COPY = "copy"


class RiskFlag(str, enum.Enum):
    POSSIBLE_INSIDER = "possible_insider"
    LOW_SAMPLE_SIZE = "low_sample_size"
    AIRDROP_ACTIVITY = "airdrop_activity"
    WALLET_CLUSTER = "wallet_cluster"
    CONCENTRATED_PNL = "concentrated_pnl"
    POSSIBLE_BOT = "possible_bot"
    DEPLOYER = "deployer"
    MARKET_MAKER = "market_maker"
    LOW_LIQUIDITY_TRADES = "low_liquidity_trades"
    ARTIFICIAL_VOLUME = "artificial_volume"


# ---- Tables ----

class Chain(Base):
    __tablename__ = "chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chain_key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    chain_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    chain_type: Mapped[ChainType] = mapped_column(Enum(ChainType), nullable=False, default=ChainType.EVM)
    explorer_url: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    wallets: Mapped[list["WalletChain"]] = relationship(back_populates="chain")
    tokens: Mapped[list["Token"]] = relationship(back_populates="chain")


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    group_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    smart_money_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk_flags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chains: Mapped[list["WalletChain"]] = relationship(back_populates="wallet")
    positions: Mapped[list["Position"]] = relationship(back_populates="wallet")
    metrics: Mapped[list["WalletMetrics"]] = relationship(back_populates="wallet")

    __table_args__ = (
        Index("idx_wallets_address", "address"),
        UniqueConstraint("address", name="uq_wallet_address"),
    )


class WalletChain(Base):
    """Many-to-many: wallet ↔ chain (a wallet can be on multiple chains)."""
    __tablename__ = "wallet_chains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"))
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_block: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_seen_signature: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    wallet: Mapped["Wallet"] = relationship(back_populates="chains")
    chain: Mapped["Chain"] = relationship(back_populates="wallets")

    __table_args__ = (
        UniqueConstraint("wallet_id", "chain_id", name="uq_wallet_chain"),
        Index("idx_wallet_chains_wallet", "wallet_id"),
        Index("idx_wallet_chains_chain", "chain_id"),
    )


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id", ondelete="CASCADE"))
    symbol: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decimals: Mapped[int] = mapped_column(Integer, default=18)
    is_stablecoin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_native: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    coingecko_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    market_cap_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    liquidity_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    chain: Mapped["Chain"] = relationship(back_populates="tokens")

    __table_args__ = (
        UniqueConstraint("address", "chain_id", name="uq_token_address_chain"),
        Index("idx_tokens_address", "address"),
        Index("idx_tokens_chain", "chain_id"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id"))
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    block_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    block_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    gas_used: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    gas_price_wei: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    gas_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Latency tracking
    t0_blockchain_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t1_detected_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t2_fetched_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t3_parsed_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t4_classified_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t5_db_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    t6_telegram_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    trades: Mapped[list["Trade"]] = relationship(back_populates="transaction")

    __table_args__ = (
        UniqueConstraint("tx_hash", "chain_id", name="uq_tx_hash_chain"),
        Index("idx_tx_hash", "tx_hash"),
        Index("idx_tx_wallet", "wallet_id"),
        Index("idx_tx_chain", "chain_id"),
        Index("idx_tx_timestamp", "block_timestamp"),
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trade_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, default=lambda: str(uuid.uuid4())
    )
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"))
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id"))
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"), nullable=True)

    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide), nullable=False)
    trade_type: Mapped[TradeType] = mapped_column(Enum(TradeType), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    value_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    gas_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fees_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Token swapped from/to
    from_token_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tokens.id"), nullable=True)
    to_token_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tokens.id"), nullable=True)
    from_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)
    to_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(36, 18), nullable=True)

    # PnL (filled after position update)
    realized_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roi_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    dex_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pool_address: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    log_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transaction: Mapped["Transaction"] = relationship(back_populates="trades")
    position: Mapped[Optional["Position"]] = relationship(back_populates="trades")

    __table_args__ = (
        Index("idx_trades_wallet", "wallet_id"),
        Index("idx_trades_chain", "chain_id"),
        Index("idx_trades_token", "token_id"),
        Index("idx_trades_timestamp", "timestamp"),
        Index("idx_trades_wallet_token", "wallet_id", "token_id"),
        Index("idx_trades_side", "side"),
        UniqueConstraint("trade_uuid", name="uq_trade_uuid"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id"))
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))

    status: Mapped[PositionStatus] = mapped_column(
        Enum(PositionStatus), nullable=False, default=PositionStatus.OPEN
    )

    # Entry info
    entry_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    average_entry_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    first_buy_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_buy_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sell_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Quantities
    total_bought_quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=Decimal(0))
    total_sold_quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=Decimal(0))
    current_quantity: Mapped[Decimal] = mapped_column(Numeric(36, 18), default=Decimal(0))
    percentage_sold: Mapped[float] = mapped_column(Float, default=0.0)

    # USD values
    total_invested_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_received_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_fees_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # PnL
    realized_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    roi_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Current market data (updated periodically)
    current_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_value_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Last Telegram alert
    last_alert_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_alert_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # FIFO lots (JSON list of {qty, price, timestamp})
    fifo_lots: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    wallet: Mapped["Wallet"] = relationship(back_populates="positions")
    trades: Mapped[list["Trade"]] = relationship(back_populates="position")

    __table_args__ = (
        Index("idx_positions_wallet", "wallet_id"),
        Index("idx_positions_token", "token_id"),
        Index("idx_positions_chain", "chain_id"),
        Index("idx_positions_status", "status"),
        Index("idx_positions_wallet_token", "wallet_id", "token_id"),
        UniqueConstraint("wallet_id", "chain_id", "token_id", name="uq_position_wallet_chain_token"),
    )


class WalletMetrics(Base):
    """Aggregated performance metrics per wallet (and optionally per chain)."""
    __tablename__ = "wallet_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"))
    chain_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # null = all chains

    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0.0)

    total_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    average_roi: Mapped[float] = mapped_column(Float, default=0.0)
    median_roi: Mapped[float] = mapped_column(Float, default=0.0)
    average_profit_usd: Mapped[float] = mapped_column(Float, default=0.0)
    average_loss_usd: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0.0)
    max_drawdown: Mapped[float] = mapped_column(Float, default=0.0)
    avg_holding_seconds: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    best_trade_roi: Mapped[float] = mapped_column(Float, default=0.0)
    worst_trade_roi: Mapped[float] = mapped_column(Float, default=0.0)
    best_trade_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)
    worst_trade_pnl_usd: Mapped[float] = mapped_column(Float, default=0.0)

    smart_money_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    score_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    wallet: Mapped["Wallet"] = relationship(back_populates="metrics")

    __table_args__ = (
        Index("idx_wallet_metrics_wallet", "wallet_id"),
        UniqueConstraint("wallet_id", "chain_key", name="uq_metrics_wallet_chain"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType), nullable=False)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    trade_id: Mapped[Optional[int]] = mapped_column(ForeignKey("trades.id"), nullable=True)
    position_id: Mapped[Optional[int]] = mapped_column(ForeignKey("positions.id"), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_alerts_type", "alert_type"),
        Index("idx_alerts_wallet", "wallet_id"),
        Index("idx_alerts_created", "created_at"),
    )


class CopyOrder(Base):
    __tablename__ = "copy_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    mode: Mapped[CopyMode] = mapped_column(Enum(CopyMode), nullable=False)
    status: Mapped[CopyOrderStatus] = mapped_column(
        Enum(CopyOrderStatus), nullable=False, default=CopyOrderStatus.PENDING
    )
    followed_wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    followed_trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id"))
    chain_id: Mapped[int] = mapped_column(ForeignKey("chains.id"))
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))

    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide), nullable=False)
    copy_percent: Mapped[float] = mapped_column(Float, nullable=False)
    target_amount_usd: Mapped[float] = mapped_column(Float, nullable=False)

    executed_amount_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    executed_tx_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    block_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Simulated PnL (paper mode)
    simulated_pnl_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    simulated_roi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_copy_orders_wallet", "followed_wallet_id"),
        Index("idx_copy_orders_status", "status"),
    )


class WalletCluster(Base):
    __tablename__ = "wallet_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    wallet_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallets.id"), nullable=True)
    token_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tokens.id"), nullable=True)
    copy_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("copy_orders.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), default="medium")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_risk_events_created", "created_at"),)


class TokenMetrics(Base):
    __tablename__ = "token_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id", ondelete="CASCADE"), unique=True)
    total_buys: Mapped[int] = mapped_column(Integer, default=0)
    total_sells: Mapped[int] = mapped_column(Integer, default=0)
    unique_wallets: Mapped[int] = mapped_column(Integer, default=0)
    avg_roi: Mapped[float] = mapped_column(Float, default=0.0)
    total_volume_usd: Mapped[float] = mapped_column(Float, default=0.0)
    smart_wallet_buys: Mapped[int] = mapped_column(Integer, default=0)
    last_smart_buy_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("idx_token_metrics_token", "token_id"),)


class PnLEvent(Base):
    """Historical snapshots of position PnL for charting."""
    __tablename__ = "pnl_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id"))
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))
    token_id: Mapped[int] = mapped_column(ForeignKey("tokens.id"))
    price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False)
    roi_percent: Mapped[float] = mapped_column(Float, nullable=False)
    cumulative_realized_pnl_usd: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_pnl_events_wallet", "wallet_id"),
        Index("idx_pnl_events_position", "position_id"),
        Index("idx_pnl_events_recorded", "recorded_at"),
    )
