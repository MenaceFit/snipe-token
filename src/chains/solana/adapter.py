"""Solana chain adapter using JSON-RPC WebSocket subscriptions."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import aiohttp

from src.chains.base_adapter import (
    ChainAdapter,
    ParsedSwap,
    PriceData,
    RawTransaction,
    TokenInfo,
    WalletBalance,
    WalletEventCallback,
)

logger = logging.getLogger(__name__)

# Well-known program IDs
RAYDIUM_AMM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
RAYDIUM_CLMM = "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK"
ORCA_WHIRLPOOL = "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc"
JUPITER_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
METEORA_DLMM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"

NATIVE_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

STABLECOINS = {USDC_MINT, USDT_MINT}


class SolanaAdapter(ChainAdapter):
    chain_key = "solana"
    chain_type = "solana"

    def __init__(
        self,
        rpc_http: str,
        rpc_ws: Optional[str] = None,
        rpc_ws_backup: Optional[str] = None,
    ) -> None:
        self._rpc_http = rpc_http
        self._rpc_ws = rpc_ws
        self._rpc_ws_backup = rpc_ws_backup
        self._subscriptions: dict[str, list[WalletEventCallback]] = {}
        self._sub_ids: dict[str, int] = {}  # wallet -> subscription id
        self._ws_task: Optional[asyncio.Task] = None
        self._ws: Any = None
        self._running = False
        self._token_cache: dict[str, TokenInfo] = {}
        self._next_id = 1

    # ---- Lifecycle ----

    async def start(self) -> None:
        self._running = True
        if self._rpc_ws:
            self._ws_task = asyncio.create_task(self._ws_loop(), name="ws-solana")
        logger.info("SolanaAdapter started")

    async def stop(self) -> None:
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

    # ---- WebSocket ----

    async def _ws_loop(self) -> None:
        backoff = 1
        while self._running:
            try:
                await self._ws_connect()
                backoff = 1
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.warning("Solana WS reconnect", extra={"error": str(exc), "backoff": backoff})
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 2, 60)
                # Re-subscribe all wallets after reconnect
                await self._resubscribe_all()

    async def _ws_connect(self) -> None:
        import websockets
        ws_url = self._rpc_ws
        async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
            self._ws = ws
            logger.info("Solana WS connected")
            # Subscribe all tracked wallets
            for wallet in list(self._subscriptions.keys()):
                await self._subscribe_account(ws, wallet)
            async for raw in ws:
                if not self._running:
                    break
                try:
                    msg = json.loads(raw)
                    await self._handle_message(msg)
                except Exception as exc:
                    logger.debug("Solana WS parse error", extra={"error": str(exc)})

    async def _subscribe_account(self, ws, wallet_address: str) -> None:
        msg_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "logsSubscribe",
            "params": [
                {"mentions": [wallet_address]},
                {"commitment": "confirmed"},
            ],
        }
        await ws.send(json.dumps(payload))

    async def _resubscribe_all(self) -> None:
        if self._ws and not self._ws.closed:
            for wallet in self._subscriptions:
                await self._subscribe_account(self._ws, wallet)

    async def _handle_message(self, msg: dict) -> None:
        if "method" not in msg:
            return
        if msg["method"] == "logsNotification":
            params = msg.get("params", {})
            result = params.get("result", {})
            value = result.get("value", {})
            signature = value.get("signature")
            if not signature:
                return
            logs = value.get("logs", [])
            err = value.get("err")
            if err:
                return  # Failed transaction

            # Determine which tracked wallet is involved
            for wallet in self._subscriptions:
                # Check if wallet appears in logs
                if any(wallet in log for log in logs):
                    raw_tx = RawTransaction(
                        tx_hash=signature,
                        chain_key=self.chain_key,
                        wallet_address=wallet,
                        block_number=None,
                        block_timestamp=None,
                        gas_used=None,
                        gas_price=None,
                        raw={"logs": logs, "signature": signature},
                        detected_at=datetime.now(timezone.utc),
                    )
                    for cb in self._subscriptions[wallet]:
                        try:
                            cb(raw_tx)
                        except Exception as exc:
                            logger.error("Solana callback error", extra={"error": str(exc)})
                    break

    # ---- Subscriptions ----

    async def subscribe_wallet(self, wallet_address: str, callback: WalletEventCallback) -> None:
        self._subscriptions.setdefault(wallet_address, []).append(callback)
        if self._ws and not self._ws.closed:
            await self._subscribe_account(self._ws, wallet_address)

    async def unsubscribe_wallet(self, wallet_address: str) -> None:
        self._subscriptions.pop(wallet_address, None)

    # ---- Transaction ----

    async def get_transaction(self, tx_hash: str) -> Optional[dict[str, Any]]:
        return await self._rpc_call("getTransaction", [
            tx_hash,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
        ])

    async def get_transaction_receipt(self, tx_hash: str) -> Optional[dict[str, Any]]:
        return await self.get_transaction(tx_hash)

    async def parse_transaction(
        self, tx_data: dict[str, Any], receipt: dict[str, Any]
    ) -> list[ParsedSwap]:
        if not tx_data:
            return []
        swaps = []
        try:
            meta = tx_data.get("meta", {})
            pre_balances = meta.get("preTokenBalances", [])
            post_balances = meta.get("postTokenBalances", [])
            message = tx_data.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])

            # Build token balance delta map: account_index -> {mint: delta}
            balance_map: dict[int, dict[str, Decimal]] = {}
            for bal in post_balances:
                idx = bal["accountIndex"]
                mint = bal["mint"]
                post_amt = Decimal(bal.get("uiTokenAmount", {}).get("amount", "0"))
                balance_map.setdefault(idx, {})[mint] = post_amt

            pre_map: dict[int, dict[str, Decimal]] = {}
            for bal in pre_balances:
                idx = bal["accountIndex"]
                mint = bal["mint"]
                pre_amt = Decimal(bal.get("uiTokenAmount", {}).get("amount", "0"))
                pre_map.setdefault(idx, {})[mint] = pre_amt

            # Find signer (index 0 is fee payer)
            if not account_keys:
                return []
            signer = account_keys[0] if isinstance(account_keys[0], str) else account_keys[0].get("pubkey", "")

            # Identify token deltas for signer-owned accounts
            # This is a simplified heuristic: find mints with positive delta (received) and negative (sent)
            deltas: dict[str, Decimal] = {}
            for idx, post_tokens in balance_map.items():
                pre_tokens = pre_map.get(idx, {})
                for mint, post_amt in post_tokens.items():
                    pre_amt = pre_tokens.get(mint, Decimal(0))
                    delta = post_amt - pre_amt
                    if delta != 0:
                        deltas[mint] = deltas.get(mint, Decimal(0)) + delta

            # Also check SOL balance change
            pre_sol = meta.get("preBalances", [])
            post_sol = meta.get("postBalances", [])
            if pre_sol and post_sol:
                sol_delta = Decimal(post_sol[0] - pre_sol[0]) / Decimal(10**9)
                if abs(sol_delta) > Decimal("0.001"):
                    deltas[NATIVE_MINT] = deltas.get(NATIVE_MINT, Decimal(0)) + sol_delta

            # Find swap pair: one positive, one negative (or SOL)
            positive = {m: d for m, d in deltas.items() if d > 0}
            negative = {m: d for m, d in deltas.items() if d < 0}

            if positive and negative:
                # Pick largest absolute values
                token_out_mint = max(positive, key=lambda m: positive[m])
                token_in_mint = min(negative, key=lambda m: negative[m])  # most negative
                amt_out_raw = positive[token_out_mint]
                amt_in_raw = abs(negative[token_in_mint])

                t_in = await self.get_token_metadata(token_in_mint)
                t_out = await self.get_token_metadata(token_out_mint)
                t_in_sym = t_in.symbol if t_in else token_in_mint[:6]
                t_out_sym = t_out.symbol if t_out else token_out_mint[:6]
                t_in_dec = t_in.decimals if t_in else 6
                t_out_dec = t_out.decimals if t_out else 6

                amt_in = amt_in_raw / Decimal(10**t_in_dec)
                amt_out = amt_out_raw / Decimal(10**t_out_dec)

                # Detect DEX from logs
                dex = "unknown"
                for inst in (tx_data.get("transaction", {}).get("message", {}).get("instructions", []) or []):
                    prog = inst.get("programId", "")
                    if RAYDIUM_AMM in prog or RAYDIUM_CLMM in prog:
                        dex = "raydium"
                    elif ORCA_WHIRLPOOL in prog:
                        dex = "orca"
                    elif JUPITER_V6 in prog:
                        dex = "jupiter"
                    elif METEORA_DLMM in prog:
                        dex = "meteora"

                block_time = tx_data.get("blockTime")
                block_ts = datetime.fromtimestamp(block_time, tz=timezone.utc) if block_time else None

                swaps.append(ParsedSwap(
                    tx_hash=tx_hash if (tx_hash := tx_data.get("transaction", {}).get("signatures", [""])[0]) else "",
                    chain_key=self.chain_key,
                    wallet_address=signer,
                    dex_name=dex,
                    pool_address="",
                    token_in_address=token_in_mint,
                    token_in_amount=amt_in,
                    token_in_symbol=t_in_sym,
                    token_out_address=token_out_mint,
                    token_out_amount=amt_out,
                    token_out_symbol=t_out_sym,
                    fee_amount=None,
                    fee_token_address=None,
                    block_number=tx_data.get("slot"),
                    block_timestamp=block_ts,
                ))
        except Exception as exc:
            logger.debug("Solana parse error", extra={"error": str(exc)})
        return swaps

    # ---- Token metadata ----

    async def get_token_metadata(self, token_address: str) -> Optional[TokenInfo]:
        if token_address in self._token_cache:
            return self._token_cache[token_address]

        if token_address == NATIVE_MINT:
            info = TokenInfo(address=token_address, symbol="SOL", name="Solana",
                             decimals=9, chain_key=self.chain_key, is_native=True)
            self._token_cache[token_address] = info
            return info

        if token_address in STABLECOINS:
            sym = "USDC" if token_address == USDC_MINT else "USDT"
            info = TokenInfo(address=token_address, symbol=sym, name=sym,
                             decimals=6, chain_key=self.chain_key, is_stablecoin=True)
            self._token_cache[token_address] = info
            return info

        # Try DexScreener for metadata
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        pairs = data.get("pairs", [])
                        if pairs:
                            pair = pairs[0]
                            base = pair.get("baseToken", {})
                            if base.get("address", "").lower() == token_address.lower():
                                info = TokenInfo(
                                    address=token_address,
                                    symbol=base.get("symbol", "???"),
                                    name=base.get("name", "Unknown"),
                                    decimals=6,
                                    chain_key=self.chain_key,
                                )
                                self._token_cache[token_address] = info
                                return info
        except Exception:
            pass

        # Fallback: on-chain SPL token metadata via RPC
        try:
            data = await self._rpc_call("getAccountInfo", [
                token_address,
                {"encoding": "jsonParsed"},
            ])
            if data and data.get("data"):
                parsed = data["data"].get("parsed", {})
                info_data = parsed.get("info", {})
                decimals = info_data.get("decimals", 6)
                info = TokenInfo(
                    address=token_address,
                    symbol=token_address[:6],
                    name="Unknown",
                    decimals=decimals,
                    chain_key=self.chain_key,
                )
                self._token_cache[token_address] = info
                return info
        except Exception:
            pass
        return None

    # ---- Price ----

    async def get_token_price(self, token_address: str) -> Optional[PriceData]:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    pairs = [p for p in data.get("pairs", []) if p.get("chainId") == "solana"]
                    if not pairs:
                        pairs = data.get("pairs", [])
                    if not pairs:
                        return None
                    best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                    return PriceData(
                        token_address=token_address,
                        chain_key=self.chain_key,
                        price_usd=float(best.get("priceUsd", 0) or 0),
                        liquidity_usd=float(best.get("liquidity", {}).get("usd", 0) or 0),
                        market_cap_usd=float(best.get("fdv", 0) or 0),
                        source="dexscreener",
                    )
        except Exception:
            return None

    # ---- Balance ----

    async def get_balance(self, wallet_address: str, token_address: str) -> Optional[WalletBalance]:
        try:
            if token_address == NATIVE_MINT:
                data = await self._rpc_call("getBalance", [wallet_address])
                if data is not None:
                    return WalletBalance(
                        wallet_address=wallet_address,
                        token_address=token_address,
                        chain_key=self.chain_key,
                        amount_decimal=Decimal(data) / Decimal(10**9),
                        amount_usd=None,
                    )
            else:
                data = await self._rpc_call("getTokenAccountsByOwner", [
                    wallet_address,
                    {"mint": token_address},
                    {"encoding": "jsonParsed"},
                ])
                if data and data.get("value"):
                    for acc in data["value"]:
                        info = acc.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
                        amt = info.get("tokenAmount", {})
                        return WalletBalance(
                            wallet_address=wallet_address,
                            token_address=token_address,
                            chain_key=self.chain_key,
                            amount_decimal=Decimal(amt.get("amount", "0")) / Decimal(10 ** amt.get("decimals", 6)),
                            amount_usd=None,
                        )
        except Exception:
            pass
        return None

    # ---- Block ----

    async def get_latest_block(self) -> int:
        data = await self._rpc_call("getSlot", [])
        return data or 0

    async def get_block_timestamp(self, block_number: int) -> Optional[datetime]:
        data = await self._rpc_call("getBlockTime", [block_number])
        if data:
            return datetime.fromtimestamp(data, tz=timezone.utc)
        return None

    # ---- Health ----

    async def is_healthy(self) -> bool:
        try:
            result = await self._rpc_call("getHealth", [])
            return result == "ok"
        except Exception:
            return False

    # ---- Backfill ----

    async def get_wallet_transactions(
        self,
        wallet_address: str,
        from_block: Optional[int] = None,
        limit: int = 100,
    ) -> list[RawTransaction]:
        result = []
        try:
            sigs_data = await self._rpc_call("getSignaturesForAddress", [
                wallet_address,
                {"limit": limit},
            ])
            if not sigs_data:
                return []
            for sig_info in sigs_data:
                sig = sig_info.get("signature")
                if not sig:
                    continue
                slot = sig_info.get("slot")
                block_time = sig_info.get("blockTime")
                block_ts = datetime.fromtimestamp(block_time, tz=timezone.utc) if block_time else None
                result.append(RawTransaction(
                    tx_hash=sig,
                    chain_key=self.chain_key,
                    wallet_address=wallet_address,
                    block_number=slot,
                    block_timestamp=block_ts,
                    gas_used=None,
                    gas_price=None,
                    raw=sig_info,
                ))
        except Exception as exc:
            logger.warning("Solana backfill error", extra={"error": str(exc)})
        return result

    # ---- Internal RPC ----

    async def _rpc_call(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self._rpc_http,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if "error" in data:
                    return None
                return data.get("result")
