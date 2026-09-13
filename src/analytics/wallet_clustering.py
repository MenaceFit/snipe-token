"""Wallet clustering — detect wallets funded from the same source or trading in lockstep."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Trade, TradeSide, Wallet, WalletCluster

logger = logging.getLogger(__name__)

# Max minutes between two buys to be considered "coordinated"
COORDINATION_WINDOW_MINUTES = 5
# Minimum number of wallets buying the same token within the window to flag
MIN_CLUSTER_SIZE = 3


async def detect_clusters(
    db: AsyncSession,
    token_id: int,
    lookback_hours: int = 24,
) -> Optional[dict]:
    """
    Detect wallets that buy the same token within a tight time window.
    Returns cluster info if one is found, else None.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    result = await db.execute(
        select(Trade)
        .where(
            Trade.token_id == token_id,
            Trade.side == TradeSide.BUY,
            Trade.timestamp >= cutoff,
        )
        .order_by(Trade.timestamp)
    )
    buys = result.scalars().all()

    if len(buys) < MIN_CLUSTER_SIZE:
        return None

    # Group into time windows
    window = timedelta(minutes=COORDINATION_WINDOW_MINUTES)
    clusters: list[list[Trade]] = []
    current: list[Trade] = [buys[0]]

    for buy in buys[1:]:
        if buy.timestamp - current[-1].timestamp <= window:
            current.append(buy)
        else:
            if len(current) >= MIN_CLUSTER_SIZE:
                clusters.append(list(current))
            current = [buy]

    if len(current) >= MIN_CLUSTER_SIZE:
        clusters.append(current)

    if not clusters:
        return None

    # Take the largest cluster
    largest = max(clusters, key=len)
    wallet_ids = list({t.wallet_id for t in largest})

    return {
        "token_id": token_id,
        "cluster_size": len(wallet_ids),
        "wallet_ids": wallet_ids,
        "first_buy": largest[0].timestamp.isoformat(),
        "last_buy": largest[-1].timestamp.isoformat(),
        "window_minutes": COORDINATION_WINDOW_MINUTES,
    }


async def flag_cluster_wallets(
    db: AsyncSession,
    wallet_ids: list[int],
    cluster_name: str,
) -> None:
    """Persist a WalletCluster record and add CLUSTER risk flag to each wallet."""
    from src.database.models import RiskFlag

    cluster = WalletCluster(
        name=cluster_name,
        wallet_ids=wallet_ids,
        detected_at=datetime.now(timezone.utc),
    )
    db.add(cluster)

    for wid in wallet_ids:
        result = await db.execute(select(Wallet).where(Wallet.id == wid))
        wallet = result.scalar_one_or_none()
        if wallet:
            flags = list(wallet.risk_flags or [])
            flag = RiskFlag.CLUSTER.value
            if flag not in flags:
                flags.append(flag)
            wallet.risk_flags = flags

    await db.commit()
    logger.info("Flagged cluster %s with %d wallets", cluster_name, len(wallet_ids))
