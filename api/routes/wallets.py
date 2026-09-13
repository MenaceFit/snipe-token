"""Wallet REST endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.connection import get_db
from src.database.models import Wallet, WalletMetrics
from src.database.repositories.wallet_repo import WalletRepository

router = APIRouter(prefix="/wallets", tags=["wallets"])


class AddWalletRequest(BaseModel):
    address: str
    chain_key: str
    label: Optional[str] = None
    group_name: Optional[str] = None
    notes: Optional[str] = None


@router.get("/")
async def list_wallets(db: AsyncSession = Depends(get_db)):
    repo = WalletRepository(db)
    wallets = await repo.list_enabled()
    return [
        {
            "id": w.id,
            "address": w.address,
            "label": w.label,
            "group_name": w.group_name,
            "score": w.smart_money_score,
            "enabled": w.enabled,
            "flags": w.risk_flags or [],
            "chains": [wc.chain.chain_key for wc in w.chains if wc.enabled],
        }
        for w in wallets
    ]


@router.get("/{wallet_id}")
async def get_wallet(wallet_id: int, db: AsyncSession = Depends(get_db)):
    repo = WalletRepository(db)
    wallet = await repo.get_by_id(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    result = await db.execute(
        select(WalletMetrics).where(
            WalletMetrics.wallet_id == wallet_id,
            WalletMetrics.chain_key == None,
        )
    )
    metrics = result.scalar_one_or_none()
    return {
        "id": wallet.id,
        "address": wallet.address,
        "label": wallet.label,
        "score": wallet.smart_money_score,
        "flags": wallet.risk_flags or [],
        "chains": [wc.chain.chain_key for wc in wallet.chains if wc.enabled],
        "metrics": {
            "total_trades": metrics.total_trades if metrics else 0,
            "win_rate": metrics.win_rate if metrics else 0,
            "average_roi": metrics.average_roi if metrics else 0,
            "total_pnl_usd": metrics.total_pnl_usd if metrics else 0,
            "max_drawdown": metrics.max_drawdown if metrics else 0,
            "profit_factor": metrics.profit_factor if metrics else 0,
            "best_trade_roi": metrics.best_trade_roi if metrics else 0,
            "worst_trade_roi": metrics.worst_trade_roi if metrics else 0,
        } if metrics else None,
    }


@router.delete("/{wallet_id}")
async def remove_wallet(wallet_id: int, db: AsyncSession = Depends(get_db)):
    repo = WalletRepository(db)
    wallet = await repo.get_by_id(wallet_id)
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")
    await repo.update(wallet, enabled=False)
    return {"success": True}
