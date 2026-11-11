"""Telegram inline keyboard builders — full multi-menu system."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ───────────────────────────────────────────────
# MAIN MENU
# ───────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👛 Mes Wallets", callback_data="menu:wallets"),
            InlineKeyboardButton("➕ Tracker", callback_data="menu:add_wallet"),
        ],
        [
            InlineKeyboardButton("🏆 Classement", callback_data="menu:ranking"),
            InlineKeyboardButton("🔥 Consensus", callback_data="menu:consensus"),
        ],
        [
            InlineKeyboardButton("📊 Analytics", callback_data="menu:analytics"),
            InlineKeyboardButton("⚙️ Paramètres", callback_data="menu:settings"),
        ],
        [
            InlineKeyboardButton("❓ Aide", callback_data="menu:help"),
        ],
    ])


# ───────────────────────────────────────────────
# WALLET MANAGEMENT
# ───────────────────────────────────────────────

def wallets_list_keyboard(
    wallets: list[dict],
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """Paginated list of wallets with per-wallet action button."""
    total = len(wallets)
    start = page * page_size
    end = start + page_size
    page_wallets = wallets[start:end]

    buttons = []
    for w in page_wallets:
        label = w.get("label") or w.get("address", "?")[:12]
        score = w.get("score")
        score_str = f" • {score:.0f}pts" if score else ""
        status_icon = "🟢" if w.get("enabled", True) else "⏸"
        buttons.append([
            InlineKeyboardButton(
                f"{status_icon} {label}{score_str}",
                callback_data=f"wallet:detail:{w['address']}",
            )
        ])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Préc.", callback_data=f"wallets:page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Suiv. ▶️", callback_data=f"wallets:page:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("➕ Ajouter", callback_data="menu:add_wallet"),
        InlineKeyboardButton("🏠 Menu", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(buttons)


def wallet_detail_keyboard(wallet_address: str, is_paused: bool = False) -> InlineKeyboardMarkup:
    pause_label = "▶️ Reprendre" if is_paused else "⏸ Pause"
    pause_data = f"wallet:resume:{wallet_address}" if is_paused else f"wallet:pause:{wallet_address}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Stats", callback_data=f"wallet:stats:{wallet_address}"),
            InlineKeyboardButton("📈 Positions", callback_data=f"wallet:positions:{wallet_address}"),
        ],
        [
            InlineKeyboardButton("💰 Trades", callback_data=f"wallet:trades:{wallet_address}"),
            InlineKeyboardButton("🔬 Backtest", callback_data=f"wallet:backtest:{wallet_address}:30d"),
        ],
        [
            InlineKeyboardButton(pause_label, callback_data=pause_data),
            InlineKeyboardButton("🗑️ Supprimer", callback_data=f"wallet:remove_confirm:{wallet_address}"),
        ],
        [
            InlineKeyboardButton("◀️ Retour", callback_data="menu:wallets"),
        ],
    ])


def chain_selection_keyboard(
    detected_chains: list[str],
    selected_chains: list[str] | None = None,
    address: str = "",
) -> InlineKeyboardMarkup:
    """Let user pick which chains to track (after auto-detection)."""
    selected = set(selected_chains or detected_chains)
    _CHAIN_LABELS = {
        "ethereum": "Ξ ETH",  "bsc": "🟡 BNB",   "polygon": "🟣 POL",
        "arbitrum": "🔵 ARB", "optimism": "🔴 OP", "base": "🔵 BASE",
        "avalanche": "🔺 AVAX","fantom": "👻 FTM", "cronos": "🔷 CRO",
        "zksync": "⚡ zkSync","linea": "🟢 Linea", "scroll": "📜 Scroll",
        "blast": "💥 Blast",  "mantle": "🌀 MNT",  "mode": "🟤 Mode",
        "celo": "🌿 Celo",   "gnosis": "💙 GNO",   "sonic": "🎵 Sonic",
        "berachain": "🐻 Bera","core": "🔴 Core",  "sei": "🌊 Sei",
        "manta": "🐙 Manta",  "taiko": "⚔️ Taiko", "fraxtal": "⚪ Frax",
        "klaytn": "🔶 Klay",  "moonbeam": "🌙 GLMR","kava": "🌋 Kava",
        "aurora": "🌌 Aurora","metis": "⚡ Metis",  "fuse": "⚡ Fuse",
        "pulsechain": "💜 PLS","worldchain": "🌍 World",
    }

    buttons = []
    row = []
    for chain in detected_chains:
        label = _CHAIN_LABELS.get(chain, chain.upper())
        is_sel = chain in selected
        prefix = "✅ " if is_sel else "⬜ "
        row.append(InlineKeyboardButton(
            f"{prefix}{label}",
            callback_data=f"chain_sel:{address}:{chain}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            f"✅ Confirmer ({len(selected)} chain{'s' if len(selected) != 1 else ''})",
            callback_data=f"chain_sel_confirm:{address}:{','.join(sorted(selected))}",
        ),
    ])
    buttons.append([InlineKeyboardButton("❌ Annuler", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


# ───────────────────────────────────────────────
# RANKINGS & ANALYTICS
# ───────────────────────────────────────────────

def ranking_keyboard(selected_chain: str = "all", page: int = 0) -> InlineKeyboardMarkup:
    chains = [
        ("🌍 Tous", "all"),
        ("Ξ ETH", "ethereum"),
        ("🟡 BNB", "bsc"),
        ("🔵 BASE", "base"),
        ("🔵 ARB", "arbitrum"),
        ("🔴 OP", "optimism"),
        ("🟣 POL", "polygon"),
    ]
    buttons = []
    row = []
    for label, key in chains:
        prefix = "✓ " if key == selected_chain else ""
        row.append(InlineKeyboardButton(f"{prefix}{label}", callback_data=f"ranking:chain:{key}:{page}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"ranking:page:{page-1}:{selected_chain}"))
    nav.append(InlineKeyboardButton("🔄 Rafraîchir", callback_data=f"ranking:chain:{selected_chain}:{page}"))
    if True:  # always show next
        nav.append(InlineKeyboardButton("▶️", callback_data=f"ranking:page:{page+1}:{selected_chain}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💎 Top Trades", callback_data="analytics:top_trades"),
            InlineKeyboardButton("📈 Positions", callback_data="analytics:positions"),
        ],
        [
            InlineKeyboardButton("🔥 Consensus", callback_data="menu:consensus"),
            InlineKeyboardButton("🏆 Classement", callback_data="menu:ranking"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])


# ───────────────────────────────────────────────
# SETTINGS
# ───────────────────────────────────────────────

def settings_keyboard(
    alerts_enabled: bool = True,
    min_trade_usd: float = 500,
    min_score: int = 70,
) -> InlineKeyboardMarkup:
    alerts_label = "🔔 Alertes: ON" if alerts_enabled else "🔕 Alertes: OFF"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(alerts_label, callback_data="settings:toggle_alerts"),
        ],
        [
            InlineKeyboardButton(f"💵 Min trade: ${min_trade_usd:.0f}", callback_data="settings:set_min_trade"),
            InlineKeyboardButton(f"🏆 Min score: {min_score}", callback_data="settings:set_min_score"),
        ],
        [
            InlineKeyboardButton("🔗 Chains actives", callback_data="settings:chains"),
            InlineKeyboardButton("ℹ️ Infos bot", callback_data="settings:info"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])


# ───────────────────────────────────────────────
# TRADE ALERTS
# ───────────────────────────────────────────────

def trade_alert_keyboard(
    tx_hash: str,
    token_address: str,
    wallet_address: str,
    chain_key: str,
    explorer_url: str = "",
    dexscreener_slug: str = "",
) -> InlineKeyboardMarkup:
    explorer = explorer_url or "https://etherscan.io"
    buttons = [
        [
            InlineKeyboardButton("🔗 TX", url=f"{explorer}/tx/{tx_hash}"),
        ],
    ]
    if dexscreener_slug and token_address:
        buttons[0].append(
            InlineKeyboardButton(
                "📊 DexScreener",
                url=f"https://dexscreener.com/{dexscreener_slug}/{token_address}",
            )
        )
    buttons.append([
        InlineKeyboardButton("👤 Wallet", callback_data=f"wallet:detail:{wallet_address}"),
        InlineKeyboardButton("🚫 Ignorer", callback_data=f"ignore_token:{chain_key}:{token_address}"),
    ])
    return InlineKeyboardMarkup(buttons)


# ───────────────────────────────────────────────
# UTILITY
# ───────────────────────────────────────────────

def confirm_keyboard(action: str, label: str = "Confirmer") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ {label}", callback_data=f"confirm:{action}"),
            InlineKeyboardButton("❌ Annuler", callback_data="cancel"),
        ]
    ])


def back_keyboard(destination: str = "menu:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Retour", callback_data=destination)]
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Annuler", callback_data="menu:main")]
    ])


# Legacy aliases kept for compatibility
def chain_filter_keyboard(selected: str = "") -> InlineKeyboardMarkup:
    return ranking_keyboard(selected_chain=selected or "all")
