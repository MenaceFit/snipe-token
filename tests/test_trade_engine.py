"""Unit tests for trade classification engine."""
from __future__ import annotations

from decimal import Decimal

import pytest

from src.chains.base_adapter import ParsedSwap
from src.core.trade_engine import TradeClassification, classify_swap

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
NATIVE = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
TOKEN = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
OTHER_TOKEN = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

STABLES = {USDC, USDT}


def _make_swap(
    token_in: str,
    token_out: str,
    amount_in: float = 100.0,
    amount_out: float = 1000.0,
    symbol_in: str = "TKN",
    symbol_out: str = "TKN2",
) -> ParsedSwap:
    return ParsedSwap(
        tx_hash="0x" + "a" * 64,
        chain_key="ethereum",
        wallet_address="0x" + "b" * 40,
        dex_name="uniswap_v3",
        pool_address="0x" + "c" * 40,
        token_in_address=token_in,
        token_in_amount=Decimal(str(amount_in)),
        token_in_symbol=symbol_in,
        token_out_address=token_out,
        token_out_amount=Decimal(str(amount_out)),
        token_out_symbol=symbol_out,
        fee_amount=None,
        fee_token_address=None,
        block_number=None,
        block_timestamp=None,
    )


def test_stable_in_token_out_is_buy():
    swap = _make_swap(USDC, TOKEN, amount_in=100.0, amount_out=1000.0, symbol_in="USDC", symbol_out="TKN")
    result = classify_swap(swap, stablecoin_addresses=STABLES, wrapped_native=WETH, native_address=NATIVE)
    assert result.classification == TradeClassification.BUY
    assert result.confidence >= 0.9
    assert result.base_token_address == TOKEN
    assert abs(result.price_usd - 0.1) < 0.001


def test_token_in_stable_out_is_sell():
    swap = _make_swap(TOKEN, USDC, amount_in=1000.0, amount_out=100.0, symbol_in="TKN", symbol_out="USDC")
    result = classify_swap(swap, stablecoin_addresses=STABLES, wrapped_native=WETH, native_address=NATIVE)
    assert result.classification == TradeClassification.SELL
    assert result.base_token_address == TOKEN


def test_native_in_token_out_is_buy():
    swap = _make_swap(WETH, TOKEN, amount_in=1.0, amount_out=5000.0, symbol_in="WETH", symbol_out="TKN")
    result = classify_swap(swap, stablecoin_addresses=STABLES, wrapped_native=WETH, native_address=NATIVE)
    assert result.classification == TradeClassification.BUY


def test_stable_to_stable_is_skipped():
    swap = _make_swap(USDC, USDT, symbol_in="USDC", symbol_out="USDT")
    result = classify_swap(swap, stablecoin_addresses=STABLES)
    assert result.classification == TradeClassification.STABLE_SWAP


def test_wrap_unwrap_is_skipped():
    swap = _make_swap(NATIVE, WETH, symbol_in="ETH", symbol_out="WETH")
    result = classify_swap(swap, stablecoin_addresses=STABLES, wrapped_native=WETH, native_address=NATIVE)
    assert result.classification == TradeClassification.WRAP_UNWRAP


def test_token_to_token_is_buy_with_lower_confidence():
    swap = _make_swap(TOKEN, OTHER_TOKEN)
    result = classify_swap(swap, stablecoin_addresses=STABLES, wrapped_native=WETH, native_address=NATIVE)
    assert result.classification == TradeClassification.BUY
    assert result.confidence < 0.9


def test_sell_price_calculation():
    # Selling 1000 tokens for 200 USDC → price = 200/1000 = 0.2
    swap = _make_swap(TOKEN, USDC, amount_in=1000.0, amount_out=200.0, symbol_in="TKN", symbol_out="USDC")
    result = classify_swap(swap, stablecoin_addresses=STABLES)
    assert result.classification == TradeClassification.SELL
    assert abs(result.price_usd - 0.2) < 0.001
    assert abs(result.quote_amount_usd - 200.0) < 0.01
