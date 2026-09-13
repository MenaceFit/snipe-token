"""Multi-source price engine with aggregation and caching."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Cache: (chain_key, token_address) -> (price_usd, fetched_at, liquidity_usd)
_price_cache: dict[tuple[str, str], tuple[float, float, Optional[float]]] = {}
_CACHE_TTL = 30  # seconds


class PriceEngine:
    """
    Fetches USD prices from multiple sources with fallback.
    Sources in priority order: DexScreener → Birdeye (Solana) → CoinGecko.
    """

    def __init__(
        self,
        coingecko_api_key: str = "",
        birdeye_api_key: str = "",
        cache_ttl: int = _CACHE_TTL,
    ) -> None:
        self._cg_key = coingecko_api_key
        self._be_key = birdeye_api_key
        self._cache_ttl = cache_ttl
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_price(
        self, token_address: str, chain_key: str, force_refresh: bool = False
    ) -> Optional[float]:
        """Return USD price; None if all sources fail."""
        cache_key = (chain_key, token_address.lower())
        if not force_refresh:
            cached = _price_cache.get(cache_key)
            if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
                return cached[0]

        price = None
        liq = None

        # Source 1: DexScreener
        try:
            price, liq = await self._dexscreener(token_address, chain_key)
        except Exception as exc:
            logger.debug("DexScreener failed", extra={"token": token_address, "error": str(exc)})

        # Source 2: Birdeye (Solana)
        if price is None and chain_key == "solana" and self._be_key:
            try:
                price = await self._birdeye_price(token_address)
            except Exception as exc:
                logger.debug("Birdeye failed", extra={"token": token_address, "error": str(exc)})

        # Source 3: CoinGecko
        if price is None and self._cg_key:
            try:
                price = await self._coingecko_price(token_address, chain_key)
            except Exception as exc:
                logger.debug("CoinGecko failed", extra={"token": token_address, "error": str(exc)})

        if price is not None and price > 0:
            _price_cache[cache_key] = (price, time.monotonic(), liq)

        return price

    async def get_price_with_liquidity(
        self, token_address: str, chain_key: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Return (price_usd, liquidity_usd)."""
        cache_key = (chain_key, token_address.lower())
        cached = _price_cache.get(cache_key)
        if cached and (time.monotonic() - cached[1]) < self._cache_ttl:
            return cached[0], cached[2]
        price, liq = await self._dexscreener(token_address, chain_key)
        if price:
            _price_cache[cache_key] = (price, time.monotonic(), liq)
        return price, liq

    # ---- Sources ----

    async def _dexscreener(
        self, token_address: str, chain_key: str
    ) -> tuple[Optional[float], Optional[float]]:
        session = await self._get_session()
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json()
            pairs = data.get("pairs", [])
            if not pairs:
                return None, None

            chain_map = {
                "ethereum": "ethereum", "base": "base", "arbitrum": "arbitrum",
                "bsc": "bsc", "polygon": "polygon", "optimism": "optimism",
                "avalanche": "avalanche", "solana": "solana",
            }
            ds_chain = chain_map.get(chain_key, chain_key)
            filtered = [p for p in pairs if p.get("chainId", "").lower() == ds_chain]
            if not filtered:
                filtered = pairs

            best = max(filtered, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
            price = float(best.get("priceUsd", 0) or 0)
            liq = float(best.get("liquidity", {}).get("usd", 0) or 0)
            return (price if price > 0 else None), (liq if liq > 0 else None)

    async def _birdeye_price(self, token_address: str) -> Optional[float]:
        session = await self._get_session()
        url = f"https://public-api.birdeye.so/public/price?address={token_address}"
        headers = {"X-API-KEY": self._be_key}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            price = data.get("data", {}).get("value")
            return float(price) if price else None

    async def _coingecko_price(self, token_address: str, chain_key: str) -> Optional[float]:
        platform_map = {
            "ethereum": "ethereum", "base": "base", "arbitrum": "arbitrum-one",
            "bsc": "binance-smart-chain", "polygon": "polygon-pos",
            "optimism": "optimistic-ethereum", "avalanche": "avalanche",
            "solana": "solana",
        }
        platform = platform_map.get(chain_key)
        if not platform:
            return None
        session = await self._get_session()
        base = "https://pro-api.coingecko.com/api/v3" if self._cg_key else "https://api.coingecko.com/api/v3"
        url = f"{base}/simple/token_price/{platform}?contract_addresses={token_address}&vs_currencies=usd"
        headers = {"x-cg-pro-api-key": self._cg_key} if self._cg_key else {}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            price = data.get(token_address.lower(), {}).get("usd")
            return float(price) if price else None

    async def get_native_price(self, chain_key: str) -> Optional[float]:
        """Get native token price (ETH, BNB, SOL, etc.)."""
        native_coingecko = {
            "ethereum": "ethereum", "base": "ethereum", "arbitrum": "ethereum",
            "optimism": "ethereum", "bsc": "binancecoin", "polygon": "matic-network",
            "avalanche": "avalanche-2", "solana": "solana",
        }
        cg_id = native_coingecko.get(chain_key)
        if not cg_id:
            return None
        try:
            session = await self._get_session()
            base = "https://api.coingecko.com/api/v3"
            url = f"{base}/simple/price?ids={cg_id}&vs_currencies=usd"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                price = data.get(cg_id, {}).get("usd")
                return float(price) if price else None
        except Exception:
            return None
