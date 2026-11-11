"""GoPlus Security API — free honeypot/tax/ownership checker."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

GOPLUS_BASE = "https://api.gopluslabs.io/api/v1"

GOPLUS_CHAIN_MAP: dict[str, str] = {
    "ethereum": "1",
    "bsc": "56",
    "polygon": "137",
    "arbitrum": "42161",
    "optimism": "10",
    "avalanche": "43114",
    "base": "8453",
    "fantom": "250",
    "cronos": "25",
    "gnosis": "100",
    "celo": "42220",
    "moonbeam": "1284",
    "moonriver": "1285",
    "harmony": "1666600000",
    "aurora": "1313161554",
    "linea": "59144",
    "scroll": "534352",
    "zksync": "324",
}


async def check_token_safety(
    token_address: str,
    chain_key: str,
    timeout: int = 5,
) -> dict:
    """Query GoPlus for token security data. Returns safe defaults on failure."""
    chain_id = GOPLUS_CHAIN_MAP.get(chain_key.lower())
    if not chain_id:
        return _unknown_result()

    url = f"{GOPLUS_BASE}/token_security/{chain_id}"
    params = {"contract_addresses": token_address.lower()}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    return _unknown_result()
                body = await resp.json()
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("GoPlus check failed for %s: %s", token_address, exc)
        return _unknown_result()

    result = body.get("result", {})
    token_data = result.get(token_address.lower(), {})
    if not token_data:
        return _unknown_result()

    is_honeypot = token_data.get("is_honeypot") == "1"
    buy_tax = _safe_float(token_data.get("buy_tax"))
    sell_tax = _safe_float(token_data.get("sell_tax"))
    is_open_source = token_data.get("is_open_source") == "1"
    is_proxy = token_data.get("is_proxy") == "1"
    can_take_back_ownership = token_data.get("can_take_back_ownership") == "1"
    owner_change_balance = token_data.get("owner_change_balance") == "1"
    hidden_owner = token_data.get("hidden_owner") == "1"
    is_mintable = token_data.get("is_mintable") == "1"
    has_blacklist = token_data.get("is_blacklisted") == "1"
    has_whitelist = token_data.get("is_whitelisted") == "1"
    creator_percent = _safe_float(token_data.get("creator_percent"))
    holder_count = int(token_data.get("holder_count") or 0)

    flags: list[str] = []
    if is_honeypot:
        flags.append("🍯 HONEYPOT")
    if sell_tax and sell_tax > 10:
        flags.append(f"💸 Sell tax élevée: {sell_tax:.0f}%")
    if buy_tax and buy_tax > 10:
        flags.append(f"💸 Buy tax élevée: {buy_tax:.0f}%")
    if hidden_owner:
        flags.append("👁️ Owner caché")
    if can_take_back_ownership:
        flags.append("⚠️ Owner récupérable")
    if owner_change_balance:
        flags.append("⚠️ Owner peut modifier balances")
    if is_mintable:
        flags.append("🖨️ Mintable")
    if not is_open_source:
        flags.append("🔒 Code non vérifié")
    if has_blacklist:
        flags.append("🚫 Blacklist active")
    if creator_percent and creator_percent > 20:
        flags.append(f"🐳 Créateur: {creator_percent:.0f}% supply")

    if is_honeypot:
        risk_level = "CRITICAL"
    elif len([f for f in flags if "HONEYPOT" not in f]) >= 3:
        risk_level = "HIGH"
    elif flags:
        risk_level = "MEDIUM"
    else:
        risk_level = "LOW"

    return {
        "is_honeypot": is_honeypot,
        "buy_tax": buy_tax,
        "sell_tax": sell_tax,
        "risk_level": risk_level,
        "flags": flags,
        "holder_count": holder_count,
        "is_open_source": is_open_source,
        "is_mintable": is_mintable,
        "creator_percent": creator_percent,
        "checked": True,
    }


def format_safety_result(safety: dict, token_symbol: str = "") -> str:
    if not safety.get("checked"):
        return ""

    sym = token_symbol or "TOKEN"
    risk = safety.get("risk_level", "UNKNOWN")
    risk_em = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(risk, "⚪")

    lines = [
        f"🔐 <b>Sécurité — {sym}</b>",
        f"Risque: {risk_em} <b>{risk}</b>",
    ]

    bt = safety.get("buy_tax")
    st = safety.get("sell_tax")
    if bt is not None or st is not None:
        buy_str = f"{bt:.1f}%" if bt is not None else "?"
        sell_str = f"{st:.1f}%" if st is not None else "?"
        lines.append(f"Tax: Buy {buy_str} / Sell {sell_str}")

    hc = safety.get("holder_count", 0)
    if hc:
        lines.append(f"Holders: <b>{hc:,}</b>")

    flags = safety.get("flags", [])
    if flags:
        lines.append("")
        for f in flags[:5]:
            lines.append(f"  {f}")

    return "\n".join(lines)


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None and val != "" else None
    except (ValueError, TypeError):
        return None


def _unknown_result() -> dict:
    return {
        "is_honeypot": False,
        "buy_tax": None,
        "sell_tax": None,
        "risk_level": "UNKNOWN",
        "flags": [],
        "holder_count": 0,
        "is_open_source": None,
        "is_mintable": False,
        "creator_percent": None,
        "checked": False,
    }
