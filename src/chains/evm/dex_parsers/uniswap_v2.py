"""Uniswap V2-style swap parser (covers Uniswap V2, SushiSwap, PancakeSwap V2, etc.)."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from eth_abi import decode as abi_decode

# Swap(address indexed sender, uint amount0In, uint amount1In, uint amount0Out, uint amount1Out, address indexed to)
SWAP_TOPIC = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"

PAIR_ABI_MINIMAL = [
    {"constant": True, "inputs": [], "name": "token0", "outputs": [{"name": "", "type": "address"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "token1", "outputs": [{"name": "", "type": "address"}], "type": "function"},
]


def decode_swap_log(log: dict) -> Optional[dict]:
    """Return decoded swap amounts from a V2 Swap log, or None if not a Swap event."""
    topics = log.get("topics", [])
    if not topics or topics[0].lower() != SWAP_TOPIC:
        return None
    try:
        data = bytes.fromhex(log["data"][2:] if log["data"].startswith("0x") else log["data"])
        amount0In, amount1In, amount0Out, amount1Out = abi_decode(
            ["uint256", "uint256", "uint256", "uint256"], data
        )
        return {
            "amount0In": amount0In,
            "amount1In": amount1In,
            "amount0Out": amount0Out,
            "amount1Out": amount1Out,
            "pair_address": log["address"].lower(),
        }
    except Exception:
        return None


def classify_swap_direction(swap_data: dict, token0: str, token1: str) -> Optional[dict]:
    """Determine which token was sold and which was bought."""
    a0in = swap_data["amount0In"]
    a1in = swap_data["amount1In"]
    a0out = swap_data["amount0Out"]
    a1out = swap_data["amount1Out"]

    # Exactly one pair should be non-zero
    if a0in > 0 and a1out > 0:
        return {"token_in": token0, "amount_in": a0in, "token_out": token1, "amount_out": a1out}
    elif a1in > 0 and a0out > 0:
        return {"token_in": token1, "amount_in": a1in, "token_out": token0, "amount_out": a0out}
    return None
