"""Telegram inline keyboard builders."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data="menu:stats"),
            InlineKeyboardButton("📈 Positions", callback_data="menu:positions"),
        ],
        [
            InlineKeyboardButton("💰 Trades", callback_data="menu:trades"),
            InlineKeyboardButton("🏆 Ranking", callback_data="menu:ranking"),
        ],
        [
            InlineKeyboardButton("⛓️ Chains", callback_data="menu:chains"),
            InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
        ],
    ])


def chain_filter_keyboard(selected: str = "") -> InlineKeyboardMarkup:
    chains = [
        ("⛓️ All", "all"),
        ("◆ Base", "base"),
        ("Ξ ETH", "ethereum"),
        ("◎ Solana", "solana"),
        ("◆ Arbitrum", "arbitrum"),
        ("🟡 BNB", "bsc"),
    ]
    buttons = []
    row = []
    for label, key in chains:
        prefix = "✓ " if key == selected else ""
        row.append(InlineKeyboardButton(f"{prefix}{label}", callback_data=f"chain:{key}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


def trade_alert_keyboard(
    tx_hash: str,
    token_address: str,
    wallet_address: str,
    chain_key: str,
    explorer_url: str = "",
) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🔗 TX", url=f"{explorer_url}/tx/{tx_hash}" if explorer_url else f"https://etherscan.io/tx/{tx_hash}"),
            InlineKeyboardButton("🪙 Token", callback_data=f"token:{chain_key}:{token_address}"),
        ],
        [
            InlineKeyboardButton("👤 Wallet", callback_data=f"wallet:{wallet_address}"),
            InlineKeyboardButton("📋 Copy Trade", callback_data=f"copy:{chain_key}:{token_address}:{wallet_address}"),
        ],
        [
            InlineKeyboardButton("🚫 Ignore Token", callback_data=f"ignore:{chain_key}:{token_address}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


def copy_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Paper Mode", callback_data="copy_mode:paper"),
            InlineKeyboardButton("🔴 Live Mode", callback_data="copy_mode:live"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="copy_mode:cancel")],
    ])


def wallet_detail_keyboard(wallet_address: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data=f"wallet_stats:{wallet_address}"),
            InlineKeyboardButton("📈 Positions", callback_data=f"wallet_pos:{wallet_address}"),
        ],
        [
            InlineKeyboardButton("💰 Trades", callback_data=f"wallet_trades:{wallet_address}"),
            InlineKeyboardButton("📋 Backtest", callback_data=f"backtest:{wallet_address}:30d"),
        ],
        [
            InlineKeyboardButton("⏸️ Pause", callback_data=f"pause_wallet:{wallet_address}"),
            InlineKeyboardButton("🗑️ Remove", callback_data=f"remove_wallet:{wallet_address}"),
        ],
    ])


def confirm_keyboard(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data=f"confirm:{action}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
        ]
    ])
