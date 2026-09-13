"""EVM chain adapter — one instance per chain (Ethereum, Base, Arbitrum, BSC, etc.)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.middleware import async_geth_poa_middleware

from src.chains.base_adapter import (
    ChainAdapter,
    ParsedSwap,
    PriceData,
    RawTransaction,
    TokenInfo,
    WalletBalance,
    WalletEventCallback,
)
from src.chains.evm.dex_parsers.uniswap_v2 import decode_swap_log, classify_swap_direction
from src.chains.evm.dex_parsers.uniswap_v3 import decode_v3_swap_log, classify_v3_swap

logger = logging.getLogger(__name__)

# Known DEX router → pool resolver registries (chain-specific, loaded from config)
KNOWN_ROUTERS: dict[str, dict[str, str]] = {}

ERC20_ABI = [
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "type": "function", "stateMutability": "view"},
    {"inputs": [], "name": "name", "outputs": [{"type": "string"}], "type": "function", "stateMutability": "view"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "type": "function", "stateMutability": "view"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "type": "function", "stateMutability": "view"},
]

PAIR_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "type": "function", "stateMutability": "view"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "type": "function", "stateMutability": "view"},
]

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class EVMAdapter(ChainAdapter):
    chain_type = "evm"

    def __init__(
        self,
        chain_key: str,
        chain_id: int,
        rpc_http: str,
        rpc_ws: Optional[str] = None,
        rpc_http_backup: Optional[str] = None,
        stablecoins: Optional[list[str]] = None,
        wrapped_native: Optional[str] = None,
        native_token: str = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
        chain_symbol: str = "ETH",
        poa: bool = False,
    ) -> None:
        self.chain_key = chain_key
        self._chain_id = chain_id
        self._rpc_http = rpc_http
        self._rpc_ws = rpc_ws
        self._rpc_http_backup = rpc_http_backup
        self._stablecoins = {a.lower() for a in (stablecoins or [])}
        self._wrapped_native = wrapped_native.lower() if wrapped_native else None
        self._native_token = native_token.lower()
        self._chain_symbol = chain_symbol
        self._poa = poa

        self._w3: Optional[AsyncWeb3] = None
        self._w3_backup: Optional[AsyncWeb3] = None
        self._subscriptions: dict[str, list[WalletEventCallback]] = {}
        self._ws_task: Optional[asyncio.Task] = None
        self._running = False
        self._pair_cache: dict[str, tuple[str, str]] = {}
        self._token_cache: dict[str, TokenInfo] = {}
        self._pending_backfill: dict[str, int] = {}  # wallet -> last_block

    # ---- Lifecycle ----

    async def start(self) -> None:
        self._w3 = AsyncWeb3(AsyncHTTPProvider(self._rpc_http))
        if self._poa:
            self._w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
        if self._rpc_http_backup:
            self._w3_backup = AsyncWeb3(AsyncHTTPProvider(self._rpc_http_backup))
        self._running = True
        if self._rpc_ws:
            self._ws_task = asyncio.create_task(self._ws_loop(), name=f"ws-{self.chain_key}")
        logger.info("EVMAdapter started", extra={"chain": self.chain_key})

    async def stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        logger.info("EVMAdapter stopped", extra={"chain": self.chain_key})

    # ---- WebSocket loop ----

    async def _ws_loop(self) -> None:
        backoff = 1
        while self._running:
            try:
                await self._ws_connect()
                backoff = 1
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning(
                    "WS reconnect",
                    extra={"chain": self.chain_key, "error": str(exc), "backoff": backoff},
                )
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)

    async def _ws_connect(self) -> None:
        import websockets

        async with websockets.connect(self._rpc_ws, ping_interval=20, ping_timeout=20) as ws:
            logger.info("WS connected", extra={"chain": self.chain_key})
            sub_id = await self._subscribe_pending(ws)
            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    await self._handle_ws_message(msg)
                except Exception as exc:
                    logger.debug("WS parse error", extra={"chain": self.chain_key, "error": str(exc)})

    async def _subscribe_pending(self, ws) -> None:
        # Subscribe to newPendingTransactions or newHeads depending on chain
        sub_msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]})
        await ws.send(sub_msg)
        resp = json.loads(await ws.recv())
        return resp.get("result")

    async def _handle_ws_message(self, msg: dict) -> None:
        if "params" not in msg:
            return
        result = msg["params"].get("result", {})
        # newHeads subscription
        if isinstance(result, dict) and "number" in result:
            block_hash = result.get("hash")
            block_number = int(result["number"], 16) if isinstance(result["number"], str) else result["number"]
            await self._process_block(block_number, block_hash)

    async def _process_block(self, block_number: int, block_hash: Optional[str]) -> None:
        if not self._subscriptions:
            return
        try:
            w3 = await self._get_w3()
            block = await w3.eth.get_block(block_hash or block_number, full_transactions=True)
            block_ts = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc)

            tracked = {addr.lower() for addr in self._subscriptions}
            for tx in block.get("transactions", []):
                from_addr = tx.get("from", "").lower()
                to_addr = (tx.get("to") or "").lower()
                if from_addr in tracked or to_addr in tracked:
                    for addr in (from_addr, to_addr):
                        if addr in tracked:
                            raw_tx = RawTransaction(
                                tx_hash=tx["hash"].hex() if hasattr(tx["hash"], "hex") else tx["hash"],
                                chain_key=self.chain_key,
                                wallet_address=addr,
                                block_number=block_number,
                                block_timestamp=block_ts,
                                gas_used=None,
                                gas_price=tx.get("gasPrice"),
                                raw=dict(tx),
                                detected_at=datetime.now(timezone.utc),
                            )
                            for cb in self._subscriptions.get(addr, []):
                                try:
                                    cb(raw_tx)
                                except Exception as exc:
                                    logger.error("Callback error", extra={"chain": self.chain_key, "error": str(exc)})
        except Exception as exc:
            logger.warning("Block processing error", extra={"chain": self.chain_key, "error": str(exc)})

    # ---- Subscriptions ----

    async def subscribe_wallet(self, wallet_address: str, callback: WalletEventCallback) -> None:
        key = wallet_address.lower()
        self._subscriptions.setdefault(key, []).append(callback)

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        self._subscriptions.pop(wallet_address.lower(), None)

    # ---- RPC helpers ----

    async def _get_w3(self) -> AsyncWeb3:
        if self._w3 and await self._check_w3(self._w3):
            return self._w3
        if self._w3_backup and await self._check_w3(self._w3_backup):
            logger.warning("Switched to backup RPC", extra={"chain": self.chain_key})
            return self._w3_backup
        # Try reconnect primary
        self._w3 = AsyncWeb3(AsyncHTTPProvider(self._rpc_http))
        if self._poa:
            self._w3.middleware_onion.inject(async_geth_poa_middleware, layer=0)
        return self._w3

    async def _check_w3(self, w3: AsyncWeb3) -> bool:
        try:
            await asyncio.wait_for(w3.eth.block_number, timeout=5)
            return True
        except Exception:
            return False

    # ---- Transaction ----

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def get_transaction(self, tx_hash: str) -> Optional[dict[str, Any]]:
        w3 = await self._get_w3()
        try:
            tx = await w3.eth.get_transaction(tx_hash)
            return dict(tx)
        except Exception:
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def get_transaction_receipt(self, tx_hash: str) -> Optional[dict[str, Any]]:
        w3 = await self._get_w3()
        try:
            receipt = await w3.eth.get_transaction_receipt(tx_hash)
            return dict(receipt)
        except Exception:
            return None

    async def parse_transaction(
        self, tx_data: dict[str, Any], receipt: dict[str, Any]
    ) -> list[ParsedSwap]:
        swaps: list[ParsedSwap] = []
        logs = receipt.get("logs", [])

        for log in logs:
            topics = [t.hex() if hasattr(t, "hex") else t for t in log.get("topics", [])]
            log_norm = {**log, "topics": topics, "address": log["address"].lower()}

            # Try V2 swap
            v2 = decode_swap_log(log_norm)
            if v2:
                pair_addr = v2["pair_address"]
                tokens = await self._get_pair_tokens(pair_addr)
                if tokens:
                    token0, token1 = tokens
                    direction = classify_swap_direction(v2, token0, token1)
                    if direction:
                        t_in = await self.get_token_metadata(direction["token_in"])
                        t_out = await self.get_token_metadata(direction["token_out"])
                        if t_in and t_out:
                            amt_in = Decimal(direction["amount_in"]) / Decimal(10 ** t_in.decimals)
                            amt_out = Decimal(direction["amount_out"]) / Decimal(10 ** t_out.decimals)
                            swaps.append(ParsedSwap(
                                tx_hash=receipt.get("transactionHash", "").hex()
                                if hasattr(receipt.get("transactionHash"), "hex")
                                else receipt.get("transactionHash", ""),
                                chain_key=self.chain_key,
                                wallet_address=tx_data.get("from", "").lower(),
                                dex_name="uniswap_v2",
                                pool_address=pair_addr,
                                token_in_address=direction["token_in"],
                                token_in_amount=amt_in,
                                token_in_symbol=t_in.symbol,
                                token_out_address=direction["token_out"],
                                token_out_amount=amt_out,
                                token_out_symbol=t_out.symbol,
                                fee_amount=None,
                                fee_token_address=None,
                                block_number=receipt.get("blockNumber"),
                                block_timestamp=None,
                                log_index=log.get("logIndex", 0),
                            ))
                continue

            # Try V3 swap
            v3 = decode_v3_swap_log(log_norm)
            if v3:
                pool_addr = v3["pool_address"]
                tokens = await self._get_pair_tokens(pool_addr)
                if tokens:
                    token0, token1 = tokens
                    direction = classify_v3_swap(v3, token0, token1)
                    if direction:
                        t_in = await self.get_token_metadata(direction["token_in"])
                        t_out = await self.get_token_metadata(direction["token_out"])
                        if t_in and t_out:
                            amt_in = Decimal(direction["amount_in"]) / Decimal(10 ** t_in.decimals)
                            amt_out = Decimal(direction["amount_out"]) / Decimal(10 ** t_out.decimals)
                            swaps.append(ParsedSwap(
                                tx_hash=receipt.get("transactionHash", "").hex()
                                if hasattr(receipt.get("transactionHash"), "hex")
                                else receipt.get("transactionHash", ""),
                                chain_key=self.chain_key,
                                wallet_address=tx_data.get("from", "").lower(),
                                dex_name="uniswap_v3",
                                pool_address=pool_addr,
                                token_in_address=direction["token_in"],
                                token_in_amount=amt_in,
                                token_in_symbol=t_in.symbol,
                                token_out_address=direction["token_out"],
                                token_out_amount=amt_out,
                                token_out_symbol=t_out.symbol,
                                fee_amount=None,
                                fee_token_address=None,
                                block_number=receipt.get("blockNumber"),
                                block_timestamp=None,
                                log_index=log.get("logIndex", 0),
                            ))
        return swaps

    async def _get_pair_tokens(self, pair_address: str) -> Optional[tuple[str, str]]:
        if pair_address in self._pair_cache:
            return self._pair_cache[pair_address]
        try:
            w3 = await self._get_w3()
            contract = w3.eth.contract(
                address=w3.to_checksum_address(pair_address), abi=PAIR_ABI
            )
            token0 = (await contract.functions.token0().call()).lower()
            token1 = (await contract.functions.token1().call()).lower()
            self._pair_cache[pair_address] = (token0, token1)
            return token0, token1
        except Exception:
            return None

    # ---- Token metadata ----

    async def get_token_metadata(self, token_address: str) -> Optional[TokenInfo]:
        token_address = token_address.lower()
        if token_address in self._token_cache:
            return self._token_cache[token_address]

        if token_address == self._native_token:
            info = TokenInfo(
                address=token_address,
                symbol=self._chain_symbol,
                name=self._chain_symbol,
                decimals=18,
                chain_key=self.chain_key,
                is_native=True,
            )
            self._token_cache[token_address] = info
            return info

        try:
            w3 = await self._get_w3()
            cs_addr = w3.to_checksum_address(token_address)
            contract = w3.eth.contract(address=cs_addr, abi=ERC20_ABI)
            symbol = await contract.functions.symbol().call()
            name = await contract.functions.name().call()
            decimals = await contract.functions.decimals().call()
            info = TokenInfo(
                address=token_address,
                symbol=symbol,
                name=name,
                decimals=decimals,
                chain_key=self.chain_key,
                is_stablecoin=token_address in self._stablecoins,
            )
            self._token_cache[token_address] = info
            return info
        except Exception:
            return None

    # ---- Price ----

    async def get_token_price(self, token_address: str) -> Optional[PriceData]:
        """Use DexScreener as primary price source for EVM tokens."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    if not pairs:
                        return None
                    # Pick highest-liquidity pair on this chain
                    chain_pairs = [p for p in pairs if p.get("chainId", "").lower() in self._chain_dexscreener_id()]
                    if not chain_pairs:
                        chain_pairs = pairs
                    best = max(chain_pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                    price_usd = float(best.get("priceUsd", 0) or 0)
                    liq = float(best.get("liquidity", {}).get("usd", 0) or 0)
                    mcap = float(best.get("fdv", 0) or 0)
                    return PriceData(
                        token_address=token_address,
                        chain_key=self.chain_key,
                        price_usd=price_usd,
                        liquidity_usd=liq,
                        market_cap_usd=mcap,
                        source="dexscreener",
                    )
        except Exception:
            return None

    def _chain_dexscreener_id(self) -> list[str]:
        mapping = {
            "ethereum": ["ethereum"],
            "base": ["base"],
            "arbitrum": ["arbitrum"],
            "bsc": ["bsc"],
            "polygon": ["polygon"],
            "optimism": ["optimism"],
            "avalanche": ["avalanche"],
        }
        return mapping.get(self.chain_key, [self.chain_key])

    # ---- Balance ----

    async def get_balance(self, wallet_address: str, token_address: str) -> Optional[WalletBalance]:
        try:
            w3 = await self._get_w3()
            if token_address.lower() == self._native_token:
                bal_wei = await w3.eth.get_balance(w3.to_checksum_address(wallet_address))
                return WalletBalance(
                    wallet_address=wallet_address,
                    token_address=token_address,
                    chain_key=self.chain_key,
                    amount_decimal=Decimal(bal_wei) / Decimal(10**18),
                    amount_usd=None,
                )
            contract = w3.eth.contract(
                address=w3.to_checksum_address(token_address), abi=ERC20_ABI
            )
            info = await self.get_token_metadata(token_address)
            decimals = info.decimals if info else 18
            raw_bal = await contract.functions.balanceOf(w3.to_checksum_address(wallet_address)).call()
            return WalletBalance(
                wallet_address=wallet_address,
                token_address=token_address,
                chain_key=self.chain_key,
                amount_decimal=Decimal(raw_bal) / Decimal(10**decimals),
                amount_usd=None,
            )
        except Exception:
            return None

    # ---- Block ----

    async def get_latest_block(self) -> int:
        w3 = await self._get_w3()
        return await w3.eth.block_number

    async def get_block_timestamp(self, block_number: int) -> Optional[datetime]:
        try:
            w3 = await self._get_w3()
            block = await w3.eth.get_block(block_number)
            return datetime.fromtimestamp(block["timestamp"], tz=timezone.utc)
        except Exception:
            return None

    # ---- Health ----

    async def is_healthy(self) -> bool:
        try:
            w3 = await self._get_w3()
            bn = await asyncio.wait_for(w3.eth.block_number, timeout=5)
            return bn > 0
        except Exception:
            return False

    # ---- Backfill ----

    async def get_wallet_transactions(
        self,
        wallet_address: str,
        from_block: Optional[int] = None,
        limit: int = 100,
    ) -> list[RawTransaction]:
        """Basic backfill via eth_getLogs for Transfer events from/to wallet."""
        result = []
        try:
            w3 = await self._get_w3()
            latest = await w3.eth.block_number
            start = from_block or max(0, latest - 1000)

            # Get logs where wallet is sender or receiver of ERC20 transfers
            wallet_cs = w3.to_checksum_address(wallet_address)
            wallet_topic = "0x" + "0" * 24 + wallet_address.lower()[2:]

            logs_from = await w3.eth.get_logs({
                "fromBlock": start,
                "toBlock": "latest",
                "topics": [TRANSFER_TOPIC, wallet_topic],
            })
            logs_to = await w3.eth.get_logs({
                "fromBlock": start,
                "toBlock": "latest",
                "topics": [TRANSFER_TOPIC, None, wallet_topic],
            })

            seen_txs: set[str] = set()
            for log in list(logs_from) + list(logs_to):
                tx_hash = log["transactionHash"].hex()
                if tx_hash in seen_txs:
                    continue
                seen_txs.add(tx_hash)
                block_ts = await self.get_block_timestamp(log["blockNumber"])
                result.append(RawTransaction(
                    tx_hash=tx_hash,
                    chain_key=self.chain_key,
                    wallet_address=wallet_address.lower(),
                    block_number=log["blockNumber"],
                    block_timestamp=block_ts,
                    gas_used=None,
                    gas_price=None,
                    raw=dict(log),
                ))
                if len(result) >= limit:
                    break
        except Exception as exc:
            logger.warning("Backfill error", extra={"chain": self.chain_key, "error": str(exc)})
        return result
