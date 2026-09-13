"""Abstract base class every chain adapter must implement."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Callable, Optional


@dataclass
class TokenInfo:
    address: str
    symbol: str
    name: str
    decimals: int
    chain_key: str
    is_stablecoin: bool = False
    is_native: bool = False
    logo_url: Optional[str] = None


@dataclass
class PriceData:
    token_address: str
    chain_key: str
    price_usd: float
    liquidity_usd: Optional[float]
    market_cap_usd: Optional[float]
    source: str
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    confidence: float = 1.0  # 0-1


@dataclass
class RawTransaction:
    """Chain-agnostic container for a raw transaction before parsing."""
    tx_hash: str
    chain_key: str
    wallet_address: str
    block_number: Optional[int]
    block_timestamp: Optional[datetime]
    gas_used: Optional[int]
    gas_price: Optional[int]
    raw: dict[str, Any]  # Original data from RPC
    detected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ParsedTransfer:
    """A single token transfer within a transaction."""
    from_address: str
    to_address: str
    token_address: str
    amount_raw: int
    amount_decimal: Decimal
    log_index: int = 0


@dataclass
class ParsedSwap:
    """A fully parsed DEX swap."""
    tx_hash: str
    chain_key: str
    wallet_address: str
    dex_name: str
    pool_address: str

    token_in_address: str
    token_in_amount: Decimal
    token_in_symbol: str

    token_out_address: str
    token_out_amount: Decimal
    token_out_symbol: str

    fee_amount: Optional[Decimal]
    fee_token_address: Optional[str]

    block_number: Optional[int]
    block_timestamp: Optional[datetime]
    log_index: int = 0

    price_impact_bps: Optional[int] = None
    slippage_bps: Optional[int] = None


@dataclass
class WalletBalance:
    wallet_address: str
    token_address: str
    chain_key: str
    amount_decimal: Decimal
    amount_usd: Optional[float]
    fetched_at: datetime = field(default_factory=datetime.utcnow)


# Callback type: receives a RawTransaction when a wallet event fires
WalletEventCallback = Callable[[RawTransaction], None]


class ChainAdapter(abc.ABC):
    """Interface every blockchain adapter must satisfy."""

    chain_key: str  # e.g. "base", "ethereum", "solana"
    chain_type: str  # "evm" | "solana" | ...

    # ---- Subscription ----

    @abc.abstractmethod
    async def start(self) -> None:
        """Connect WebSocket(s) and begin streaming events."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Cleanly disconnect and release resources."""

    @abc.abstractmethod
    async def subscribe_wallet(self, wallet_address: str, callback: WalletEventCallback) -> None:
        """Register a callback to receive events for this wallet."""

    @abc.abstractmethod
    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        """Remove a wallet subscription."""

    # ---- Transaction fetching ----

    @abc.abstractmethod
    async def get_transaction(self, tx_hash: str) -> Optional[dict[str, Any]]:
        """Fetch full transaction data from RPC."""

    @abc.abstractmethod
    async def get_transaction_receipt(self, tx_hash: str) -> Optional[dict[str, Any]]:
        """Fetch transaction receipt / logs from RPC."""

    @abc.abstractmethod
    async def parse_transaction(self, tx_data: dict[str, Any], receipt: dict[str, Any]) -> list[ParsedSwap]:
        """Extract all swaps from a transaction + receipt."""

    # ---- Token data ----

    @abc.abstractmethod
    async def get_token_metadata(self, token_address: str) -> Optional[TokenInfo]:
        """Fetch symbol, name, decimals for a token."""

    @abc.abstractmethod
    async def get_token_price(self, token_address: str) -> Optional[PriceData]:
        """Get current USD price for a token."""

    @abc.abstractmethod
    async def get_balance(self, wallet_address: str, token_address: str) -> Optional[WalletBalance]:
        """Get on-chain balance of token for wallet."""

    # ---- Block info ----

    @abc.abstractmethod
    async def get_latest_block(self) -> int:
        """Return current block number (or slot for Solana)."""

    @abc.abstractmethod
    async def get_block_timestamp(self, block_number: int) -> Optional[datetime]:
        """Return timestamp for a block."""

    # ---- Health ----

    @abc.abstractmethod
    async def is_healthy(self) -> bool:
        """Return True if RPC/WebSocket is responsive."""

    # ---- Backfill ----

    @abc.abstractmethod
    async def get_wallet_transactions(
        self,
        wallet_address: str,
        from_block: Optional[int] = None,
        limit: int = 100,
    ) -> list[RawTransaction]:
        """Fetch historical transactions for a wallet (used for backfill)."""
