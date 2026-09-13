"""Token info and risk check endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.risk_engine import RiskEngine
from src.database.connection import get_db
from src.database.models import Token

router = APIRouter(prefix="/tokens", tags=["tokens"])

_risk_engine = RiskEngine()


@router.get("/{token_address}/risk")
async def token_risk(
    token_address: str,
    chain_key: str = Query(...),
):
    result = await _risk_engine.check_token(token_address, chain_key)
    return {
        "address": token_address,
        "chain_key": chain_key,
        "risk_level": result.risk_level,
        "risk_score": result.risk_score,
        "flags": result.flags,
        "safe_to_trade": _risk_engine.is_safe_to_trade(result),
    }


@router.get("/")
async def list_tokens(
    chain_id: int | None = Query(None),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    q = select(Token)
    if chain_id:
        q = q.where(Token.chain_id == chain_id)
    result = await db.execute(q.limit(limit))
    tokens = result.scalars().all()
    return [
        {
            "id": t.id,
            "address": t.address,
            "symbol": t.symbol,
            "name": t.name,
            "decimals": t.decimals,
            "chain_id": t.chain_id,
            "is_verified": t.is_verified,
            "is_honeypot": t.is_honeypot,
            "risk_score": t.risk_score,
        }
        for t in tokens
    ]
