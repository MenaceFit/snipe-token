"""Position and PnL engine — reconstructs positions from trades."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.trade_engine import ClassifiedTrade, TradeClassification
from src.database.models import Position, PositionStatus
from src.database.repositories.trade_repo import PositionRepository

logger = logging.getLogger(__name__)

DUST_THRESHOLD = Decimal("0.000001")


class PositionEngine:
    """
    Maintains per-wallet per-token positions using Average Cost method (default) or FIFO.
    Updates realized and unrealized PnL on every trade.
    """

    def __init__(self, cost_method: str = "average_cost") -> None:
        self._cost_method = cost_method

    async def process_trade(
        self,
        session: AsyncSession,
        wallet_id: int,
        chain_id: int,
        token_id: int,
        trade: ClassifiedTrade,
        gas_cost_usd: float = 0.0,
        fees_usd: float = 0.0,
        current_price_usd: Optional[float] = None,
    ) -> tuple[Position, float]:
        """
        Apply a classified trade to the position.
        Returns (updated_position, realized_pnl_usd).
        realized_pnl_usd is 0 for buys.
        """
        repo = PositionRepository(session)
        position, is_new = await repo.get_or_create(wallet_id, chain_id, token_id)

        if trade.classification == TradeClassification.BUY:
            realized_pnl = await self._apply_buy(position, trade, gas_cost_usd, fees_usd)
        elif trade.classification == TradeClassification.SELL:
            realized_pnl = await self._apply_sell(position, trade, gas_cost_usd, fees_usd, current_price_usd)
        else:
            return position, 0.0

        if current_price_usd is not None:
            self._update_unrealized(position, current_price_usd)

        await repo.update(position)
        return position, realized_pnl

    async def _apply_buy(
        self,
        pos: Position,
        trade: ClassifiedTrade,
        gas_usd: float,
        fees_usd: float,
    ) -> float:
        qty = trade.base_amount
        value_usd = trade.quote_amount_usd or 0.0
        total_cost = value_usd + gas_usd + fees_usd

        now = datetime.now(timezone.utc)

        if pos.total_bought_quantity == 0:
            # First buy
            pos.entry_price_usd = trade.price_usd
            pos.first_buy_at = now

        pos.last_buy_at = now
        pos.total_bought_quantity += qty
        pos.current_quantity += qty
        pos.total_invested_usd += total_cost
        pos.total_fees_usd += gas_usd + fees_usd

        # Recalculate average entry
        if pos.current_quantity > 0 and pos.total_invested_usd > 0:
            pos.average_entry_usd = pos.total_invested_usd / float(pos.current_quantity)

        # FIFO: add lot
        if self._cost_method == "fifo":
            lots = list(pos.fifo_lots or [])
            lots.append({
                "qty": str(qty),
                "cost_usd": total_cost,
                "price_usd": trade.price_usd,
                "timestamp": now.isoformat(),
            })
            pos.fifo_lots = lots

        pos.status = PositionStatus.OPEN
        return 0.0

    async def _apply_sell(
        self,
        pos: Position,
        trade: ClassifiedTrade,
        gas_usd: float,
        fees_usd: float,
        current_price_usd: Optional[float],
    ) -> float:
        qty_sold = trade.base_amount
        proceeds_usd = trade.quote_amount_usd or 0.0
        if proceeds_usd == 0 and current_price_usd:
            proceeds_usd = float(qty_sold) * current_price_usd

        realized_pnl = 0.0
        now = datetime.now(timezone.utc)

        if pos.current_quantity <= DUST_THRESHOLD:
            logger.debug("Sell on empty position, ignoring")
            return 0.0

        # Cap at current quantity
        qty_sold = min(qty_sold, pos.current_quantity)

        if self._cost_method == "fifo":
            realized_pnl = self._fifo_sell(pos, qty_sold, proceeds_usd, gas_usd, fees_usd)
        else:
            realized_pnl = self._average_cost_sell(pos, qty_sold, proceeds_usd, gas_usd, fees_usd)

        pos.total_sold_quantity += qty_sold
        pos.total_received_usd += proceeds_usd
        pos.total_fees_usd += gas_usd + fees_usd
        pos.realized_pnl_usd += realized_pnl
        pos.last_sell_at = now

        if pos.total_bought_quantity > 0:
            pos.percentage_sold = float(pos.total_sold_quantity / pos.total_bought_quantity * 100)

        # Determine position status
        if pos.current_quantity <= DUST_THRESHOLD:
            pos.status = PositionStatus.CLOSED
            pos.closed_at = now
            pos.current_quantity = Decimal(0)
        elif pos.total_sold_quantity > 0:
            pos.status = PositionStatus.PARTIAL

        return realized_pnl

    def _average_cost_sell(
        self,
        pos: Position,
        qty_sold: Decimal,
        proceeds_usd: float,
        gas_usd: float,
        fees_usd: float,
    ) -> float:
        if pos.current_quantity <= 0:
            return 0.0
        avg_cost = pos.total_invested_usd / float(pos.current_quantity)
        cost_basis = avg_cost * float(qty_sold)
        realized_pnl = proceeds_usd - cost_basis - gas_usd - fees_usd
        pos.current_quantity -= qty_sold
        # Adjust total_invested proportionally
        if pos.total_bought_quantity > 0:
            pct = float(qty_sold / pos.total_bought_quantity)
            pos.total_invested_usd = max(0, pos.total_invested_usd - cost_basis)
        return realized_pnl

    def _fifo_sell(
        self,
        pos: Position,
        qty_sold: Decimal,
        proceeds_usd: float,
        gas_usd: float,
        fees_usd: float,
    ) -> float:
        lots = list(pos.fifo_lots or [])
        remaining_qty = qty_sold
        cost_basis = Decimal(0)

        new_lots = []
        for lot in lots:
            if remaining_qty <= 0:
                new_lots.append(lot)
                continue
            lot_qty = Decimal(lot["qty"])
            lot_cost = Decimal(str(lot.get("cost_usd", 0)))
            if lot_qty <= remaining_qty:
                cost_basis += lot_cost
                remaining_qty -= lot_qty
            else:
                # Partial lot
                used_fraction = remaining_qty / lot_qty
                cost_basis += lot_cost * used_fraction
                lot["qty"] = str(lot_qty - remaining_qty)
                lot["cost_usd"] = str(lot_cost * (1 - used_fraction))
                new_lots.append(lot)
                remaining_qty = Decimal(0)

        pos.fifo_lots = new_lots
        pos.current_quantity -= qty_sold
        realized_pnl = proceeds_usd - float(cost_basis) - gas_usd - fees_usd
        return realized_pnl

    def _update_unrealized(self, pos: Position, current_price_usd: float) -> None:
        if pos.current_quantity <= DUST_THRESHOLD:
            pos.unrealized_pnl_usd = 0.0
            pos.current_price_usd = current_price_usd
            pos.current_value_usd = 0.0
            pos.roi_percent = None
            return

        current_value = float(pos.current_quantity) * current_price_usd
        # Cost of remaining position
        if pos.total_bought_quantity > 0:
            remaining_fraction = float(pos.current_quantity / pos.total_bought_quantity)
            cost_remaining = pos.total_invested_usd * remaining_fraction
        else:
            cost_remaining = 0.0

        unrealized = current_value - cost_remaining
        total_pnl = pos.realized_pnl_usd + unrealized

        pos.unrealized_pnl_usd = unrealized
        pos.total_pnl_usd = total_pnl
        pos.current_price_usd = current_price_usd
        pos.current_value_usd = current_value
        pos.price_updated_at = datetime.now(timezone.utc)

        if pos.total_invested_usd > 0:
            pos.roi_percent = (total_pnl / pos.total_invested_usd) * 100
        else:
            pos.roi_percent = None

    async def update_unrealized_pnl(
        self,
        session: AsyncSession,
        position: Position,
        current_price_usd: float,
    ) -> None:
        """Standalone update for periodic price refresh."""
        self._update_unrealized(position, current_price_usd)
        repo = PositionRepository(session)
        await repo.update(position)
