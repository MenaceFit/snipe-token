"""Alert message formatters for all trade and system events."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Utility formatters ────────────────────────────────────────────────────────

def format_number(n: float, prefix: str = "", suffix: str = "") -> str:
    if abs(n) >= 1_000_000:
        return f"{prefix}{n/1_000_000:.2f}M{suffix}"
    if abs(n) >= 1_000:
        return f"{prefix}{n/1_000:.1f}K{suffix}"
    if abs(n) >= 100:
        return f"{prefix}{n:.0f}{suffix}"
    if abs(n) >= 1:
        return f"{prefix}{n:.2f}{suffix}"
    return f"{prefix}{n:.6f}{suffix}"


def format_usd(n: float) -> str:
    sign = "+" if n > 0 else ""
    return f"{sign}${format_number(n)}"


def format_pct(n: float) -> str:
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.1f}%"


def format_hold_time(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


def format_progress_bar(value: float, max_val: float = 100, width: int = 10) -> str:
    pct = max(0.0, min(1.0, value / max_val if max_val else 0))
    filled = round(pct * width)
    return "▓" * filled + "░" * (width - filled)


def format_score_display(score: float) -> str:
    bar = format_progress_bar(score, 100, 8)
    if score >= 85:
        tier = "🔥"
    elif score >= 70:
        tier = "⭐"
    elif score >= 50:
        tier = "✅"
    else:
        tier = "❓"
    return f"{bar} <b>{score:.0f}/100</b> {tier}"


def _usd_scale_emoji(usd: float) -> str:
    """Return whale-size emoji based on trade size."""
    if usd >= 100_000:
        return "🐋"
    if usd >= 25_000:
        return "🦈"
    if usd >= 5_000:
        return "🐬"
    if usd >= 1_000:
        return "🐟"
    return "🦐"


def _roi_emoji(roi: float) -> str:
    if roi >= 500:
        return "🚀🚀🚀"
    if roi >= 200:
        return "🚀🚀"
    if roi >= 100:
        return "🚀"
    if roi >= 50:
        return "📈📈"
    if roi >= 10:
        return "📈"
    if roi > 0:
        return "🟢"
    if roi > -20:
        return "🔴"
    return "💀"


# ─── Trade alerts ──────────────────────────────────────────────────────────────

def format_buy_alert(
    wallet_label: str,
    chain_name: str,
    token_symbol: str,
    token_address: str,
    price_usd: Optional[float],
    invested_usd: Optional[float],
    tx_hash: str,
    latency_ms: int,
    is_new_position: bool = True,
    existing_position_pnl: Optional[float] = None,
    group_emoji: str = "🔥",
    smart_money_score: Optional[float] = None,
) -> str:
    score_line = ""
    if smart_money_score is not None:
        score_line = f"\n🏆 Score: {format_score_display(smart_money_score)}"

    price_str = (
        f"${price_usd:.8f}" if price_usd and price_usd < 0.001 else
        f"${price_usd:.6f}" if price_usd and price_usd < 0.01 else
        f"${price_usd:.4f}" if price_usd else "—"
    )

    size_emoji = _usd_scale_emoji(invested_usd or 0)
    position_label = "🆕 Nouvelle position" if is_new_position else "➕ Renforcement"

    parts = [
        f"🟢 <b>ACHAT</b> · <code>{chain_name.upper()}</code>",
        f"",
        f"👤 <b>{wallet_label}</b>{score_line}",
        f"━━━━━━━━━━━━━━",
        f"🪙 <b>${token_symbol}</b>  ·  {price_str}",
    ]

    if invested_usd is not None:
        parts.append(f"{size_emoji} Montant: <b>${invested_usd:,.0f}</b>")

    parts.append(f"📊 {position_label}")

    if not is_new_position and existing_position_pnl is not None:
        pnl_icon = "📈" if existing_position_pnl > 0 else "📉"
        parts.append(f"{pnl_icon} PnL position: <b>{format_pct(existing_position_pnl)}</b>")

    parts += [
        f"━━━━━━━━━━━━━━",
        f"⚡ Latence: <b>{latency_ms/1000:.2f}s</b>",
        f"🔗 <code>{tx_hash[:20]}…{tx_hash[-6:]}</code>",
    ]

    return "\n".join(parts)


def format_sell_alert(
    wallet_label: str,
    chain_name: str,
    token_symbol: str,
    pct_sold: float,
    proceeds_usd: Optional[float],
    realized_pnl: float,
    roi_percent: float,
    hold_time_seconds: int,
    tx_hash: str,
    remaining_pct: float,
    entry_price: Optional[float] = None,
    sell_price: Optional[float] = None,
    smart_money_score: Optional[float] = None,
) -> str:
    roi_sign = "+" if roi_percent > 0 else ""
    roi_em = _roi_emoji(roi_percent)

    score_line = ""
    if smart_money_score is not None:
        score_line = f"\n🏆 Score: {format_score_display(smart_money_score)}"

    size_emoji = _usd_scale_emoji(abs(proceeds_usd or 0))

    parts = [
        f"🔴 <b>VENTE</b> {pct_sold:.0f}% · <code>{chain_name.upper()}</code>",
        f"",
        f"👤 <b>{wallet_label}</b>{score_line}",
        f"━━━━━━━━━━━━━━",
        f"🪙 <b>${token_symbol}</b>",
    ]

    if proceeds_usd is not None:
        parts.append(f"{size_emoji} Reçu: <b>${proceeds_usd:,.0f}</b>")

    parts.append(
        f"{roi_em} ROI: <b>{roi_sign}{roi_percent:.1f}%</b>  ·  PnL: <b>{format_usd(realized_pnl)}</b>"
    )

    if entry_price and sell_price:
        ep = f"${entry_price:.6f}" if entry_price < 0.01 else f"${entry_price:.4f}"
        sp = f"${sell_price:.6f}" if sell_price < 0.01 else f"${sell_price:.4f}"
        bar = format_progress_bar(max(0.0, roi_percent), 200, 8)
        parts.append(f"📊 {ep} → {sp}  {bar}")

    parts += [
        f"⏱️ Tenu: <b>{format_hold_time(hold_time_seconds)}</b>  ·  Reste: <b>{remaining_pct:.0f}%</b>",
        f"━━━━━━━━━━━━━━",
        f"🔗 <code>{tx_hash[:20]}…{tx_hash[-6:]}</code>",
    ]

    return "\n".join(parts)


def format_position_update(
    wallet_label: str,
    token_symbol: str,
    entry_price: float,
    current_price: float,
    pnl_pct: float,
    invested_usd: float,
    current_value_usd: float,
    hold_time_seconds: int,
) -> str:
    pnl_em = _roi_emoji(pnl_pct)
    pct_sign = "+" if pnl_pct > 0 else ""
    bar = format_progress_bar(max(0.0, pnl_pct), 200, 10)

    ep = f"${entry_price:.8f}" if entry_price < 0.01 else f"${entry_price:.4f}"
    cp = f"${current_price:.8f}" if current_price < 0.01 else f"${current_price:.4f}"

    return "\n".join([
        f"📊 <b>POSITION UPDATE</b>",
        f"",
        f"👤 <b>{wallet_label}</b>  ·  🪙 <b>${token_symbol}</b>",
        f"",
        f"💰 {ep} → {cp}",
        f"{pnl_em} PnL: <b>{pct_sign}{pnl_pct:.1f}%</b>",
        f"<code>{bar}</code>",
        f"",
        f"💵 Investi: <b>${invested_usd:,.0f}</b>  ·  Valeur: <b>${current_value_usd:,.0f}</b>",
        f"⏱️ Tenu: <b>{format_hold_time(hold_time_seconds)}</b>",
    ])


# ─── Consensus & system ────────────────────────────────────────────────────────

def format_consensus_alert(
    token_symbol: str,
    token_address: str,
    chain_name: str,
    wallets: list[dict],
    total_usd: float,
    confidence: str,
) -> str:
    wallet_lines = []
    for w in wallets[:5]:
        name = w.get("label") or w.get("address", "?")[:10]
        val = w.get("value_usd", 0)
        score = w.get("score")
        score_str = f"  🏆{score:.0f}" if score else ""
        wallet_lines.append(f"  · <b>{name}</b>: ${val:,.0f}{score_str}")

    conf_emoji = "🔥🔥🔥" if confidence == "HIGH" else ("🔥🔥" if confidence == "MEDIUM" else "🔥")

    return "\n".join([
        f"🚨 <b>SMART MONEY CONSENSUS</b>",
        f"",
        f"🪙 <b>${token_symbol}</b>  ·  <code>{chain_name.upper()}</code>",
        f"",
        f"<b>{len(wallets)} wallets</b> ont acheté:",
        f"",
        *wallet_lines,
        f"",
        f"💰 Total: <b>${total_usd:,.0f}</b>  ·  {conf_emoji} <b>{confidence}</b>",
    ])


def format_paper_trade(
    wallet_label: str,
    token_symbol: str,
    token_address: str,
    chain_name: str,
    simulated_amount_usd: float,
    entry_price: Optional[float],
    copy_pct: float,
) -> str:
    ep = (
        f"${entry_price:.8f}" if entry_price and entry_price < 0.01 else
        f"${entry_price:.4f}" if entry_price else "N/A"
    )
    return "\n".join([
        f"📋 <b>PAPER TRADE</b>  <i>(simulation)</i>",
        f"",
        f"👤 Copie: <b>{wallet_label}</b>",
        f"🪙 <b>${token_symbol}</b>  ·  <code>{chain_name.upper()}</code>",
        f"",
        f"💵 Montant simulé: <b>${simulated_amount_usd:,.0f}</b>  ({copy_pct}%)",
        f"💰 Entrée: <b>{ep}</b>",
        f"",
        f"<i>Aucune transaction réelle.</i>",
    ])


def format_system_alert(chain: str, issue: str, status: str, details: str = "") -> str:
    return "\n".join([
        f"⚠️ <b>ALERTE SYSTÈME</b>",
        f"",
        f"⛓️ Chain: <b>{chain}</b>",
        f"🔴 Problème: <b>{issue}</b>",
        f"📊 Statut: <b>{status}</b>",
        *(["", details] if details else []),
    ])


def format_risk_blocked(token_symbol: str, reason: str, flags: list[str]) -> str:
    flag_lines = "\n".join(f"  ⚠️ {f}" for f in flags[:5])
    return "\n".join([
        f"🚫 <b>TRADE BLOQUÉ</b>",
        f"",
        f"Token: <b>${token_symbol}</b>",
        f"Raison: <b>{reason}</b>",
        f"",
        f"Flags détectés:",
        flag_lines,
        f"",
        f"<i>Aucune transaction exécutée.</i>",
    ])


# ─── Wallet stats ──────────────────────────────────────────────────────────────

def format_wallet_stats(
    label: str,
    address: str,
    score: float,
    total_trades: int,
    win_rate: float,
    avg_roi: float,
    total_pnl: float,
    avg_hold_seconds: Optional[int],
    best_trade: float,
    worst_trade: float,
    score_breakdown: Optional[dict] = None,
    flags: Optional[list[str]] = None,
    chains: Optional[list[str]] = None,
    enabled: bool = True,
    **_kwargs,
) -> str:
    score_bar = format_progress_bar(score, 100, 10)
    wr_bar = format_progress_bar(win_rate, 100, 8)
    pnl_em = "📈" if total_pnl >= 0 else "📉"
    status_icon = "🟢" if enabled else "⏸"

    chains_str = ""
    if chains:
        chains_str = f"\n⛓️ Chains: <b>{' · '.join(c.upper() for c in chains[:6])}</b>"
        if len(chains) > 6:
            chains_str += f" +{len(chains)-6}"

    breakdown_lines = ""
    if score_breakdown:
        parts = []
        for k, v in score_breakdown.items():
            parts.append(f"  · {k}: <b>{v:.0f}</b>")
        breakdown_lines = "\n📋 Détail score:\n" + "\n".join(parts)

    flag_lines = ""
    if flags:
        flag_lines = "\n🚩 Flags: " + " | ".join(flags[:3])

    return "\n".join(filter(None, [
        f"{status_icon} <b>{label}</b>",
        f"<code>{address}</code>",
        chains_str,
        f"",
        f"🏆 Score: {format_score_display(score)}",
        f"<code>{score_bar}</code>",
        breakdown_lines,
        f"",
        f"━━━━━━━━━━━━━━",
        f"📊 Trades: <b>{total_trades}</b>",
        f"✅ Win rate: <b>{win_rate:.1f}%</b>  <code>{wr_bar}</code>",
        f"📈 ROI moyen: <b>{format_pct(avg_roi)}</b>",
        f"{pnl_em} PnL total: <b>{format_usd(total_pnl)}</b>",
        f"⏱️ Durée moy.: <b>{format_hold_time(avg_hold_seconds or 0)}</b>",
        f"",
        f"🏅 Meilleur: <b>+{best_trade:.1f}%</b>  ·  Pire: <b>{worst_trade:.1f}%</b>",
        flag_lines,
    ]))


# ─── Ranking ───────────────────────────────────────────────────────────────────

def format_ranking(
    ranking: list[dict],
    chain_filter: str = "all",
    page: int = 0,
) -> str:
    chain_label = chain_filter.upper() if chain_filter != "all" else "Toutes les chains"
    offset = page * 10

    if not ranking:
        return f"🏆 <b>Classement</b> — {chain_label}\n\n<i>Aucun wallet classé.</i>"

    lines = [f"🏆 <b>CLASSEMENT SMART MONEY</b>", f"<i>{chain_label} · Page {page+1}</i>", ""]

    for i, w in enumerate(ranking, offset + 1):
        label = w.get("label") or w.get("address", "?")[:10]
        score = w.get("score", 0)
        win_rate = w.get("win_rate", 0)
        trades = w.get("total_trades", 0)
        pnl = w.get("total_pnl", 0)
        pnl_em = "📈" if pnl >= 0 else "📉"
        bar = format_progress_bar(score, 100, 6)

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(
            f"{medal} <b>{label}</b>  <code>{bar}</code> <b>{score:.0f}</b>\n"
            f"   ✅{win_rate:.0f}%  📊{trades}  {pnl_em}{format_usd(pnl)}"
        )

    return "\n".join(lines)


# ─── Portfolio ─────────────────────────────────────────────────────────────────

def format_portfolio_summary(wallets: list[dict]) -> str:
    if not wallets:
        return "💼 <b>Portfolio</b>\n\n<i>Aucun wallet tracké.</i>"

    total_pnl = sum(w.get("total_pnl", 0) for w in wallets)
    total_trades = sum(w.get("total_trades", 0) for w in wallets)
    avg_score = sum(w.get("score", 0) for w in wallets) / len(wallets) if wallets else 0

    pnl_em = "📈" if total_pnl >= 0 else "📉"
    score_bar = format_progress_bar(avg_score, 100, 8)

    lines = [
        f"💼 <b>PORTFOLIO</b>  ·  {len(wallets)} wallets",
        f"",
        f"🏆 Score moyen: <code>{score_bar}</code> <b>{avg_score:.0f}/100</b>",
        f"{pnl_em} PnL agrégé: <b>{format_usd(total_pnl)}</b>",
        f"📊 Trades totaux: <b>{total_trades}</b>",
        f"",
        f"━━━━━━━━━━━━━━",
    ]

    for w in sorted(wallets, key=lambda x: x.get("score", 0), reverse=True)[:8]:
        label = w.get("label") or w.get("address", "?")[:10]
        score = w.get("score", 0)
        pnl = w.get("total_pnl", 0)
        status = "🟢" if w.get("enabled", True) else "⏸"
        pnl_str = format_usd(pnl)
        lines.append(f"{status} <b>{label}</b>  🏆{score:.0f}  {pnl_str}")

    return "\n".join(lines)


# ─── Hotlist ───────────────────────────────────────────────────────────────────

def format_hotlist(tokens: list[dict]) -> str:
    if not tokens:
        return (
            "🔥 <b>HOTLIST</b>  ·  24h\n\n"
            "<i>Aucun token acheté en commun récemment.</i>"
        )

    lines = [
        f"🔥 <b>HOTLIST — Tokens actifs (24h)</b>",
        f"<i>Achetés par plusieurs wallets trackés</i>",
        f"",
    ]

    for i, t in enumerate(tokens[:12], 1):
        sym = t.get("token_symbol", "???")
        chain = t.get("chain", "?").upper()
        count = t.get("wallet_count", 0)
        total = t.get("total_usd", 0)
        size_em = _usd_scale_emoji(total)
        lines.append(
            f"{i}. <b>${sym}</b> <code>{chain}</code>  "
            f"{size_em} ${format_number(total)}  "
            f"👛×{count}"
        )

    return "\n".join(lines)


# ─── Trade history ─────────────────────────────────────────────────────────────

def format_trade_history(
    trades: list[dict],
    wallet_label: str,
    page: int = 0,
    total_pages: int = 1,
) -> str:
    if not trades:
        return f"📜 <b>Historique</b> — {wallet_label}\n\n<i>Aucun trade enregistré.</i>"

    lines = [
        f"📜 <b>HISTORIQUE</b>  ·  {wallet_label}",
        f"<i>Page {page+1}/{total_pages}</i>",
        f"",
    ]

    for t in trades:
        side = t.get("side", "BUY")
        sym = t.get("token_symbol", "???")
        chain = t.get("chain", "?").upper()
        roi = t.get("roi_percent")
        usd = t.get("value_usd", 0)
        ts = t.get("timestamp")

        side_em = "🟢" if side == "BUY" else "🔴"
        roi_str = f"  {_roi_emoji(roi)} <b>{roi:+.0f}%</b>" if roi is not None else ""
        time_str = ""
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts))
                time_str = f" · {dt.strftime('%d/%m %H:%M')}"
            except Exception:
                pass

        lines.append(
            f"{side_em} <b>${sym}</b> <code>{chain}</code>"
            f"  ${format_number(usd)}{roi_str}{time_str}"
        )

    return "\n".join(lines)


# ─── Chain activity ────────────────────────────────────────────────────────────

def format_chain_activity(stats: dict) -> str:
    if not stats:
        return "⛓️ <b>Activité par chain</b>\n\n<i>Aucune donnée.</i>"

    lines = ["⛓️ <b>ACTIVITÉ PAR BLOCKCHAIN</b>", ""]

    sorted_chains = sorted(stats.items(), key=lambda x: x[1].get("tx_count", 0), reverse=True)
    max_tx = max((v.get("tx_count", 0) for _, v in sorted_chains), default=1)

    for chain, data in sorted_chains[:15]:
        tx = data.get("tx_count", 0)
        vol = data.get("volume_usd", 0)
        bar = format_progress_bar(tx, max_tx, 6)
        lines.append(
            f"<code>{bar}</code> <b>{chain.upper()}</b>  "
            f"📊{tx}tx  💰${format_number(vol)}"
        )

    return "\n".join(lines)
