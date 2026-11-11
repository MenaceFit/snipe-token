"""Menu handlers for the Telegram bot FSM.

Each function handles a specific menu state or callback action.
State is stored in Redis under tg:state:{chat_id}.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.telegram.alerts import (
    format_ranking,
    format_wallet_stats,
    format_number,
)
from src.telegram.keyboards import (
    analytics_keyboard,
    back_keyboard,
    cancel_keyboard,
    chain_selection_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    ranking_keyboard,
    settings_keyboard,
    wallet_detail_keyboard,
    wallets_list_keyboard,
)

if TYPE_CHECKING:
    from src.telegram.bot import SnipeBot

logger = logging.getLogger(__name__)

# ─── State constants ───────────────────────────
STATE_IDLE = "idle"
STATE_AWAITING_ADDRESS = "awaiting_address"
STATE_AWAITING_LABEL = "awaiting_label"
STATE_AWAITING_MIN_TRADE = "awaiting_min_trade"
STATE_AWAITING_MIN_SCORE = "awaiting_min_score"

# ─── Redis key helpers ─────────────────────────
def _state_key(chat_id: int) -> str:
    return f"tg:state:{chat_id}"

def _data_key(chat_id: int) -> str:
    return f"tg:data:{chat_id}"

_STATE_TTL = 1800  # 30 minutes


# ─── State management ──────────────────────────

async def get_state(bot: "SnipeBot", chat_id: int) -> str:
    val = await bot._redis.get(_state_key(chat_id))
    return val.decode() if val else STATE_IDLE


async def set_state(bot: "SnipeBot", chat_id: int, state: str, data: dict | None = None) -> None:
    await bot._redis.setex(_state_key(chat_id), _STATE_TTL, state)
    if data is not None:
        await bot._redis.setex(_data_key(chat_id), _STATE_TTL, json.dumps(data))


async def get_data(bot: "SnipeBot", chat_id: int) -> dict:
    val = await bot._redis.get(_data_key(chat_id))
    if val:
        try:
            return json.loads(val)
        except Exception:
            pass
    return {}


async def clear_state(bot: "SnipeBot", chat_id: int) -> None:
    await bot._redis.delete(_state_key(chat_id))
    await bot._redis.delete(_data_key(chat_id))


# ─── Message router ────────────────────────────

async def handle_text_message(
    bot: "SnipeBot",
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Route plain text messages based on current state."""
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    state = await get_state(bot, chat_id)

    if state == STATE_AWAITING_ADDRESS:
        await _handle_address_input(bot, update, text)

    elif state == STATE_AWAITING_LABEL:
        await _handle_label_input(bot, update, text)

    elif state == STATE_AWAITING_MIN_TRADE:
        await _handle_min_trade_input(bot, update, text)

    elif state == STATE_AWAITING_MIN_SCORE:
        await _handle_min_score_input(bot, update, text)

    else:
        # Default: treat as address if it looks like one
        if text.startswith("0x") and len(text) >= 40:
            await set_state(bot, chat_id, STATE_AWAITING_ADDRESS)
            await _handle_address_input(bot, update, text)
        else:
            await show_main_menu(bot, update)


# ─── Address input flow ────────────────────────

async def _handle_address_input(
    bot: "SnipeBot",
    update: Update,
    address: str,
) -> None:
    chat_id = update.effective_chat.id

    # Validate EVM address format
    if not (address.startswith("0x") and len(address) == 42):
        await update.message.reply_html(
            "❌ <b>Adresse invalide.</b>\n\n"
            "Une adresse EVM doit commencer par <code>0x</code> et faire 42 caractères.\n"
            "Exemple: <code>0x1234567890123456789012345678901234567890</code>",
            reply_markup=cancel_keyboard(),
        )
        return

    msg = await update.message.reply_html(
        f"🔍 <b>Détection des blockchains actives...</b>\n\n"
        f"<code>{address}</code>\n\n"
        f"<i>Vérification sur {len(_get_active_chain_map())} blockchains...</i>"
    )

    try:
        from src.chains.chain_detector import detect_active_chains
        active_chains = await detect_active_chains(address, timeout=4.0)
    except Exception as exc:
        logger.error("Chain detection error: %s", exc)
        active_chains = []

    if not active_chains:
        await msg.edit_text(
            "⚠️ <b>Aucune activité détectée.</b>\n\n"
            f"<code>{address}</code>\n\n"
            "Cette adresse n'a aucune transaction sur les blockchains supportées.\n"
            "Vérifie que l'adresse est correcte.",
            parse_mode=ParseMode.HTML,
            reply_markup=cancel_keyboard(),
        )
        await clear_state(bot, chat_id)
        return

    chains_str = " · ".join(f"<b>{c.upper()}</b>" for c in active_chains[:8])
    if len(active_chains) > 8:
        chains_str += f" +{len(active_chains)-8} autres"

    await msg.edit_text(
        f"✅ <b>Activité détectée sur {len(active_chains)} blockchain(s)</b>\n\n"
        f"<code>{address}</code>\n\n"
        f"⛓️ {chains_str}\n\n"
        f"Sélectionne les blockchains à tracker, ou confirme tout:",
        parse_mode=ParseMode.HTML,
        reply_markup=chain_selection_keyboard(active_chains, address=address),
    )
    await set_state(bot, chat_id, STATE_AWAITING_LABEL, {
        "address": address,
        "detected_chains": active_chains,
        "selected_chains": active_chains,
    })


async def _handle_label_input(
    bot: "SnipeBot",
    update: Update,
    label: str,
) -> None:
    chat_id = update.effective_chat.id
    data = await get_data(bot, chat_id)
    address = data.get("address")
    chains = data.get("selected_chains", [])

    if not address:
        await clear_state(bot, chat_id)
        await show_main_menu(bot, update)
        return

    await update.message.reply_text("⏳ Ajout du wallet...")
    result = await bot.add_wallet_multi_chain(
        address=address,
        chain_keys=chains,
        label=label if label.lower() != "skip" else None,
        chat_id=chat_id,
    )

    await clear_state(bot, chat_id)

    if result["success"]:
        chains_str = ", ".join(result.get("added_chains", chains))
        await update.message.reply_html(
            f"✅ <b>Wallet ajouté !</b>\n\n"
            f"👤 Label: <b>{label if label.lower() != 'skip' else 'Aucun'}</b>\n"
            f"📍 <code>{address}</code>\n"
            f"⛓️ Chains: <b>{chains_str}</b>\n\n"
            f"Tu recevras les alertes en temps réel.",
            reply_markup=wallet_detail_keyboard(address),
        )
    else:
        await update.message.reply_html(
            f"❌ Erreur: {result.get('error', 'Erreur inconnue')}",
            reply_markup=main_menu_keyboard(),
        )


async def _handle_min_trade_input(
    bot: "SnipeBot",
    update: Update,
    text: str,
) -> None:
    chat_id = update.effective_chat.id
    try:
        value = float(text.replace("$", "").replace(",", ""))
        if value < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_html(
            "❌ Valeur invalide. Entre un montant en USD (ex: <b>500</b>)",
            reply_markup=cancel_keyboard(),
        )
        return

    await bot.set_user_setting(chat_id, "min_trade_usd", value)
    await clear_state(bot, chat_id)
    cfg = await bot.get_settings()
    await update.message.reply_html(
        f"✅ Montant minimum mis à jour: <b>${value:.0f}</b>",
        reply_markup=settings_keyboard(
            min_trade_usd=value,
            min_score=cfg.get("min_score", 70),
        ),
    )


async def _handle_min_score_input(
    bot: "SnipeBot",
    update: Update,
    text: str,
) -> None:
    chat_id = update.effective_chat.id
    try:
        value = int(text.strip())
        if not 0 <= value <= 100:
            raise ValueError
    except ValueError:
        await update.message.reply_html(
            "❌ Valeur invalide. Entre un score entre <b>0 et 100</b>",
            reply_markup=cancel_keyboard(),
        )
        return

    await bot.set_user_setting(chat_id, "min_score", value)
    await clear_state(bot, chat_id)
    cfg = await bot.get_settings()
    await update.message.reply_html(
        f"✅ Score minimum mis à jour: <b>{value}/100</b>",
        reply_markup=settings_keyboard(
            min_trade_usd=cfg.get("min_trade_usd", 500),
            min_score=value,
        ),
    )


# ─── Menu shows ────────────────────────────────

async def show_main_menu(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    total = await bot.count_tracked_wallets()
    text = (
        "🔍 <b>Snipe Token — Insider Detector</b>\n\n"
        f"👛 Wallets trackés: <b>{total}</b>\n"
        "⛓️ Blockchains: <b>40+</b> (all DexScreener)\n\n"
        "<i>Détecte les insiders et smart money en temps réel.</i>"
    )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard()
        )
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=main_menu_keyboard())


async def show_wallets_menu(
    bot: "SnipeBot",
    update: Update,
    page: int = 0,
    edit: bool = False,
) -> None:
    wallets = await bot.list_wallets()
    if not wallets:
        text = (
            "👛 <b>Aucun wallet tracké</b>\n\n"
            "Clique sur ➕ Tracker pour ajouter un wallet.\n"
            "Tu peux aussi simplement coller une adresse ici."
        )
        kb = main_menu_keyboard()
    else:
        text = f"👛 <b>Mes Wallets</b> ({len(wallets)} total)\n\nClique sur un wallet pour voir les détails:"
        kb = wallets_list_keyboard(wallets, page=page)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


async def show_add_wallet_prompt(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    chat_id = update.effective_chat.id
    await set_state(bot, chat_id, STATE_AWAITING_ADDRESS)
    text = (
        "➕ <b>Tracker un wallet</b>\n\n"
        "Envoie l'adresse EVM que tu veux tracker.\n"
        "Le bot détectera automatiquement les blockchains actives.\n\n"
        "<i>Exemple: <code>0x1234...abcd</code></i>"
    )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=cancel_keyboard()
        )
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=cancel_keyboard())


async def show_ranking(
    bot: "SnipeBot",
    update: Update,
    chain_key: str = "all",
    page: int = 0,
    edit: bool = False,
) -> None:
    ranking = await bot.get_ranking(
        chain_key=chain_key if chain_key != "all" else None,
        limit=10,
        offset=page * 10,
    )
    text = format_ranking(ranking, chain_filter=chain_key, page=page)
    kb = ranking_keyboard(selected_chain=chain_key, page=page)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


async def show_consensus(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    consensus = await bot.get_consensus_tokens()
    if not consensus:
        text = "🔥 <b>Consensus</b>\n\nAucun consensus détecté récemment."
    else:
        lines = ["🔥 <b>TOKENS EN CONSENSUS</b>\n", "<i>Plusieurs wallets trackés ont acheté ces tokens:</i>\n"]
        for i, c in enumerate(consensus[:10], 1):
            token = c.get("token_symbol", "???")
            chain = c.get("chain", "?")
            count = c.get("wallet_count", 0)
            total = c.get("total_usd", 0)
            lines.append(
                f"{i}. <b>{token}</b> ({chain.upper()}) — {count} wallets · ${format_number(total)}"
            )
        text = "\n".join(lines)

    kb = back_keyboard("menu:main")
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


async def show_analytics(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    text = "📊 <b>Analytics</b>\n\nChoisissez une vue:"
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=analytics_keyboard()
        )
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=analytics_keyboard())


async def show_settings(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    cfg = await bot.get_settings()
    text = (
        "⚙️ <b>Paramètres</b>\n\n"
        f"Mode copy trading: <b>{cfg.get('copy_mode', 'paper')}</b>\n"
        f"Environnement: <b>{cfg.get('environment', 'development')}</b>"
    )
    kb = settings_keyboard(
        alerts_enabled=cfg.get("alerts_enabled", True),
        min_trade_usd=cfg.get("min_trade_usd", 500),
        min_score=cfg.get("min_score", 70),
    )
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


async def show_wallet_detail(
    bot: "SnipeBot",
    update: Update,
    address: str,
    edit: bool = False,
) -> None:
    data = await bot.get_wallet_data(address)
    if not data:
        text = f"❌ Wallet <code>{address[:20]}...</code> non trouvé."
        kb = back_keyboard("menu:wallets")
    else:
        text = format_wallet_stats(**data)
        kb = wallet_detail_keyboard(address, is_paused=not data.get("enabled", True))

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


async def show_help(
    bot: "SnipeBot",
    update: Update,
    edit: bool = False,
) -> None:
    text = (
        "❓ <b>Aide — Snipe Token</b>\n\n"
        "<b>Comment tracker un wallet :</b>\n"
        "1️⃣ Clique sur ➕ Tracker\n"
        "2️⃣ Colle l'adresse EVM\n"
        "3️⃣ Le bot détecte les chains actives\n"
        "4️⃣ Tu reçois les alertes BUY/SELL\n\n"
        "<b>Commandes :</b>\n"
        "/start — Menu principal\n"
        "/track &lt;adresse&gt; — Tracker direct\n"
        "/wallets — Mes wallets\n"
        "/ranking — Classement\n"
        "/health — État du système\n"
        "/emergency — Stop d'urgence\n\n"
        "<b>Alertes :</b>\n"
        "🟢 BUY — Achat détecté\n"
        "🔴 SELL — Vente détectée\n"
        "🚨 CONSENSUS — Plusieurs wallets ont acheté\n\n"
        "<b>Smart Money Score :</b>\n"
        "Score de 0 à 100 basé sur le win rate,\n"
        "ROI moyen, régularité et gestion du risque."
    )
    kb = back_keyboard("menu:main")
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        msg = update.message or (update.callback_query and update.callback_query.message)
        if msg:
            await msg.reply_html(text, reply_markup=kb)


# ─── Chain selection toggle ────────────────────

async def handle_chain_toggle(
    bot: "SnipeBot",
    update: Update,
    address: str,
    chain_key: str,
) -> None:
    """Toggle a chain in the pending selection."""
    chat_id = update.effective_chat.id
    data = await get_data(bot, chat_id)
    detected = data.get("detected_chains", [])
    selected = set(data.get("selected_chains", detected))

    if chain_key in selected:
        selected.discard(chain_key)
    else:
        selected.add(chain_key)

    data["selected_chains"] = list(selected)
    await set_state(bot, chat_id, STATE_AWAITING_LABEL, data)

    if update.callback_query:
        await update.callback_query.edit_message_reply_markup(
            reply_markup=chain_selection_keyboard(detected, list(selected), address=address)
        )


async def handle_chain_confirm(
    bot: "SnipeBot",
    update: Update,
    address: str,
    chains: list[str],
) -> None:
    """User confirmed chain selection — ask for label."""
    chat_id = update.effective_chat.id
    if not chains:
        await update.callback_query.answer("❌ Sélectionne au moins une chain.", show_alert=True)
        return

    data = await get_data(bot, chat_id)
    data["selected_chains"] = chains
    await set_state(bot, chat_id, STATE_AWAITING_LABEL, data)

    chains_str = " · ".join(c.upper() for c in chains[:6])
    await update.callback_query.edit_message_text(
        f"✅ <b>{len(chains)} chain(s) sélectionnée(s):</b> {chains_str}\n\n"
        f"📍 <code>{address}</code>\n\n"
        f"Donne un label à ce wallet (ou envoie <b>skip</b> pour ignorer) :",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_keyboard(),
    )


# ─── Helper ────────────────────────────────────

def _get_active_chain_map() -> dict:
    from src.chains.chain_detector import CHAIN_RPC_MAP
    return CHAIN_RPC_MAP
