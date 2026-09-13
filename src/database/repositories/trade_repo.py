"""Trade, Transaction and Position repositories."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Position, PositionStatus, Trade, TradeSide, Transaction


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_hash(self, tx_hash: str, chain_id: int) -> Optional[Transaction]:
        result = await self.session.execute(
            select(Transaction).where(
                Transaction.tx_hash == tx_hash.lower(),
                Transaction.chain_id == chain_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Transaction:
        if "tx_hash" in kwargs:
            kwargs["tx_hash"] = kwargs["tx_hash"].lower()
        tx = Transaction(**kwargs)
        self.session.add(tx)
        await self.session.flush()
        return tx

    async def update(self, tx: Transaction, **kwargs) -> Transaction:
        for k, v in kwargs.items():
            setattr(tx, k, v)
        await self.session.flush()
        return tx


class TradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs) -> Trade:
        trade = Trade(**kwargs)
        self.session.add(trade)
        await self.session.flush()
        return trade

    async def get_by_wallet(
        self,
        wallet_id: int,
        chain_id: Optional[int] = None,
        token_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Trade]:
        q = (
            select(Trade)
            .where(Trade.wallet_id == wallet_id)
            .order_by(desc(Trade.timestamp))
            .limit(limit)
            .offset(offset)
        )
        if chain_id:
            q = q.where(Trade.chain_id == chain_id)
        if token_id:
            q = q.where(Trade.token_id == token_id)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_top_by_roi(
        self,
        min_roi: float = 50.0,
        min_value_usd: float = 100.0,
        limit: int = 20,
    ) -> list[Trade]:
        result = await self.session.execute(
            select(Trade)
            .where(
                Trade.side == TradeSide.SELL,
                Trade.roi_percent >= min_roi,
                Trade.value_usd >= min_value_usd,
            )
            .order_by(desc(Trade.roi_percent))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_wallet(self, wallet_id: int) -> int:
        from sqlalchemy import func as sqlfunc
        result = await self.session.execute(
            select(sqlfunc.count()).select_from(Trade).where(Trade.wallet_id == wallet_id)
        )
        return result.scalar_one()


class PositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        wallet_id: int,
        chain_id: int,
        token_id: int,
    ) -> tuple[Position, bool]:
        result = await self.session.execute(
            select(Position).where(
                Position.wallet_id == wallet_id,
                Position.chain_id == chain_id,
                Position.token_id == token_id,
                Position.status != PositionStatus.CLOSED,
            )
        )
        pos = result.scalar_one_or_none()
        if pos:
            return pos, False
        pos = Position(
            wallet_id=wallet_id,
            chain_id=chain_id,
            token_id=token_id,
        )
        self.session.add(pos)
        await self.session.flush()
        return pos, True

    async def get_open_positions(
        self, wallet_id: Optional[int] = None, chain_id: Optional[int] = None
    ) -> list[Position]:
        q = select(Position).where(Position.status != PositionStatus.CLOSED)
        if wallet_id:
            q = q.where(Position.wallet_id == wallet_id)
        if chain_id:
            q = q.where(Position.chain_id == chain_id)
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def update(self, position: Position, **kwargs) -> Position:
        for k, v in kwargs.items():
            setattr(position, k, v)
        await self.session.flush()
        return position

    async def count_today(self) -> int:
        from datetime import date
        from sqlalchemy import func as sqlfunc, cast, Date
        today = date.today()
        result = await self.session.execute(
            select(sqlfunc.count())
            .select_from(Trade)
            .where(cast(Trade.timestamp, Date) == today)
        )
        return result.scalar_one()
