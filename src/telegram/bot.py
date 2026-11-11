"""Telegram bot — multi-menu FSM with inline keyboard navigation.

Menu architecture:
  Main → Wallets | Track | Ranking | Consensus | Analytics | Settings | Help
  Wallets → list (paginated) → wallet detail → stats/trades/positions/backtest
  Track → address input → chain auto-detect → chain select → label → confirm
  Ranking → chain filter + pagination
  Settings → toggle alerts / set thresholds

State machine stored in Redis (tg:state:{chat_id}).
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
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
    MessageHandler,
    filters,
)

from src.analytics.ranking import get_wallet_ranking
from src.chains.chain_detector import get_chain_explorer, get_dexscreener_chain_slug
from src.config import get_settings
from src.database.connection import AsyncSessionLocal
from src.database.models import Position, PositionStatus, Trade, TradeSide, Wallet, WalletMetrics
from src.telegram import menus
from src.telegram.alerts import (
    format_buy_alert,
    format_consensus_alert,
    format_paper_trade,
    format_position_update,
    format_risk_blocked,
    format_sell_alert,
    format_system_alert,
    format_wallet_stats,
    format_number,
)
from src.telegram.keyboards import (
    alert_filters_keyboard,
    back_keyboard,
    cancel_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    settings_keyboard,
    trade_alert_keyboard,
    wallet_detail_keyboard,
)
from src.telegram.menus import (
    clear_state,
    get_data,
    get_state,
    handle_chain_confirm,
    handle_chain_toggle,
    handle_watchlist_quickadd,
    handle_watchlist_remove,
    set_state,
    show_add_wallet_prompt,
    show_alert_filters_view,
    show_analytics,
    show_consensus,
    show_daily_summary,
    show_discover,
    show_help,
    show_hotlist,
    show_main_menu,
    show_open_positions,
    show_portfolio,
    show_ranking,
    show_settings,
    show_trade_history_view,
    show_wallet_detail,
    show_wallets_menu,
    show_watchlist,
    handle_export_csv,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Alert cooldown
_position_alert_cooldown: dict[tuple, datetime] = {}
_COOLDOWN_SECONDS = 300
_MIN_PCT_CHANGE = 5.0

# Redis keys
def _user_settings_key(chat_id: int) -> str:
    return f"tg:user_settings:{chat_id}"

def _alerts_muted_key(chat_id: int) -> str:
    return f"tg:alerts_muted:{chat_id}"

def _trade_alert_cooldown_key(wallet: str, token: str) -> str:
    return f"alert:cooldown:{wallet[:20]}:{token[:20]}"


class SnipeBot:
    def __init__(
        self,
        token: str,
        chat_ids: list[int],
        admin_ids: list[int],
        redis: aioredis.Redis,
        wallet_manager=None,
        paper_trader=None,
        live_trader=None,
    ) -> None:
        self._token = token
        self._chat_ids = chat_ids
        self._admin_ids = set(admin_ids or [])
        self._redis = redis
        self._wallet_manager = wallet_manager
        self._paper_trader = paper_trader
        self._live_trader = live_trader
        self._live_enabled = settings.copy_trading_live_enabled
        self._emergency_stopped = False
        self._app: Optional[Application] = None

    # ── Build & lifecycle ──────────────────────────────

    async def build(self) -> None:
        if not self._token:
            raise ValueError("TELEGRAM_BOT_TOKEN is not set")
        self._app = Application.builder().token(self._token).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        app = self._app

        # Commands
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("menu", self._cmd_start))
        app.add_handler(CommandHandler("track", self._cmd_track))
        app.add_handler(CommandHandler("add", self._cmd_track))
        app.add_handler(CommandHandler("wallets", self._cmd_wallets))
        app.add_handler(CommandHandler("wallet", self._cmd_wallet))
        app.add_handler(CommandHandler("ranking", self._cmd_ranking))
        app.add_handler(CommandHandler("portfolio", self._cmd_portfolio))
        app.add_handler(CommandHandler("hotlist", self._cmd_hotlist))
        app.add_handler(CommandHandler("positions", self._cmd_positions))
        app.add_handler(CommandHandler("health", self._cmd_health))
        app.add_handler(CommandHandler("emergency", self._cmd_emergency))
        app.add_handler(CommandHandler("settings", self._cmd_settings))
        app.add_handler(CommandHandler("backtest", self._cmd_backtest))
        app.add_handler(CommandHandler("toptrades", self._cmd_toptrades))
        app.add_handler(CommandHandler("watchlist", self._cmd_watchlist))
        app.add_handler(CommandHandler("export", self._cmd_export))
        app.add_handler(CommandHandler("daily", self._cmd_daily))

        # Text messages (address input, label input, etc.)
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text)
        )

        # Callbacks
        app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def run_polling(self) -> None:
        """Start the bot with polling (non-blocking — runs until cancelled)."""
        if not self._app:
            await self.build()
        logger.info("Starting Telegram bot polling")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        # Keep alive until cancelled
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def stop(self) -> None:
        if self._app and self._app.running:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    # ── Commands ───────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await clear_state(self, update.effective_chat.id)
        await show_main_menu(self, update)

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_help(self, update)

    async def _cmd_track(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if ctx.args:
            # /track 0xABCD...
            address = ctx.args[0]
            await set_state(self, update.effective_chat.id, menus.STATE_AWAITING_ADDRESS)
            await menus._handle_address_input(self, update, address)
        else:
            await show_add_wallet_prompt(self, update)

    async def _cmd_wallets(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_wallets_menu(self, update)

    async def _cmd_wallet(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("Usage: /wallet <address>")
            return
        await show_wallet_detail(self, update, ctx.args[0])

    async def _cmd_ranking(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chain = ctx.args[0].lower() if ctx.args else "all"
        await show_ranking(self, update, chain_key=chain)

    async def _cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        address = ctx.args[0] if ctx.args else None
        pos_list = await self.get_positions(wallet_address=address)
        if not pos_list:
            await update.message.reply_html("📈 Aucune position ouverte.", reply_markup=main_menu_keyboard())
            return
        lines = ["📈 <b>Positions ouvertes</b>\n"]
        for p in pos_list[:10]:
            roi_str = f"{p['roi']:.1f}%" if p.get("roi") is not None else "N/A"
            emoji = "🚀" if (p.get("roi") or 0) > 50 else ("📈" if (p.get("roi") or 0) > 0 else "📉")
            lines.append(
                f"{emoji} <b>{p['token_symbol']}</b> ({p['chain']})\n"
                f"   Entry: ${p['entry']:.6f} | Now: ${p['current']:.6f}\n"
                f"   ROI: <b>{roi_str}</b>"
            )
        await update.message.reply_html("\n\n".join(lines), reply_markup=main_menu_keyboard())

    async def _cmd_health(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        status = await self.health_check()
        lines = ["🔧 <b>Système</b>\n"]
        for chain, healthy in status.items():
            icon = "🟢" if healthy else "🔴"
            lines.append(f"{icon} {chain}")
        if not status:
            lines.append("Aucun adapter actif.")
        await update.message.reply_html("\n".join(lines), reply_markup=back_keyboard("menu:main"))

    async def _cmd_emergency(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user and update.effective_user.id not in self._admin_ids:
            await update.message.reply_text("⛔ Non autorisé.")
            return
        await self.emergency_stop()
        await update.message.reply_html(
            "🛑 <b>EMERGENCY STOP</b>\n\n"
            "Copy trading live: <b>DÉSACTIVÉ</b>\n"
            "Tracking wallets: <b>ACTIF</b>"
        )

    async def _cmd_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_settings(self, update)

    async def _cmd_backtest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args or len(ctx.args) < 1:
            await update.message.reply_text("Usage: /backtest <address> [7d|30d|90d]")
            return
        address = ctx.args[0]
        period = ctx.args[1].lower() if len(ctx.args) > 1 else "30d"
        await update.message.reply_text("⏳ Backtest en cours...")
        result = await self.run_backtest(address, period)
        if not result:
            await update.message.reply_html("❌ Pas assez de données pour ce wallet.")
            return
        text = (
            f"🔬 <b>BACKTEST — {result.get('label', address[:10])}</b>\n\n"
            f"Période: <b>{period}</b>\n"
            f"Trades: <b>{result.get('trades', 0)}</b>\n"
            f"Win rate: <b>{result.get('win_rate', 0):.1f}%</b>\n"
            f"ROI moyen: <b>{result.get('avg_roi', 0):.1f}%</b>\n"
            f"PnL total: <b>${result.get('total_pnl', 0):,.0f}</b>\n"
            f"Max drawdown: <b>-{result.get('max_dd', 0):.1f}%</b>\n"
            f"Meilleur trade: <b>+{result.get('best_roi', 0):.1f}%</b>\n"
            f"Pire trade: <b>{result.get('worst_roi', 0):.1f}%</b>\n"
            f"Profit factor: <b>{result.get('profit_factor', 0):.1f}</b>\n\n"
            f"🏆 Score: <b>{result.get('score', 0):.0f}/100</b>"
        )
        await update.message.reply_html(text, reply_markup=wallet_detail_keyboard(address))

    async def _cmd_toptrades(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        trades = await self.get_top_trades()
        if not trades:
            await update.message.reply_html("💎 Aucun top trade pour l'instant.")
            return
        lines = ["💎 <b>TOP TRADES</b>\n"]
        for t in trades[:10]:
            lines.append(
                f"+{t['roi']:.0f}% — <b>{t['wallet']}</b> → {t['token']}\n"
                f"   ${format_number(t['invested'])} → ${format_number(t['value'])}"
            )
        await update.message.reply_html("\n\n".join(lines), reply_markup=main_menu_keyboard())

    async def _cmd_portfolio(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_portfolio(self, update)

    async def _cmd_hotlist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_hotlist(self, update)

    async def _cmd_watchlist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_watchlist(self, update)

    async def _cmd_export(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        from src.telegram.keyboards import export_keyboard
        await update.message.reply_html(
            "📤 <b>Export de données</b>\n\nChoisir la période :",
            reply_markup=export_keyboard(),
        )

    async def _cmd_daily(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await show_daily_summary(self, update)

    async def _is_alert_on_cooldown(self, wallet_address: str, token_address: str) -> bool:
        key = _trade_alert_cooldown_key(wallet_address, token_address)
        exists = await self._redis.exists(key)
        if exists:
            return True
        await self._redis.setex(key, _COOLDOWN_SECONDS, "1")
        return False

    # ── Text message router ────────────────────────────

    async def _handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_chat:
            return
        await menus.handle_text_message(self, update, ctx)

    # ── Callback router ────────────────────────────────

    async def _handle_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        data = query.data or ""
        chat_id = update.effective_chat.id

        # Main menu navigation
        if data == "menu:main":
            await clear_state(self, chat_id)
            await show_main_menu(self, update, edit=True)

        elif data == "menu:wallets":
            await show_wallets_menu(self, update, edit=True)

        elif data == "menu:add_wallet":
            await show_add_wallet_prompt(self, update, edit=True)

        elif data == "menu:ranking":
            await show_ranking(self, update, edit=True)

        elif data == "menu:consensus":
            await show_consensus(self, update, edit=True)

        elif data == "menu:analytics":
            await show_analytics(self, update, edit=True)

        elif data == "menu:settings":
            await show_settings(self, update, edit=True)

        elif data == "menu:help":
            await show_help(self, update, edit=True)

        elif data == "menu:portfolio":
            await show_portfolio(self, update, edit=True)

        elif data == "menu:hotlist":
            await show_hotlist(self, update, edit=True)

        elif data == "menu:discover":
            await show_discover(self, update, edit=True)

        elif data == "menu:positions":
            await show_open_positions(self, update, edit=True)

        elif data == "menu:watchlist":
            await show_watchlist(self, update, edit=True)

        elif data == "positions:refresh":
            await show_open_positions(self, update, edit=True)

        # Watchlist actions
        elif data.startswith("watchlist:quickadd:"):
            parts = data.split(":", 3)
            chain_key = parts[2] if len(parts) > 2 else ""
            token_addr = parts[3] if len(parts) > 3 else ""
            await handle_watchlist_quickadd(self, update, chain_key, token_addr)

        elif data.startswith("watchlist:remove:"):
            parts = data.split(":", 3)
            chain_key = parts[2] if len(parts) > 2 else ""
            token_addr = parts[3] if len(parts) > 3 else ""
            await handle_watchlist_remove(self, update, chain_key, token_addr)

        # Export
        elif data.startswith("export:trades:"):
            period = data.split(":")[2]
            await handle_export_csv(self, update, period=period)

        elif data.startswith("export:positions:csv"):
            positions = await self.get_positions()
            if not positions:
                await query.answer("Aucune position ouverte.", show_alert=True)
                return
            import csv, io
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=["token_symbol", "chain", "roi", "invested"])
            writer.writeheader()
            for p in positions:
                writer.writerow({
                    "token_symbol": p.get("token_symbol", ""),
                    "chain": p.get("chain", ""),
                    "roi": p.get("roi", ""),
                    "invested": p.get("invested", ""),
                })
            csv_bytes = buf.getvalue().encode("utf-8")
            msg = query.message
            await msg.reply_document(
                document=io.BytesIO(csv_bytes),
                filename="positions.csv",
                caption=f"📤 Export positions ({len(positions)} positions)",
            )
            await query.answer()

        # Wallet pagination
        elif data.startswith("wallets:page:"):
            page = int(data.split(":")[2])
            await show_wallets_menu(self, update, page=page, edit=True)

        # Wallet detail
        elif data.startswith("wallet:detail:"):
            address = data.split(":", 2)[2]
            await show_wallet_detail(self, update, address, edit=True)

        elif data.startswith("wallet:stats:"):
            address = data.split(":", 2)[2]
            await show_wallet_detail(self, update, address, edit=True)

        elif data.startswith("wallet:trades:"):
            address = data.split(":", 2)[2]
            await self._show_wallet_trades(update, address)

        elif data.startswith("wallet:history:"):
            parts = data.split(":")
            address = parts[2]
            page = int(parts[3]) if len(parts) > 3 else 0
            await show_trade_history_view(self, update, address, page=page, edit=True)

        elif data.startswith("wallet:filters:"):
            address = data.split(":", 2)[2]
            await show_alert_filters_view(self, update, address, edit=True)

        elif data.startswith("wallet:positions:"):
            address = data.split(":", 2)[2]
            await self._show_wallet_positions(update, address)

        elif data.startswith("wallet:backtest:"):
            parts = data.split(":")
            address = parts[2]
            period = parts[3] if len(parts) > 3 else "30d"
            await self._do_backtest_callback(update, address, period)

        elif data.startswith("wallet:pause:"):
            address = data.split(":", 2)[2]
            await self.pause_wallet(address)
            await query.edit_message_text(
                f"⏸ Wallet <code>{address[:16]}...</code> mis en pause.",
                parse_mode=ParseMode.HTML,
                reply_markup=wallet_detail_keyboard(address, is_paused=True),
            )

        elif data.startswith("wallet:resume:"):
            address = data.split(":", 2)[2]
            await self.resume_wallet(address)
            await query.edit_message_text(
                f"▶️ Wallet <code>{address[:16]}...</code> reprend le tracking.",
                parse_mode=ParseMode.HTML,
                reply_markup=wallet_detail_keyboard(address, is_paused=False),
            )

        elif data.startswith("wallet:remove_confirm:"):
            address = data.split(":", 2)[2]
            await query.edit_message_text(
                f"⚠️ Supprimer le wallet <code>{address[:20]}...</code> ?",
                parse_mode=ParseMode.HTML,
                reply_markup=confirm_keyboard(f"remove_wallet:{address}", "Supprimer"),
            )

        # Chain selection
        elif data.startswith("chain_sel:"):
            parts = data.split(":", 2)
            address, chain_key = parts[1], parts[2]
            await handle_chain_toggle(self, update, address, chain_key)

        elif data.startswith("chain_sel_confirm:"):
            parts = data.split(":", 2)
            address = parts[1]
            chains = parts[2].split(",") if parts[2] else []
            await handle_chain_confirm(self, update, address, chains)

        # Ranking
        elif data.startswith("ranking:chain:"):
            parts = data.split(":")
            chain_key = parts[2]
            page = int(parts[3]) if len(parts) > 3 else 0
            await show_ranking(self, update, chain_key=chain_key, page=page, edit=True)

        elif data.startswith("ranking:page:"):
            parts = data.split(":")
            page = int(parts[2])
            chain_key = parts[3] if len(parts) > 3 else "all"
            await show_ranking(self, update, chain_key=chain_key, page=page, edit=True)

        # Analytics
        elif data == "analytics:top_trades":
            trades = await self.get_top_trades()
            if not trades:
                await query.edit_message_text("💎 Aucun top trade.", reply_markup=back_keyboard("menu:analytics"))
                return
            lines = ["💎 <b>TOP TRADES</b>\n"]
            for t in trades[:10]:
                lines.append(f"+{t['roi']:.0f}% — <b>{t['wallet']}</b>\n   ${format_number(t['invested'])} → ${format_number(t['value'])}")
            await query.edit_message_text(
                "\n\n".join(lines), parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard("menu:analytics"),
            )

        elif data == "analytics:positions":
            pos_list = await self.get_positions()
            if not pos_list:
                await query.edit_message_text("📈 Aucune position ouverte.", reply_markup=back_keyboard("menu:analytics"))
                return
            lines = ["📈 <b>Positions ouvertes</b>\n"]
            for p in pos_list[:10]:
                roi = p.get("roi") or 0
                em = "🚀" if roi > 50 else ("📈" if roi > 0 else "📉")
                lines.append(f"{em} <b>{p['token_symbol']}</b> ({p['chain']}) — ROI: <b>{roi:.1f}%</b>")
            await query.edit_message_text(
                "\n\n".join(lines), parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard("menu:analytics"),
            )

        elif data == "analytics:chain_activity":
            from src.telegram.alerts import format_chain_activity
            stats = await self._get_chain_activity_stats()
            text = format_chain_activity(stats)
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard("menu:analytics"))

        # Portfolio
        elif data in ("portfolio:refresh", "portfolio:by_chain", "portfolio:top_gains", "portfolio:top_losses"):
            await show_portfolio(self, update, edit=True)

        # Hotlist
        elif data == "hotlist:refresh":
            await show_hotlist(self, update, edit=True)

        elif data.startswith("hotlist:page:"):
            page = int(data.split(":")[2])
            await show_hotlist(self, update, page=page, edit=True)

        elif data.startswith("hotlist:chain:"):
            chain = data.split(":")[2]
            await show_hotlist(self, update, chain_filter=chain, edit=True)

        # Discover
        elif data.startswith("discover:"):
            await show_discover(self, update, edit=True)

        # Alert filters
        elif data.startswith("filter:min_usd:"):
            address = data.split(":", 2)[2]
            await set_state(self, chat_id, menus.STATE_AWAITING_FILTER_USD, {"wallet_address": address})
            await query.edit_message_text(
                f"💵 Entre le montant minimum en USD pour les alertes de ce wallet:\n<i>Ex: 1000</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=cancel_keyboard(),
            )

        elif data.startswith("filter:min_score:"):
            address = data.split(":", 2)[2]
            await set_state(self, chat_id, menus.STATE_AWAITING_FILTER_SCORE, {"wallet_address": address})
            await query.edit_message_text(
                f"🏆 Entre le score minimum Smart Money (0-100):\n<i>Ex: 70</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=cancel_keyboard(),
            )

        elif data.startswith("filter:mute:"):
            address = data.split(":", 2)[2]
            muted_key = f"tg:alerts_muted:{chat_id}:{address}"
            await self._redis.setex(muted_key, 86400 * 30, "1")
            await show_alert_filters_view(self, update, address, edit=True)

        elif data.startswith("filter:unmute:"):
            address = data.split(":", 2)[2]
            muted_key = f"tg:alerts_muted:{chat_id}:{address}"
            await self._redis.delete(muted_key)
            await show_alert_filters_view(self, update, address, edit=True)

        elif data.startswith("filter:reset:"):
            address = data.split(":", 2)[2]
            filters_key = f"tg:wallet_filters:{chat_id}:{address}"
            await self._redis.delete(filters_key)
            await show_alert_filters_view(self, update, address, edit=True)

        # Settings
        elif data == "settings:toggle_alerts":
            current = await self._redis.get(_alerts_muted_key(chat_id))
            if current:
                await self._redis.delete(_alerts_muted_key(chat_id))
                is_enabled = True
            else:
                await self._redis.setex(_alerts_muted_key(chat_id), 86400 * 30, "1")
                is_enabled = False
            cfg = await self.get_settings()
            await query.edit_message_text(
                f"{'🔔 Alertes activées.' if is_enabled else '🔕 Alertes coupées.'}",
                parse_mode=ParseMode.HTML,
                reply_markup=settings_keyboard(
                    alerts_enabled=is_enabled,
                    min_trade_usd=cfg.get("min_trade_usd", 500),
                    min_score=cfg.get("min_score", 70),
                ),
            )

        elif data == "settings:set_min_trade":
            await set_state(self, chat_id, menus.STATE_AWAITING_MIN_TRADE)
            await query.edit_message_text(
                "💵 Entre le montant minimum en USD pour les alertes:\n<i>Ex: 500</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=cancel_keyboard(),
            )

        elif data == "settings:set_min_score":
            await set_state(self, chat_id, menus.STATE_AWAITING_MIN_SCORE)
            await query.edit_message_text(
                "🏆 Entre le score minimum Smart Money (0-100):\n<i>Ex: 70</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=cancel_keyboard(),
            )

        elif data == "settings:info":
            total = await self.count_tracked_wallets()
            from src.chains.chain_detector import CHAIN_RPC_MAP
            text = (
                f"ℹ️ <b>Snipe Token Bot</b>\n\n"
                f"👛 Wallets trackés: <b>{total}</b>\n"
                f"⛓️ Chains supportées: <b>{len(CHAIN_RPC_MAP)}</b>\n"
                f"🏗️ Mode: <b>{'Live' if self._live_enabled else 'Paper'}</b>\n"
                f"🔧 Version: <b>2.0</b>"
            )
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard("menu:settings"))

        # Confirms / cancels
        elif data.startswith("confirm:remove_wallet:"):
            address = data.split(":", 2)[2]
            await self.remove_wallet(address)
            await query.edit_message_text(f"✅ Wallet supprimé.", reply_markup=back_keyboard("menu:wallets"))

        elif data == "cancel":
            await clear_state(self, chat_id)
            await show_main_menu(self, update, edit=True)

        # Token ignore
        elif data.startswith("ignore_token:"):
            parts = data.split(":")
            chain_key = parts[1] if len(parts) > 1 else ""
            token = parts[2] if len(parts) > 2 else ""
            await query.answer(f"Token ignoré: {token[:8]}...", show_alert=False)

        else:
            logger.debug("Unhandled callback: %s", data)

    # ── Wallet sub-menus ───────────────────────────────

    async def _show_wallet_trades(self, update: Update, address: str) -> None:
        query = update.callback_query
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            from src.database.repositories.trade_repo import TradeRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if not wallet:
                await query.edit_message_text("❌ Wallet non trouvé.", reply_markup=back_keyboard("menu:wallets"))
                return
            trade_repo = TradeRepository(session)
            trades = await trade_repo.get_by_wallet(wallet.id, limit=10)

        if not trades:
            await query.edit_message_text(
                f"💰 <b>Trades — {address[:12]}...</b>\n\nAucun trade enregistré.",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(f"wallet:detail:{address}"),
            )
            return

        lines = [f"💰 <b>Derniers trades</b> — <code>{address[:12]}...</code>\n"]
        for t in trades:
            side_icon = "🟢" if t.side == TradeSide.BUY else "🔴"
            roi = f" +{t.roi_percent:.0f}%" if (t.roi_percent or 0) > 0 else (f" {t.roi_percent:.0f}%" if t.roi_percent else "")
            lines.append(f"{side_icon} {t.token_symbol or '???'}{roi} — ${format_number(t.value_usd or 0)}")

        await query.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(f"wallet:detail:{address}"),
        )

    async def _show_wallet_positions(self, update: Update, address: str) -> None:
        query = update.callback_query
        pos_list = await self.get_positions(wallet_address=address)
        if not pos_list:
            await query.edit_message_text(
                f"📈 Aucune position ouverte pour <code>{address[:12]}...</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard(f"wallet:detail:{address}"),
            )
            return
        lines = [f"📈 <b>Positions — {address[:12]}...</b>\n"]
        for p in pos_list[:10]:
            roi = p.get("roi") or 0
            em = "🚀" if roi > 50 else ("📈" if roi > 0 else "📉")
            lines.append(f"{em} <b>{p['token_symbol']}</b> ROI: {roi:.1f}%")
        await query.edit_message_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(f"wallet:detail:{address}"),
        )

    async def _do_backtest_callback(self, update: Update, address: str, period: str) -> None:
        query = update.callback_query
        await query.edit_message_text("⏳ Backtest en cours...")
        result = await self.run_backtest(address, period)
        if not result:
            await query.edit_message_text(
                "❌ Pas assez de données.",
                reply_markup=back_keyboard(f"wallet:detail:{address}"),
            )
            return
        text = (
            f"🔬 <b>BACKTEST — {result.get('label', address[:10])}</b>\n\n"
            f"Période: <b>{period}</b>\n"
            f"Trades: <b>{result.get('trades', 0)}</b>\n"
            f"Win rate: <b>{result.get('win_rate', 0):.1f}%</b>\n"
            f"ROI moyen: <b>{result.get('avg_roi', 0):.1f}%</b>\n"
            f"PnL total: <b>${result.get('total_pnl', 0):,.0f}</b>\n"
            f"🏆 Score: <b>{result.get('score', 0):.0f}/100</b>"
        )
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard(f"wallet:detail:{address}"),
        )

    # ── Alert dispatch ─────────────────────────────────

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

        # Per-wallet+token cooldown (5 min)
        if await self._is_alert_on_cooldown(wallet.address, token.address):
            return

        label = wallet.label or wallet.address[:12]
        chain_key = chain.chain_key
        chain_name = chain.name
        explorer = get_chain_explorer(chain_key)
        dex_slug = get_dexscreener_chain_slug(chain_key)

        # Get wallet score for context
        score = getattr(wallet, "smart_money_score", None)

        # Safety check on BUY (non-blocking, best-effort)
        safety_text = ""
        if trade.side == TradeSide.BUY:
            try:
                from src.telegram.safety import check_token_safety, format_safety_result
                safety = await asyncio.wait_for(
                    check_token_safety(token.address, chain_key),
                    timeout=4,
                )
                if safety.get("checked") and safety.get("risk_level") in ("CRITICAL", "HIGH"):
                    safety_text = "\n\n" + format_safety_result(safety, token.symbol or "")
            except Exception:
                pass

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
                smart_money_score=score,
            )
            if safety_text:
                text += safety_text
        else:
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
                smart_money_score=score,
            )

        keyboard = trade_alert_keyboard(
            tx_hash=tx_hash,
            token_address=token.address,
            wallet_address=wallet.address,
            chain_key=chain_key,
            explorer_url=explorer,
            dexscreener_slug=dex_slug,
        )

        for chat_id in self._chat_ids:
            muted = await self._redis.get(_alerts_muted_key(chat_id))
            if muted:
                continue
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            except Exception as exc:
                logger.error("Telegram send failed chat=%s: %s", chat_id, exc)

    async def send_position_update(self, position_data: dict) -> None:
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
        text = format_position_update(**position_data)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.error("Position update send failed: %s", exc)

    async def send_consensus_alert(self, consensus_data: dict) -> None:
        text = format_consensus_alert(**consensus_data)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.error("Consensus alert send failed: %s", exc)

    async def send_system_alert(self, chain: str, issue: str, status: str, details: str = "") -> None:
        text = format_system_alert(chain, issue, status, details)
        for chat_id in self._chat_ids:
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
            except Exception:
                pass

    # ── Bot actions ────────────────────────────────────

    async def add_wallet_multi_chain(
        self,
        address: str,
        chain_keys: list[str],
        label: Optional[str] = None,
        chat_id: Optional[int] = None,
    ) -> dict:
        from src.database.repositories.wallet_repo import WalletRepository

        added_chains = []
        async with AsyncSessionLocal() as session:
            repo = WalletRepository(session)
            existing = await repo.get_by_address(address)
            if existing:
                wallet = existing
            else:
                wallet = await repo.create(
                    address=address,
                    label=label,
                    added_by_chat_id=chat_id,
                )

            for chain_key in chain_keys:
                chain = await repo.get_chain_by_key(chain_key)
                if chain and chain.enabled:
                    await repo.add_chain(wallet.id, chain.id)
                    added_chains.append(chain_key)

            await session.commit()

        # Subscribe
        if self._wallet_manager and added_chains:
            await self._wallet_manager.add_wallet(address, added_chains)

        return {"success": True, "wallet_id": wallet.id, "added_chains": added_chains}

    async def remove_wallet(self, address: str) -> None:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if wallet:
                await repo.update(wallet, enabled=False)
                await session.commit()
        if self._wallet_manager:
            await self._wallet_manager.remove_wallet(address)

    async def pause_wallet(self, address: str) -> None:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if wallet:
                await repo.update(wallet, enabled=False)
                await session.commit()

    async def resume_wallet(self, address: str) -> None:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if wallet:
                await repo.update(wallet, enabled=True)
                await session.commit()
        if self._wallet_manager:
            chains = await self._get_wallet_chain_keys(address)
            if chains:
                await self._wallet_manager.add_wallet(address, chains)

    async def _get_wallet_chain_keys(self, address: str) -> list[str]:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.wallet_repo import WalletRepository
            repo = WalletRepository(session)
            wallet = await repo.get_by_address(address)
            if not wallet:
                return []
            return [wc.chain.chain_key for wc in wallet.chains if wc.enabled]

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
                    "label": w.label or w.address[:12],
                    "chains": chains,
                    "enabled": w.enabled,
                    "score": w.smart_money_score,
                    "flags": w.risk_flags or [],
                })
            return result

    async def count_tracked_wallets(self) -> int:
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import func
                result = await session.execute(
                    select(func.count()).where(Wallet.enabled == True)
                )
                return result.scalar() or 0
        except Exception:
            return 0

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
            chains = [wc.chain.chain_key for wc in wallet.chains if wc.enabled]

            if not metrics:
                return {
                    "label": wallet.label or wallet.address[:12],
                    "address": wallet.address,
                    "score": wallet.smart_money_score or 0,
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_roi": 0,
                    "total_pnl": 0,
                    "avg_hold_seconds": 0,
                    "best_trade": 0,
                    "worst_trade": 0,
                    "chains": chains,
                    "flags": wallet.risk_flags or [],
                    "enabled": wallet.enabled,
                }

            from src.analytics.smart_money_score import compute_score
            breakdown = compute_score(metrics)
            return {
                "label": wallet.label or wallet.address[:12],
                "address": wallet.address,
                "score": metrics.smart_money_score or 0,
                "total_trades": metrics.total_trades,
                "win_rate": metrics.win_rate,
                "avg_roi": metrics.average_roi,
                "total_pnl": metrics.total_pnl_usd,
                "avg_hold_seconds": metrics.avg_holding_seconds,
                "best_trade": metrics.best_trade_roi,
                "worst_trade": metrics.worst_trade_roi,
                "chains": chains,
                "score_breakdown": breakdown.to_dict() if breakdown else None,
                "flags": wallet.risk_flags or [],
                "enabled": wallet.enabled,
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
            return [
                {
                    "token_symbol": "???",
                    "chain": "???",
                    "entry": p.average_entry_usd or 0,
                    "current": p.current_price_usd or 0,
                    "invested": p.total_invested_usd,
                    "roi": p.roi_percent,
                }
                for p in positions
            ]

    async def get_ranking(
        self,
        chain_key: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        async with AsyncSessionLocal() as session:
            return await get_wallet_ranking(session, chain_key=chain_key, limit=limit, offset=offset)

    async def get_top_trades(self) -> list[dict]:
        async with AsyncSessionLocal() as session:
            from src.database.repositories.trade_repo import TradeRepository
            repo = TradeRepository(session)
            trades = await repo.get_top_by_roi(min_roi=50, min_value_usd=100, limit=20)
            return [
                {
                    "roi": t.roi_percent or 0,
                    "wallet": "Unknown",
                    "token": t.token_symbol or "???",
                    "invested": t.value_usd or 0,
                    "value": (t.value_usd or 0) * (1 + (t.roi_percent or 0) / 100),
                }
                for t in trades
            ]

    async def get_consensus_tokens(self) -> list[dict]:
        try:
            keys = await self._redis.keys("consensus:*")
            tokens = []
            for key in keys[:20]:
                data = await self._redis.get(key)
                if data:
                    try:
                        tokens.append(json.loads(data))
                    except Exception:
                        pass
            return sorted(tokens, key=lambda x: x.get("wallet_count", 0), reverse=True)[:10]
        except Exception:
            return []

    async def run_backtest(self, address: str, period: str) -> Optional[dict]:
        from src.backtesting.engine import BacktestEngine
        engine = BacktestEngine()
        return await engine.run(address, period)

    async def health_check(self) -> dict[str, bool]:
        if self._wallet_manager:
            return await self._wallet_manager.health_check()
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
            "min_score": 70,
            "min_trade_usd": 500,
            "min_liquidity": 50000,
            "alerts_enabled": True,
            "environment": settings.environment,
        }

    async def set_user_setting(self, chat_id: int, key: str, value) -> None:
        raw = await self._redis.get(_user_settings_key(chat_id))
        data = json.loads(raw) if raw else {}
        data[key] = value
        await self._redis.setex(_user_settings_key(chat_id), 86400 * 90, json.dumps(data))

    async def get_trade_history(
        self,
        wallet_address: str,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        try:
            async with AsyncSessionLocal() as session:
                from src.database.repositories.wallet_repo import WalletRepository
                from src.database.repositories.trade_repo import TradeRepository
                repo = WalletRepository(session)
                wallet = await repo.get_by_address(wallet_address)
                if not wallet:
                    return []
                trade_repo = TradeRepository(session)
                trades = await trade_repo.get_by_wallet(wallet.id, limit=limit, offset=offset)
                return [
                    {
                        "side": t.side.value if t.side else "BUY",
                        "token_symbol": t.token_symbol or "???",
                        "chain": getattr(t, "chain_key", ""),
                        "roi_percent": t.roi_percent,
                        "value_usd": t.value_usd or 0,
                        "timestamp": t.created_at,
                    }
                    for t in trades
                ]
        except Exception:
            return []

    async def count_trades(self, wallet_address: str) -> int:
        try:
            async with AsyncSessionLocal() as session:
                from src.database.repositories.wallet_repo import WalletRepository
                from sqlalchemy import func
                repo = WalletRepository(session)
                wallet = await repo.get_by_address(wallet_address)
                if not wallet:
                    return 0
                result = await session.execute(
                    select(func.count(Trade.id)).where(Trade.wallet_id == wallet.id)
                )
                return result.scalar() or 0
        except Exception:
            return 0

    async def _get_chain_activity_stats(self) -> dict:
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import func
                result = await session.execute(
                    select(Trade.chain_key, func.count(Trade.id), func.sum(Trade.value_usd))
                    .group_by(Trade.chain_key)
                    .order_by(func.count(Trade.id).desc())
                    .limit(20)
                )
                rows = result.all()
                return {
                    row[0] or "unknown": {
                        "tx_count": row[1] or 0,
                        "volume_usd": float(row[2] or 0),
                    }
                    for row in rows
                }
        except Exception:
            return {}

    def set_wallet_manager(self, wm) -> None:
        self._wallet_manager = wm
