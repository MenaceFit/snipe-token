"""Alert message formatters for all trade and system events."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


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
    score_str = ""
    if smart_money_score is not None:
        score_emoji = "🔥" if smart_money_score >= 85 else ("⭐" if smart_money_score >= 70 else "")
        score_str = f" • Score <b>{smart_money_score:.0f}</b>{score_emoji}"

    price_str = (
        f"${price_usd:.8f}" if price_usd and price_usd < 0.001 else
        f"${price_usd:.6f}" if price_usd and price_usd < 0.01 else
        f"${price_usd:.4f}" if price_usd else "N/A"
    )

    parts = [
        f"🟢 <b>BUY</b> · {chain_name.upper()}",
        f"",
        f"👤 <b>{wallet_label}</b>{score_str}",
        f"━━━━━━━━━━━━━━━━━",
        f"🪙 <b>{token_symbol}</b>  |  {price_str}",
    ]

    if invested_usd is not None:
        parts.append(f"💵 Investi: <b>${invested_usd:,.0f}</b>")

    position_label = "🆕 NOUVELLE POSITION" if is_new_position else "➕ RENFORCEMENT"
    parts.append(f"📊 {position_label}")

    if not is_new_position and existing_position_pnl is not None:
        pnl_icon = "📈" if existing_position_pnl > 0 else "📉"
        parts.append(f"{pnl_icon} PnL actuel: <b>{format_pct(existing_position_pnl)}</b>")

    parts += [
        f"━━━━━━━━━━━━━━━━━",
        f"⚡ Détecté en {latency_ms/1000:.2f}s",
        f"🔗 <code>{tx_hash[:16]}...{tx_hash[-6:]}</code>",
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
    pnl_emoji = "🚀" if roi_percent > 100 else ("📈" if realized_pnl > 0 else "📉")
    roi_sign = "+" if roi_percent > 0 else ""

    score_str = ""
    if smart_money_score is not None:
        score_emoji = "🔥" if smart_money_score >= 85 else ("⭐" if smart_money_score >= 70 else "")
        score_str = f" • Score <b>{smart_money_score:.0f}</b>{score_emoji}"

    parts = [
        f"🔴 <b>SELL</b> · {pct_sold:.0f}% · {chain_name.upper()}",
        f"",
        f"👤 <b>{wallet_label}</b>{score_str}",
        f"━━━━━━━━━━━━━━━━━",
        f"🪙 <b>{token_symbol}</b>",
    ]

    if proceeds_usd is not None:
        parts.append(f"💵 Reçu: <b>${proceeds_usd:,.0f}</b>")

    parts += [
        f"{pnl_emoji} ROI: <b>{roi_sign}{roi_percent:.1f}%</b>  |  PnL: <b>{format_usd(realized_pnl)}</b>",
    ]

    if entry_price and sell_price:
        ep = f"${entry_price:.6f}" if entry_price < 0.01 else f"${entry_price:.4f}"
        sp = f"${sell_price:.6f}" if sell_price < 0.01 else f"${sell_price:.4f}"
        parts.append(f"📊 {ep} → {sp}")

    parts += [
        f"⏱️ Tenu: <b>{format_hold_time(hold_time_seconds)}</b>  |  Reste: <b>{remaining_pct:.0f}%</b>",
        f"━━━━━━━━━━━━━━━━━",
        f"🔗 <code>{tx_hash[:16]}...{tx_hash[-6:]}</code>",
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
    pnl_emoji = "🚀" if pnl_pct > 50 else ("📈" if pnl_pct > 0 else "📉")
    pct_sign = "+" if pnl_pct > 0 else ""

    return "\n".join([
        f"📈 <b>POSITION UPDATE</b>",
        f"",
        f"👤 <b>{wallet_label}</b>",
        f"",
        f"🪙 <b>{token_symbol}</b>",
        f"",
        f"Entry: <b>${entry_price:.8f}</b>" if entry_price < 0.01 else f"Entry: <b>${entry_price:.4f}</b>",
        f"Current: <b>${current_price:.8f}</b>" if current_price < 0.01 else f"Current: <b>${current_price:.4f}</b>",
        f"",
        f"{pnl_emoji} PnL: <b>{pct_sign}{pnl_pct:.1f}%</b>",
        f"",
        f"💰 Invested: <b>${invested_usd:,.0f}</b>",
        f"📊 Current value: <b>${current_value_usd:,.0f}</b>",
        f"",
        f"⏱️ Hold: <b>{format_hold_time(hold_time_seconds)}</b>",
    ])


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
        name = w.get("label") or w.get("address", "Unknown")[:10]
        val = w.get("value_usd", 0)
        wallet_lines.append(f"  • {name}: <b>${val:,.0f}</b>")

    return "\n".join([
        f"🚨 <b>SMART MONEY CONSENSUS</b>",
        f"",
        f"🪙 TOKEN: <b>{token_symbol}</b>",
        f"⛓️ {chain_name}",
        f"",
        f"<b>{len(wallets)} tracked wallets</b> bought this token:",
        f"",
        *wallet_lines,
        f"",
        f"💰 Total: <b>${total_usd:,.0f}</b>",
        f"🔥 Confidence: <b>{confidence}</b>",
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
    return "\n".join([
        f"📋 <b>PAPER TRADE SIMULATED</b>",
        f"",
        f"Following: <b>{wallet_label}</b>",
        f"",
        f"🪙 Token: <b>{token_symbol}</b>",
        f"⛓️ {chain_name}",
        f"",
        f"📊 Simulated amount: <b>${simulated_amount_usd:,.0f}</b>",
        f"📋 Copy %: <b>{copy_pct}%</b>",
        f"💰 Entry: <b>${entry_price:.8f}</b>" if entry_price and entry_price < 0.01 else (
            f"💰 Entry: <b>${entry_price:.4f}</b>" if entry_price else "💰 Entry: <b>N/A</b>"
        ),
        f"",
        f"<i>This is a simulation. No real transaction executed.</i>",
    ])


def format_system_alert(
    chain: str,
    issue: str,
    status: str,
    details: str = "",
) -> str:
    return "\n".join([
        f"🚨 <b>SYSTEM ALERT</b>",
        f"",
        f"Chain: <b>{chain}</b>",
        f"Issue: <b>{issue}</b>",
        f"Status: <b>{status}</b>",
        *(["", details] if details else []),
    ])


def format_risk_blocked(token_symbol: str, reason: str, flags: list[str]) -> str:
    flag_lines = "\n".join(f"  ⚠️ {f}" for f in flags[:5])
    return "\n".join([
        f"🚨 <b>TRADE BLOCKED</b>",
        f"",
        f"Token: <b>{token_symbol}</b>",
        f"Reason: <b>{reason}</b>",
        f"",
        f"Flags:",
        flag_lines,
        f"",
        f"Action: No transaction executed.",
    ])


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
    hold_str = format_hold_time(avg_hold_seconds) if avg_hold_seconds else "N/A"
    score_emoji = "🔥" if score >= 85 else ("📈" if score >= 70 else ("⚠️" if score >= 50 else "📉"))
    status = "🟢 Actif" if enabled else "⏸ Pausé"

    lines = [
        f"📊 <b>WALLET</b> — {status}",
        f"",
        f"👤 <b>{label}</b>",
        f"<code>{address}</code>",
    ]

    if chains:
        chains_str = " · ".join(c.upper() for c in chains[:6])
        if len(chains) > 6:
            chains_str += f" +{len(chains)-6}"
        lines.append(f"⛓️ {chains_str}")

    lines += [
        f"",
        f"🏆 Smart Money Score: <b>{score:.0f}/100 {score_emoji}</b>",
        f"",
        f"📈 Trades: <b>{total_trades}</b>  |  Win rate: <b>{win_rate:.1f}%</b>",
        f"📊 ROI moyen: <b>{format_pct(avg_roi)}</b>",
        f"💰 PnL total: <b>{format_usd(total_pnl)}</b>",
        f"",
        f"⏱️ Hold moyen: <b>{hold_str}</b>",
        f"🚀 Meilleur: <b>{format_pct(best_trade or 0)}</b>  |  Pire: <b>{format_pct(worst_trade or 0)}</b>",
    ]

    if score_breakdown:
        lines += [
            f"",
            f"<b>Détail du score:</b>",
            f"  Win rate: {score_breakdown.get('win_rate', 0):.0f}  |  ROI: {score_breakdown.get('average_roi', 0):.0f}  |  Risque: {score_breakdown.get('risk_management', 0):.0f}",
        ]

    if flags:
        flag_lines = " ".join(f"⚠️ {f}" for f in flags[:3])
        lines += ["", flag_lines]

    return "\n".join(lines)


def format_ranking(
    ranking: list[dict],
    chain_filter: str = "all",
    page: int = 0,
) -> str:
    medals = ["🥇", "🥈", "🥉"]
    chain_str = f" — {chain_filter.upper()}" if chain_filter and chain_filter != "all" else ""
    page_str = f" (p.{page+1})" if page > 0 else ""
    lines = [f"🏆 <b>CLASSEMENT SMART MONEY{chain_str}{page_str}</b>", ""]

    if not ranking:
        lines.append("<i>Aucun wallet classé pour l'instant.</i>")
        return "\n".join(lines)

    for entry in ranking[:10]:
        rank = entry.get("rank", 0) + page * 10
        medal = medals[rank - 1] if rank <= 3 else f"<b>{rank}.</b>"
        label = entry.get("label") or entry.get("address", "?")[:12]
        score = entry.get("score", 0) or 0
        roi = entry.get("average_roi", 0) or 0
        wr = entry.get("win_rate", 0) or 0
        pnl = entry.get("total_pnl_usd", 0) or 0
        score_icon = "🔥" if score >= 85 else ("⭐" if score >= 70 else "")

        lines.append(
            f"{medal} <b>{label}</b> {score_icon}\n"
            f"   Score: <b>{score:.0f}</b> | ROI: {format_pct(roi)} | WR: {wr:.0f}% | PnL: {format_usd(pnl)}"
        )
    return "\n".join(lines)
