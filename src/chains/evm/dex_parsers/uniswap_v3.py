"""Uniswap V3-style swap parser."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from eth_abi import decode as abi_decode

# Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
SWAP_TOPIC_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"


def decode_v3_swap_log(log: dict) -> Optional[dict]:
    topics = log.get("topics", [])
    if not topics or topics[0].lower() != SWAP_TOPIC_V3:
        return None
    try:
        data = bytes.fromhex(log["data"][2:] if log["data"].startswith("0x") else log["data"])
        amount0, amount1, sqrtPriceX96, liquidity, tick = abi_decode(
            ["int256", "int256", "uint160", "uint128", "int24"], data
        )
        return {
            "amount0": amount0,
            "amount1": amount1,
            "pool_address": log["address"].lower(),
        }
    except Exception:
        return None


def classify_v3_swap(swap_data: dict, token0: str, token1: str) -> Optional[dict]:
    a0 = swap_data["amount0"]
    a1 = swap_data["amount1"]
    # Negative = outgoing (sold), positive = incoming (bought)
    if a0 < 0 and a1 > 0:
        return {"token_in": token1, "amount_in": abs(a1), "token_out": token0, "amount_out": abs(a0)}
    elif a1 < 0 and a0 > 0:
        return {"token_in": token0, "amount_in": abs(a0), "token_out": token1, "amount_out": abs(a1)}
    return None
