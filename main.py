"""
Application entry point — starts all services and runs until interrupted.

Services started:
  - FastAPI REST API (uvicorn)
  - Telegram bot (polling or webhook)
  - WalletManager + EVMAdapter / SolanaAdapter per chain
  - TransactionEngine event processor
  - BackgroundScheduler (unrealized PnL refresh, metrics recomputation)
  - Prometheus metrics server
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

import uvicorn

from src.config import get_settings
from src.core.price_engine import PriceEngine
from src.core.risk_engine import RiskEngine
from src.core.wallet_manager import WalletManager
from src.monitoring.metrics import MetricsCollector, setup_logging
from src.workers.scheduler import BackgroundScheduler

logger = logging.getLogger(__name__)
settings = get_settings()


async def _build_chain_adapters(wallet_manager: WalletManager) -> None:
    """Register adapters for all configured chains."""
    from src.chains.evm.adapter import EVMAdapter
    from src.chains.solana.adapter import SolanaAdapter

    evm_chains = [
        ("ethereum", 1, settings.eth_rpc_ws, settings.eth_rpc_http, settings.eth_rpc_ws_backup),
        ("base", 8453, settings.base_rpc_ws, settings.base_rpc_http, settings.base_rpc_ws_backup),
        ("arbitrum", 42161, settings.arb_rpc_ws, settings.arb_rpc_http, settings.arb_rpc_ws_backup),
        ("bsc", 56, settings.bsc_rpc_ws, settings.bsc_rpc_http, settings.bsc_rpc_ws_backup),
        ("polygon", 137, settings.polygon_rpc_ws, settings.polygon_rpc_http, settings.polygon_rpc_ws_backup),
        ("optimism", 10, settings.op_rpc_ws, settings.op_rpc_http, settings.op_rpc_ws_backup),
        ("avalanche", 43114, settings.avax_rpc_ws, settings.avax_rpc_http, settings.avax_rpc_ws_backup),
    ]

    for chain_key, chain_id, ws, http, ws_backup in evm_chains:
        if http:
            adapter = EVMAdapter(
                chain_key=chain_key,
                chain_id=chain_id,
                rpc_ws_url=ws or None,
                rpc_http_url=http,
                rpc_ws_backup_url=ws_backup or None,
            )
            wallet_manager.register_adapter(chain_key, adapter)
            logger.info("Registered EVM adapter: %s", chain_key)

    if settings.solana_rpc_http:
        sol_adapter = SolanaAdapter(
            rpc_http_url=settings.solana_rpc_http,
            rpc_ws_url=settings.solana_rpc_ws or None,
        )
        wallet_manager.register_adapter("solana", sol_adapter)
        logger.info("Registered Solana adapter")


async def _build_telegram_bot(wallet_manager: WalletManager):
    """Build and return the Telegram bot (or None if no token configured)."""
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — bot disabled")
        return None

    from src.copytrading.live_trader import LiveTrader
    from src.copytrading.paper_trader import PaperTrader
    from src.core.risk_engine import RiskEngine
    from src.telegram.bot import SnipeBot

    risk = RiskEngine()
    paper = PaperTrader(risk_engine=risk)
    live = LiveTrader(
        risk_engine=risk,
        max_trade_size_usd=settings.copy_trading_max_trade_size_usd,
        max_daily_loss_usd=settings.copy_trading_max_daily_loss_usd,
        max_position_size_usd=settings.copy_trading_max_position_size_usd,
        max_slippage_bps=settings.copy_trading_max_slippage_bps,
    )

    bot = SnipeBot(
        token=settings.telegram_bot_token,
        chat_ids=settings.allowed_chat_ids,
        admin_ids=settings.admin_ids,
        wallet_manager=wallet_manager,
        paper_trader=paper,
        live_trader=live,
    )
    return bot


async def main() -> None:
    setup_logging(log_level=settings.log_level, json_logs=settings.is_production)
    logger.info("Starting Snipe Token Bot — environment=%s", settings.environment)

    # Prometheus metrics
    metrics = MetricsCollector()
    if settings.enable_metrics:
        metrics.start_server(port=settings.prometheus_port)

    # Core services
    price_engine = PriceEngine()
    wallet_manager = WalletManager()
    await _build_chain_adapters(wallet_manager)

    # Telegram bot
    bot = await _build_telegram_bot(wallet_manager)

    # Wire the alert callback into the transaction engine's pipeline
    if bot:
        from src.core.transaction_engine import TransactionEngine

        tx_engine = TransactionEngine(alert_callback=bot.send_trade_alert)
        wallet_manager.set_transaction_engine(tx_engine)

    # Restore subscriptions from Redis (wallets added before restart)
    await wallet_manager.restore_subscriptions()

    # Background tasks
    scheduler = BackgroundScheduler(price_engine=price_engine)
    await scheduler.start()

    # Graceful shutdown handler
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    # Start the Telegram bot (non-blocking, runs in background)
    bot_task: Optional[asyncio.Task] = None
    if bot:
        bot_task = asyncio.create_task(bot.run_polling())

    # Start FastAPI in a background task
    config = uvicorn.Config(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    logger.info(
        "All services running — API on %s:%d", settings.api_host, settings.api_port
    )

    # Wait for shutdown signal
    await shutdown_event.wait()
    logger.info("Shutting down...")

    server.should_exit = True
    await scheduler.stop()
    if bot_task:
        bot_task.cancel()
    await asyncio.gather(api_task, return_exceptions=True)

    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
