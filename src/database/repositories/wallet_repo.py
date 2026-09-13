"""Wallet repository — CRUD for wallets, chains, wallet_chains."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models import Chain, Wallet, WalletChain


class WalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_address(self, address: str) -> Optional[Wallet]:
        result = await self.session.execute(
            select(Wallet)
            .where(Wallet.address == address.lower())
            .options(selectinload(Wallet.chains).selectinload(WalletChain.chain))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, wallet_id: int) -> Optional[Wallet]:
        result = await self.session.execute(
            select(Wallet)
            .where(Wallet.id == wallet_id)
            .options(selectinload(Wallet.chains).selectinload(WalletChain.chain))
        )
        return result.scalar_one_or_none()

    async def list_enabled(self, chain_key: Optional[str] = None) -> list[Wallet]:
        q = (
            select(Wallet)
            .where(Wallet.enabled == True)
            .options(selectinload(Wallet.chains).selectinload(WalletChain.chain))
        )
        if chain_key:
            q = q.join(WalletChain).join(Chain).where(Chain.chain_key == chain_key)
        result = await self.session.execute(q)
        return list(result.scalars().unique().all())

    async def create(
        self,
        address: str,
        label: Optional[str] = None,
        group_name: Optional[str] = None,
        notes: Optional[str] = None,
        added_by_chat_id: Optional[int] = None,
    ) -> Wallet:
        wallet = Wallet(
            address=address.lower(),
            label=label,
            group_name=group_name,
            notes=notes,
            added_by_chat_id=added_by_chat_id,
        )
        self.session.add(wallet)
        await self.session.flush()
        return wallet

    async def update(self, wallet: Wallet, **kwargs) -> Wallet:
        for k, v in kwargs.items():
            setattr(wallet, k, v)
        await self.session.flush()
        return wallet

    async def delete(self, wallet: Wallet) -> None:
        await self.session.delete(wallet)
        await self.session.flush()

    async def add_chain(self, wallet_id: int, chain_id: int) -> WalletChain:
        existing = await self.session.execute(
            select(WalletChain).where(
                WalletChain.wallet_id == wallet_id, WalletChain.chain_id == chain_id
            )
        )
        wc = existing.scalar_one_or_none()
        if wc:
            wc.enabled = True
        else:
            wc = WalletChain(wallet_id=wallet_id, chain_id=chain_id)
            self.session.add(wc)
        await self.session.flush()
        return wc

    async def get_chain_by_key(self, chain_key: str) -> Optional[Chain]:
        result = await self.session.execute(
            select(Chain).where(Chain.chain_key == chain_key)
        )
        return result.scalar_one_or_none()

    async def list_all_chains(self) -> list[Chain]:
        result = await self.session.execute(select(Chain).where(Chain.enabled == True))
        return list(result.scalars().all())

    async def count_wallets(self) -> int:
        from sqlalchemy import func as sqlfunc
        result = await self.session.execute(
            select(sqlfunc.count()).select_from(Wallet).where(Wallet.enabled == True)
        )
        return result.scalar_one()
