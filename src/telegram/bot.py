"""Main Telegram bot — wires together commands, callbacks and alert sending."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from src.analytics.ranking import get_wallet_ranking
from src.config import get_settings
from src.database.connection import AsyncSessionLocal
from src.database.models import Position, PositionStatus, Trade, TradeSide, Wallet, WalletMetrics
from src.telegram.alerts import (
    format_buy_alert,
    format_consensus_alert,
    format_paper_trade,
    format_risk_blocked,
    format_sell_alert,
    format_system_alert,
    format_wallet_stats,
)
from src.telegram.commands import CommandHandlers
from src.telegram.keyboards import trade_alert_keyboard, wallet_detail_keyboard

logger = logging.getLogger(__name__)
settings = get_settings()

# Alert cooldown: (wallet_id, position_id) -> last_alert_at
_position_alert_cooldown: dict[tuple, datetime] = {}
_COOLDOWN_SECONDS = 300  # 5 min
_MIN_PCT_CHANGE = 5.0    # minimum % change to trigger position update


class SnipeBot:
    def __init__(self, redis: aioredis.Redis) -> None:
        self._redis = redis
        self._chat_ids = settings.allowed_chat_ids
        self._admin_ids = set(settings.admin_ids)
        self._app: Optional[Application] = None
        self._cmd = CommandHandlers(self)
        self._live_enabled = settings.copy_trading_live_enabled
        self._emergency_stopped = False

    async def build(self) -> None:
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")

        self._app = (
            Application.builder()
            .token(settings.telegram_bot_token)
            .build()
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        app = self._app
        cmd = self._cmd
        app.add_handler(CommandHandler("start", cmd.start))
        app.add_handler(CommandHandler("help", cmd.help_cmd))
        app.add_handler(CommandHandler("addwallet", cmd.add_wallet))
        app.add_handler(CommandHandler("removewallet", cmd.remove_wallet))
        app.add_handler(CommandHandler("listwallets", cmd.list_wallets))
        app.add_handler(CommandHandler("wallet", cmd.wallet_info))
        app.add_handler(CommandHandler("ranking", cmd.ranking))
        app.add_handler(CommandHandler("positions", cmd.positions))
        app.add_handler(CommandHandler("health", cmd.health))
        app.add_handler(CommandHandler("emergency", cmd.emergency_stop))
        app.add_handler(CommandHandler("backtest", cmd.backtest))
        app.add_handler(CommandHandler("toptrades", cmd.top_trades))
        app.add_handler(CommandHandler("settings", cmd.settings))
        app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start_polling(self) -> None:
        if not self._app:
            await self.build()
        logger.info("Starting Telegram bot polling")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    # ---- Alert dispatch ----

    async def send_trade_alert(self, alert_data: dict) -> None:
        """Called by TransactionEngine for every classified trade."""
        if not self._chat_ids:
            return

        wallet = alert_data["wallet"]
        token = alert_data["token"]
        chain = alert_data["chain"]
        trade = alert_data["trade"]
        position = alert_data["position"]
        classified = alert_data["classified"]
        tx_hash = alert_data["tx_hash"]
        price_usd = alert_data["price_usd"]
        value_usd = alert_data["value_usd"]
        latency_ms = alert_data["latency_ms"]
        realized_pnl = alert_data["realized_pnl"]

        label = wallet.label or wallet.address[:10]
        chain_name = chain.name

        explorer_map = {
            "ethereum": "https://etherscan.io",
            "base": "https://basescan.org",
            "arbitrum": "https://arbiscan.io",
            "bsc": "https://bscscan.com",
            "polygon": "https://polygonscan.com",
            "optimism": "https://optimistic.etherscan.io",
            "avalanche": "https://snowscan.xyz",
            "solana": "https://solscan.io",
        }
        explorer = explorer_map.get(chain.chain_key, "https://etherscan.io")

        if trade.side == TradeSide.BUY:
            text = format_buy_alert(
                wallet_label=label,
                chain_name=chain_name,
                token_symbol=token.symbol,
                token_address=token.address,
                price_usd=price_usd,
                invested_usd=value_usd,
                tx_hash=tx_hash,
                latency_ms=latency_ms,
                is_new_position=(position.total_bought_quantity == classified.base_amount),
            )
            keyboard = trade_alert_keyboard(
                tx_hash=tx_hash,
                token_address=token.address,
                wallet_address=wallet.address,
                chain_key=chain.chain_key,
                explorer_url=explorer,
            )
        else:
            # SELL
            hold_secs = 0
            if position.first_buy_at:
                hold_secs = int((datetime.now(timezone.utc) - position.first_buy_at).total_seconds())
            remaining = 100.0 - position.percentage_sold

            text = format_sell_alert(
                wallet_label=label,
                chain_name=chain_name,
                token_symbol=token.symbol,
                pct_sold=float(classified.base_amount / position.total_bought_quantity * 100)
                if position.total_bought_quantity > 0 else 0,
                proceeds_usd=value_usd,
                realized_pnl=realized_pnl,
                roi_percent=trade.roi_percent or 0,
                hold_time_seconds=hold_secs,
                tx_hash=tx_hash,
                remaining_pct=remaining,
                entry_price=position.average_entry_usd,
                sell_price=price_usd,
            )
            keyboard = trade_alert_keyboard(
                tx_hash=tx_hash,
                token_address=token.address,
                wallet_address=wallet.address,
                chain_key=chain.chain_key,
                explorer_url=explorer,
            )

        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except Exception as exc:
                logger.error("Telegram send failed", extra={"chat_id": chat_id, "error": str(exc)})

    async def send_position_update(self, position_data: dict) -> None:
        """Periodic position price update with cooldown."""
        wallet_id = position_data["wallet_id"]
        position_id = position_data["position_id"]
        key = (wallet_id, position_id)
        now = datetime.now(timezone.utc)

        last = _position_alert_cooldown.get(key)
        if last and (now - last).total_seconds() < _COOLDOWN_SECONDS:
            return
        roi_change = abs(position_data.get("roi_change", 0))
        if roi_change < _MIN_PCT_CHANGE:
            return

        _position_alert_cooldown[key] = now
        from src.telegram.alerts import format_position_update
        text = format_position_update(**position_data)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.error("Position update send failed", extra={"error": str(exc)})

    async def send_consensus_alert(self, consensus_data: dict) -> None:
        text = format_consensus_alert(**consensus_data)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.error("Consensus alert send failed", extra={"error": str(exc)})

    async def send_system_alert(self, chain: str, issue: str, status: str, details: str = "") -> None:
        text = format_system_alert(chain, issue, status, details)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception:
                pass

    # ---- Callback queries ----

    async def _handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        data = query.data or ""

        if data.startswith("wallet:"):
            address = data.split(":", 1)[1]
            wallet_data = await self.get_wallet_data(address)
            if wallet_data:
                text = format_wallet_stats(**wallet_data)
                await query.edit_message_text(
                    text=text, parse_mode=ParseMode.HTML,
                    reply_markup=wallet_detail_keyboard(address),
                )

        elif data.startswith("chain:"):
            chain_key = data.split(":", 1)[1]
            ranking = await self.get_ranking(chain_key=chain_key if chain_key != "all" else None)
            from src.telegram.alerts import format_ranking
            from src.telegram.keyboards import chain_filter_keyboard
            text = format_ranking(ranking)
            await query.edit_message_text(
                text=text, parse_mode=ParseMode.HTML,
                reply_markup=chain_filter_keyboard(chain_key),
            )

        elif data.startswith("confirm:remove_wallet:"):
            address = data.split(":", 2)[2]
            await self.remove_wallet(address)
            await query.edit_message_text(f"✅ Wallet {address[:10]}... removed.")

        elif data.startswith("pause_wallet:"):
            address = data.split(":", 1)[1]
            await self.pause_wallet(address)
            await query.edit_message_text(f"⏸️ Wallet {address[:10]}... paused.")

        elif data == "cancel":
            await query.edit_message_text("Cancelled.")

    # ---- Bot actions (called by commands) ----

    async def add_wallet(
        self,
        address: str,
        chain_key: str,
        label: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> dict:
        from src.database.connection import AsyncSessionLocal
        from src.database.repositories.wallet_repo import WalletRepository

        # Validate chain
        async with AsyncSessionLocal() as session:
            wallet_repo = WalletRepository(session)
            chain = await wallet_repo.get_chain_by_key(chain_key)
            if not chain or not chain.enabled:
                return {"success": False, "error": f"Chain '{chain_key}' not supported or disabled."}

            existing = await wallet_repo.get_by_address(address)
            if existing:
                # Add chain
                await wallet_repo.add_chain(existing.id, chain.id)
                await session.commit()
                wallet = existing
            else:
                wallet = await wallet_repo.create(
                    address=address,
                    label=label,
                    added_by_chat_id=chat_id,
                )
                await wallet_repo.add_chain(wallet.id, chain.id)
                await session.commit()

        # Subscribe to chain events
        from src.core.wallet_manager import WalletManager
        wm = self._get_wallet_manager()
        if wm:
            await wm.add_wallet(address, [chain_key])

        return {"success": True, "wallet_id": wallet.id}

    async def remove_wallet(self, address: str) -> None:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if wallet:
                await repo.update(wallet, enabled=False)
                await session.commit()
        wm = self._get_wallet_manager()
        if wm:
            await wm.remove_wallet(address)

    async def pause_wallet(self, address: str) -> None:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if wallet:
                await repo.update(wallet, enabled=False)
                await session.commit()

    async def list_wallets(self) -> list[dict]:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallets = await repo.list_enabled()
            result = []
            for w in wallets:
                chains = [wc.chain.chain_key for wc in w.chains if wc.enabled]
                result.append({
                    "address": w.address,
                    "label": w.label or w.address[:10],
                    "chains": chains,
                    "enabled": w.enabled,
                    "score": w.smart_money_score,
                    "flags": w.risk_flags or [],
                })
            return result

    async def get_wallet_data(self, address: str) -> Optional[dict]:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if not wallet:
                return None

            result = await session.execute(
                select(WalletMetrics).where(
                    WalletMetrics.wallet_id == wallet.id,
                    WalletMetrics.chain_key == None,
                )
            )
            metrics = result.scalar_one_or_none()
            if not metrics:
                return None

            from src.analytics.smart_money_score import compute_score
            breakdown = compute_score(metrics, wallet)
            return {
                "label": wallet.label or wallet.address[:10],
                "address": wallet.address,
                "score": metrics.smart_money_score or 0,
                "total_trades": metrics.total_trades,
                "win_rate": metrics.win_rate,
                "avg_roi": metrics.average_roi,
                "total_pnl": metrics.total_pnl_usd,
                "avg_hold_seconds": metrics.avg_holding_seconds,
                "best_trade": metrics.best_trade_roi,
                "worst_trade": metrics.worst_trade_roi,
                "score_breakdown": breakdown.to_dict() if metrics.score_breakdown else None,
                "flags": wallet.risk_flags or [],
            }

    async def get_positions(self, wallet_address: Optional[str] = None) -> list[dict]:
        async with AsyncSessionLocal() as session:
            q = select(Position).where(Position.status == PositionStatus.OPEN)
            if wallet_address:
                from src.database.repositories.wallet_repo import WalletRepository
                repo = WalletRepository(session)
                w = await repo.get_by_address(wallet_address)
                if w:
                    q = q.where(Position.wallet_id == w.id)

            result = await session.execute(q)
            positions = result.scalars().all()

            out = []
            for p in positions:
                token_r = await session.get_one(type(p.token_id), p.token_id) if hasattr(p, "token") else None
                # Simplified since relationships may not be loaded
                out.append({
                    "token_symbol": "???",
                    "chain": "???",
                    "entry": p.average_entry_usd or 0,
                    "current": p.current_price_usd or 0,
                    "invested": p.total_invested_usd,
                    "roi": p.roi_percent,
                })
            return out

    async def get_ranking(self, chain_key: Optional[str] = None) -> list[dict]:
        async with AsyncSessionLocal() as session:
            return await get_wallet_ranking(session, chain_key=chain_key, limit=20)

    async def get_top_trades(self) -> list[dict]:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.trade_repo import TradeRepository
            repo = TradeRepository(session)
            trades = await repo.get_top_by_roi(min_roi=50, min_value_usd=100, limit=20)
            return [
                {
                    "roi": t.roi_percent or 0,
                    "wallet": "Unknown",
                    "token": "???",
                    "invested": t.value_usd or 0,
                    "value": (t.value_usd or 0) * (1 + (t.roi_percent or 0) / 100),
                }
                for t in trades
            ]

    async def run_backtest(self, address: str, period: str) -> Optional[dict]:
        from src.backtesting.engine import BacktestEngine
        engine = BacktestEngine()
        return await engine.run(address, period)

    async def health_check(self) -> dict[str, bool]:
        wm = self._get_wallet_manager()
        if wm:
            return await wm.health_check()
        return {}

    async def emergency_stop(self) -> None:
        self._emergency_stopped = True
        self._live_enabled = False
        logger.warning("EMERGENCY STOP activated")

    async def get_settings(self) -> dict:
        return {
            "copy_mode": "live" if self._live_enabled and not self._emergency_stopped else "paper",
            "copy_pct": settings.copy_trading_default_copy_percent,
            "max_trade": settings.copy_trading_max_trade_size_usd,
            "min_score": 80,
            "min_investment": 500,
            "min_liquidity": 50000,
        }

    def _get_wallet_manager(self):
        # Injected at runtime
        return getattr(self, "_wallet_manager", None)

    def set_wallet_manager(self, wm) -> None:
        self._wallet_manager = wm
