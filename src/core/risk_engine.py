"""Risk engine — validates tokens and wallets before copy-trading."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import aiohttp

from src.core.price_engine import PriceEngine

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    SAFE = "safe"
    CAUTION = "caution"
    HIGH_RISK = "high_risk"
    BLOCKED = "blocked"


@dataclass
class TokenRiskReport:
    token_address: str
    chain_key: str
    risk_level: RiskLevel
    score: float  # 0 = safe, 100 = dangerous
    flags: list[str] = field(default_factory=list)
    buy_tax: Optional[float] = None
    sell_tax: Optional[float] = None
    liquidity_usd: Optional[float] = None
    is_honeypot: Optional[bool] = None
    has_mint_authority: Optional[bool] = None
    has_freeze_authority: Optional[bool] = None
    top_holder_pct: Optional[float] = None
    is_contract_verified: Optional[bool] = None
    details: dict = field(default_factory=dict)


class RiskEngine:
    """
    Checks token safety before allowing copy-trades.
    Uses GoPlus Security API and DexScreener.
    """

    def __init__(
        self,
        price_engine: PriceEngine,
        max_buy_tax: float = 10.0,
        max_sell_tax: float = 10.0,
        min_liquidity_usd: float = 10_000.0,
        max_top_holder_pct: float = 50.0,
    ) -> None:
        self._price = price_engine
        self._max_buy_tax = max_buy_tax
        self._max_sell_tax = max_sell_tax
        self._min_liquidity = min_liquidity_usd
        self._max_top_holder = max_top_holder_pct
        self._cache: dict[str, TokenRiskReport] = {}

    async def check_token(self, token_address: str, chain_key: str) -> TokenRiskReport:
        cache_key = f"{chain_key}:{token_address.lower()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        report = await self._run_checks(token_address, chain_key)
        self._cache[cache_key] = report
        return report

    async def _run_checks(self, token_address: str, chain_key: str) -> TokenRiskReport:
        flags: list[str] = []
        score = 0.0

        # ---- Liquidity check ----
        _, liquidity = await self._price.get_price_with_liquidity(token_address, chain_key)
        if liquidity is not None:
            if liquidity < self._min_liquidity:
                flags.append("LOW_LIQUIDITY")
                score += 40
        else:
            flags.append("NO_PRICE_DATA")
            score += 20

        # ---- GoPlus Security (EVM) ----
        chain_id_map = {
            "ethereum": 1, "base": 8453, "arbitrum": 42161, "bsc": 56,
            "polygon": 137, "optimism": 10, "avalanche": 43114,
        }
        buy_tax = None
        sell_tax = None
        is_honeypot = None
        top_holder_pct = None
        is_verified = None
        has_mint = None
        has_freeze = None

        if chain_key in chain_id_map:
            try:
                chain_id = chain_id_map[chain_key]
                url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={token_address}"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            token_data = data.get("result", {}).get(token_address.lower(), {})

                            buy_tax_raw = token_data.get("buy_tax")
                            sell_tax_raw = token_data.get("sell_tax")
                            if buy_tax_raw is not None:
                                buy_tax = float(buy_tax_raw) * 100
                            if sell_tax_raw is not None:
                                sell_tax = float(sell_tax_raw) * 100

                            is_honeypot = token_data.get("is_honeypot") == "1"
                            is_verified = token_data.get("is_open_source") == "1"

                            holders = token_data.get("holders", [])
                            if holders:
                                top_holder_pct = float(holders[0].get("percent", 0)) * 100

                            if buy_tax and buy_tax > self._max_buy_tax:
                                flags.append(f"HIGH_BUY_TAX_{buy_tax:.0f}%")
                                score += 30
                            if sell_tax and sell_tax > self._max_sell_tax:
                                flags.append(f"HIGH_SELL_TAX_{sell_tax:.0f}%")
                                score += 30
                            if is_honeypot:
                                flags.append("HONEYPOT")
                                score += 60
                            if not is_verified:
                                flags.append("UNVERIFIED_CONTRACT")
                                score += 10
                            if top_holder_pct and top_holder_pct > self._max_top_holder:
                                flags.append(f"HIGH_CONCENTRATION_{top_holder_pct:.0f}%")
                                score += 20

                            if token_data.get("can_take_back_ownership") == "1":
                                flags.append("OWNERSHIP_BACKDOOR")
                                score += 40
                            if token_data.get("hidden_owner") == "1":
                                flags.append("HIDDEN_OWNER")
                                score += 30
                            if token_data.get("transfer_pausable") == "1":
                                flags.append("TRANSFER_PAUSABLE")
                                score += 30
                            if token_data.get("is_blacklisted") == "1":
                                flags.append("BLACKLIST_FUNCTION")
                                score += 20
            except Exception as exc:
                logger.debug("GoPlus check failed", extra={"token": token_address, "error": str(exc)})

        elif chain_key == "solana":
            # For Solana: check rugcheck.xyz
            try:
                url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            risks = data.get("risks", [])
                            for risk in risks:
                                level = risk.get("level", "").upper()
                                name = risk.get("name", "")
                                if level == "DANGER":
                                    flags.append(f"DANGER_{name.upper().replace(' ', '_')}")
                                    score += 30
                                elif level == "WARN":
                                    flags.append(f"WARN_{name.upper().replace(' ', '_')}")
                                    score += 10

                            # Mint/freeze authority
                            if data.get("mintAuthority"):
                                flags.append("MINT_AUTHORITY_ENABLED")
                                has_mint = True
                                score += 20
                            if data.get("freezeAuthority"):
                                flags.append("FREEZE_AUTHORITY_ENABLED")
                                has_freeze = True
                                score += 20
            except Exception as exc:
                logger.debug("RugCheck failed", extra={"token": token_address, "error": str(exc)})

        # Determine risk level
        score = min(score, 100)
        if score >= 60 or "HONEYPOT" in flags:
            risk_level = RiskLevel.BLOCKED
        elif score >= 40:
            risk_level = RiskLevel.HIGH_RISK
        elif score >= 20:
            risk_level = RiskLevel.CAUTION
        else:
            risk_level = RiskLevel.SAFE

        return TokenRiskReport(
            token_address=token_address,
            chain_key=chain_key,
            risk_level=risk_level,
            score=score,
            flags=flags,
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            liquidity_usd=liquidity,
            is_honeypot=is_honeypot,
            has_mint_authority=has_mint,
            has_freeze_authority=has_freeze,
            top_holder_pct=top_holder_pct,
            is_contract_verified=is_verified,
        )

    def is_safe_to_trade(self, report: TokenRiskReport) -> bool:
        return report.risk_level not in (RiskLevel.BLOCKED, RiskLevel.HIGH_RISK)
