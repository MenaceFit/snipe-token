"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import analytics, backtesting, copy_trading, health, tokens, trades, wallets
from src.database.connection import engine
from src.monitoring.metrics import setup_logging

setup_logging(json_logs=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Nothing to start/stop at the API layer — the engine + bot run in main.py
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Snipe Token API",
        description="Wallet intelligence & copy trading analytics",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(wallets.router)
    app.include_router(analytics.router)
    app.include_router(trades.router)
    app.include_router(tokens.router)
    app.include_router(copy_trading.router)
    app.include_router(backtesting.router)

    return app


app = create_app()
