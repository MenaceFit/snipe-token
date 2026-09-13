"""Telegram command handlers."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

from src.telegram.alerts import format_ranking, format_wallet_stats
from src.telegram.keyboards import (
    chain_filter_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    wallet_detail_keyboard,
)

if TYPE_CHECKING:
    from src.telegram.bot import SnipeBot

logger = logging.getLogger(__name__)


def admin_only(func):
    """Decorator: restrict command to admin chat IDs."""
    async def wrapper(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user:
            return
        user_id = update.effective_user.id
        if self._admin_ids and user_id not in self._admin_ids:
            await update.message.reply_text("⛔ Unauthorized.")
            return
        return await func(self, update, ctx)
    return wrapper


class CommandHandlers:
    def __init__(self, bot: "SnipeBot") -> None:
        self._bot = bot

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "🔥 <b>Snipe-Token Bot</b>\n\n"
            "Multi-chain wallet intelligence & copy trading.\n\n"
            "Use /help for commands."
        )
        await update.message.reply_html(text, reply_markup=main_menu_keyboard())

    async def help_cmd(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "📋 <b>Commands</b>\n\n"
            "<b>Wallets:</b>\n"
            "/addwallet &lt;address&gt; &lt;chain&gt; [label]\n"
            "/removewallet &lt;address&gt;\n"
            "/listwallets\n"
            "/wallet &lt;address&gt;\n"
            "/pausewallet &lt;address&gt;\n"
            "/resumewallet &lt;address&gt;\n"
            "/renamewallet &lt;address&gt; &lt;label&gt;\n\n"
            "<b>Analytics:</b>\n"
            "/stats &lt;address&gt;\n"
            "/positions [address]\n"
            "/trades [address]\n"
            "/ranking\n"
            "/toptraders\n"
            "/toptrades\n"
            "/backtest &lt;address&gt; &lt;30d|7d&gt;\n\n"
            "<b>Copy Trading:</b>\n"
            "/paper &lt;address&gt; [amount]\n"
            "/live &lt;address&gt;\n"
            "/stopcopy &lt;address&gt;\n\n"
            "<b>Risk:</b>\n"
            "/blacklist &lt;token&gt;\n"
            "/whitelist &lt;token&gt;\n\n"
            "<b>System:</b>\n"
            "/health\n"
            "/emergency\n"
            "/settings\n"
        )
        await update.message.reply_html(text)

    async def add_wallet(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        args = ctx.args
        if not args or len(args) < 2:
            await update.message.reply_html(
                "Usage: /addwallet &lt;address&gt; &lt;chain&gt; [label]\n"
                "Example: /addwallet 0x123... base AlphaTrader"
            )
            return

        address = args[0]
        chain_key = args[1].lower()
        label = " ".join(args[2:]) if len(args) > 2 else None

        await update.message.reply_text("⏳ Adding wallet...")
        try:
            result = await self._bot.add_wallet(
                address=address,
                chain_key=chain_key,
                label=label,
                chat_id=update.effective_chat.id,
            )
            if result["success"]:
                await update.message.reply_html(
                    f"✅ <b>Wallet added!</b>\n\n"
                    f"Address: <code>{address}</code>\n"
                    f"Chain: <b>{chain_key}</b>\n"
                    f"Label: <b>{label or 'None'}</b>\n\n"
                    f"Now tracking on {chain_key}.",
                    reply_markup=wallet_detail_keyboard(address),
                )
            else:
                await update.message.reply_text(f"❌ {result.get('error', 'Unknown error')}")
        except Exception as exc:
            await update.message.reply_text(f"❌ Error: {exc}")

    async def remove_wallet(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("Usage: /removewallet <address>")
            return
        address = ctx.args[0]
        await update.message.reply_html(
            f"⚠️ Remove wallet <code>{address}</code>?",
            reply_markup=confirm_keyboard(f"remove_wallet:{address}"),
        )

    async def list_wallets(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        wallets = await self._bot.list_wallets()
        if not wallets:
            await update.message.reply_text("No wallets tracked yet. Use /addwallet.")
            return

        lines = ["📋 <b>Tracked Wallets</b>\n"]
        for w in wallets[:20]:
            status = "🟢" if w["enabled"] else "⛔"
            score = f" | Score: {w['score']:.0f}" if w.get("score") else ""
            chains = ", ".join(w.get("chains", []))
            lines.append(
                f"{status} <b>{w['label']}</b>\n"
                f"   <code>{w['address']}</code>\n"
                f"   ⛓️ {chains}{score}"
            )

        await update.message.reply_html("\n\n".join(lines))

    async def wallet_info(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args:
            await update.message.reply_text("Usage: /wallet <address>")
            return
        address = ctx.args[0]
        data = await self._bot.get_wallet_data(address)
        if not data:
            await update.message.reply_text("❌ Wallet not found.")
            return
        text = format_wallet_stats(**data)
        await update.message.reply_html(text, reply_markup=wallet_detail_keyboard(address))

    async def ranking(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chain = None
        if ctx.args:
            chain = ctx.args[0].lower()
        data = await self._bot.get_ranking(chain_key=chain)
        text = format_ranking(data)
        await update.message.reply_html(text, reply_markup=chain_filter_keyboard(chain or "all"))

    async def positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        address = ctx.args[0] if ctx.args else None
        pos_list = await self._bot.get_positions(wallet_address=address)
        if not pos_list:
            await update.message.reply_text("No open positions.")
            return
        lines = ["📈 <b>Open Positions</b>\n"]
        for p in pos_list[:10]:
            roi_str = f"{p['roi']:.1f}%" if p.get("roi") is not None else "N/A"
            lines.append(
                f"🪙 <b>{p['token_symbol']}</b> ({p['chain']})\n"
                f"   Entry: ${p['entry']:.6f} | Now: ${p['current']:.6f}\n"
                f"   PnL: <b>{roi_str}</b> | ${p['invested']:.0f} invested"
            )
        await update.message.reply_html("\n\n".join(lines))

    async def health(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        status = await self._bot.health_check()
        lines = ["🔧 <b>System Health</b>\n"]
        for chain, healthy in status.items():
            icon = "🟢" if healthy else "🔴"
            lines.append(f"{icon} {chain}")
        await update.message.reply_html("\n".join(lines))

    async def emergency_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._bot.emergency_stop()
        await update.message.reply_html(
            "🛑 <b>EMERGENCY STOP</b>\n\n"
            "Live copy trading: <b>DISABLED</b>\n"
            "Wallet tracking: <b>ACTIVE</b>\n"
            "Paper trading: <b>ACTIVE</b>"
        )

    async def backtest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not ctx.args or len(ctx.args) < 2:
            await update.message.reply_text("Usage: /backtest <address> <7d|30d|90d>")
            return
        address = ctx.args[0]
        period = ctx.args[1].lower()
        await update.message.reply_text("⏳ Running backtest...")
        result = await self._bot.run_backtest(address, period)
        if not result:
            await update.message.reply_text("❌ No data for backtest.")
            return
        text = (
            f"📊 <b>BACKTEST</b>\n\n"
            f"Wallet: <b>{result['label']}</b>\n"
            f"Period: <b>{period}</b>\n\n"
            f"Trades: <b>{result['trades']}</b>\n"
            f"Win rate: <b>{result['win_rate']:.1f}%</b>\n"
            f"Avg ROI: <b>{result['avg_roi']:.1f}%</b>\n"
            f"Total PnL: <b>${result['total_pnl']:,.0f}</b>\n"
            f"Max drawdown: <b>-{result['max_dd']:.1f}%</b>\n"
            f"Best trade: <b>+{result['best_roi']:.1f}%</b>\n"
            f"Worst trade: <b>{result['worst_roi']:.1f}%</b>\n"
            f"Profit factor: <b>{result['profit_factor']:.1f}</b>\n\n"
            f"🏆 Score: <b>{result['score']:.0f}/100</b>"
        )
        await update.message.reply_html(text)

    async def top_trades(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        trades = await self._bot.get_top_trades()
        if not trades:
            await update.message.reply_text("No top trades yet.")
            return
        lines = ["🔥 <b>TOP TRADES</b>\n"]
        for t in trades[:10]:
            lines.append(
                f"+{t['roi']:.0f}% — <b>{t['wallet']}</b> → {t['token']}\n"
                f"   ${t['invested']:.0f} → ${t['value']:.0f}"
            )
        await update.message.reply_html("\n\n".join(lines))

    async def settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cfg = await self._bot.get_settings()
        text = (
            f"⚙️ <b>Settings</b>\n\n"
            f"Copy mode: <b>{cfg.get('copy_mode', 'paper')}</b>\n"
            f"Copy %: <b>{cfg.get('copy_pct', 5)}%</b>\n"
            f"Max trade: <b>${cfg.get('max_trade', 100)}</b>\n"
            f"Min score threshold: <b>{cfg.get('min_score', 80)}</b>\n"
            f"Min investment: <b>${cfg.get('min_investment', 500)}</b>\n"
            f"Min liquidity: <b>${cfg.get('min_liquidity', 50000):,}</b>\n"
        )
        await update.message.reply_html(text)
