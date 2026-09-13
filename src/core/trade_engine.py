"""Trade classification engine: determines BUY / SELL / UNKNOWN from parsed swaps."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.chains.base_adapter import ParsedSwap

logger = logging.getLogger(__name__)

STABLECOIN_SYMBOLS = {"USDC", "USDT", "DAI", "BUSD", "FRAX", "LUSD", "USDE", "TUSD", "GUSD", "USDP"}
NATIVE_SYMBOLS = {"ETH", "WETH", "BNB", "WBNB", "MATIC", "WMATIC", "AVAX", "WAVAX", "SOL", "WSOL"}


class TradeClassification(str, Enum):
    BUY = "buy"
    SELL = "sell"
    STABLE_SWAP = "stable_swap"      # USDC → USDT, etc. — not a trade
    WRAP_UNWRAP = "wrap_unwrap"      # ETH ↔ WETH — not a trade
    UNKNOWN = "unknown"


@dataclass
class ClassifiedTrade:
    swap: ParsedSwap
    classification: TradeClassification
    base_token_address: str        # The "interesting" token (not stablecoin/native)
    base_token_symbol: str
    quote_token_address: str
    quote_token_symbol: str
    base_amount: Decimal
    quote_amount_usd: Optional[float]  # USD value of the quote side
    price_usd: Optional[float]         # Effective price of base token
    confidence: float                   # 0-1, how sure we are of the classification


def classify_swap(
    swap: ParsedSwap,
    stablecoin_addresses: Optional[set[str]] = None,
    wrapped_native: Optional[str] = None,
    native_address: Optional[str] = None,
) -> ClassifiedTrade:
    """
    Classify a parsed swap as BUY, SELL, STABLE_SWAP, WRAP_UNWRAP, or UNKNOWN.

    Rules:
    - If token_in is a stablecoin/native and token_out is neither → BUY
    - If token_out is a stablecoin/native and token_in is neither → SELL
    - If both are stablecoins → STABLE_SWAP (skip)
    - If one is wrapped native of the other → WRAP_UNWRAP (skip)
    - Otherwise → UNKNOWN (might still be token→token swap, classified as BUY/SELL based on context)
    """
    stables = stablecoin_addresses or set()
    t_in = swap.token_in_address.lower()
    t_out = swap.token_out_address.lower()
    s_in = swap.token_in_symbol.upper()
    s_out = swap.token_out_symbol.upper()

    def is_stable(addr: str, symbol: str) -> bool:
        return addr in stables or symbol in STABLECOIN_SYMBOLS

    def is_native_or_wrap(addr: str, symbol: str) -> bool:
        return (
            addr == (native_address or "").lower()
            or addr == (wrapped_native or "").lower()
            or symbol in NATIVE_SYMBOLS
        )

    def is_quote_token(addr: str, symbol: str) -> bool:
        return is_stable(addr, symbol) or is_native_or_wrap(addr, symbol)

    in_is_quote = is_quote_token(t_in, s_in)
    out_is_quote = is_quote_token(t_out, s_out)
    in_is_stable = is_stable(t_in, s_in)
    out_is_stable = is_stable(t_out, s_out)

    # Wrap/unwrap detection
    if wrapped_native and {t_in, t_out} == {(native_address or "").lower(), wrapped_native.lower()}:
        return ClassifiedTrade(
            swap=swap,
            classification=TradeClassification.WRAP_UNWRAP,
            base_token_address=t_in,
            base_token_symbol=s_in,
            quote_token_address=t_out,
            quote_token_symbol=s_out,
            base_amount=swap.token_in_amount,
            quote_amount_usd=None,
            price_usd=None,
            confidence=1.0,
        )

    # Stablecoin ↔ stablecoin
    if in_is_stable and out_is_stable:
        return ClassifiedTrade(
            swap=swap,
            classification=TradeClassification.STABLE_SWAP,
            base_token_address=t_in,
            base_token_symbol=s_in,
            quote_token_address=t_out,
            quote_token_symbol=s_out,
            base_amount=swap.token_in_amount,
            quote_amount_usd=float(swap.token_in_amount) if in_is_stable else None,
            price_usd=None,
            confidence=1.0,
        )

    # BUY: in=stablecoin/native, out=token
    if in_is_quote and not out_is_quote:
        # Estimate price
        price_usd = None
        quote_usd = None
        if in_is_stable:
            quote_usd = float(swap.token_in_amount)
            if swap.token_out_amount > 0:
                price_usd = float(swap.token_in_amount) / float(swap.token_out_amount)
        return ClassifiedTrade(
            swap=swap,
            classification=TradeClassification.BUY,
            base_token_address=t_out,
            base_token_symbol=s_out,
            quote_token_address=t_in,
            quote_token_symbol=s_in,
            base_amount=swap.token_out_amount,
            quote_amount_usd=quote_usd,
            price_usd=price_usd,
            confidence=0.95,
        )

    # SELL: in=token, out=stablecoin/native
    if out_is_quote and not in_is_quote:
        price_usd = None
        quote_usd = None
        if out_is_stable:
            quote_usd = float(swap.token_out_amount)
            if swap.token_in_amount > 0:
                price_usd = float(swap.token_out_amount) / float(swap.token_in_amount)
        return ClassifiedTrade(
            swap=swap,
            classification=TradeClassification.SELL,
            base_token_address=t_in,
            base_token_symbol=s_in,
            quote_token_address=t_out,
            quote_token_symbol=s_out,
            base_amount=swap.token_in_amount,
            quote_amount_usd=quote_usd,
            price_usd=price_usd,
            confidence=0.95,
        )

    # Token→Token swap: treat as SELL of in-token and BUY of out-token
    # We pick the out-token as the "base" (being acquired), classification = BUY
    if not in_is_quote and not out_is_quote:
        return ClassifiedTrade(
            swap=swap,
            classification=TradeClassification.BUY,
            base_token_address=t_out,
            base_token_symbol=s_out,
            quote_token_address=t_in,
            quote_token_symbol=s_in,
            base_amount=swap.token_out_amount,
            quote_amount_usd=None,
            price_usd=None,
            confidence=0.6,
        )

    return ClassifiedTrade(
        swap=swap,
        classification=TradeClassification.UNKNOWN,
        base_token_address=t_in,
        base_token_symbol=s_in,
        quote_token_address=t_out,
        quote_token_symbol=s_out,
        base_amount=swap.token_in_amount,
        quote_amount_usd=None,
        price_usd=None,
        confidence=0.0,
    )
