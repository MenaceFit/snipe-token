"""
Application entry point — starts all services and runs until interrupted.

Services:
  - FastAPI REST API (uvicorn)
  - Telegram bot (polling) with multi-menu FSM
  - WalletManager + EVMAdapter per chain (all DexScreener EVM chains)
  - TransactionEngine event processor
  - BackgroundScheduler (unrealized PnL refresh, metrics recomputation)
  - Prometheus metrics server
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Optional

import redis.asyncio as aioredis
import uvicorn

from src.config import get_settings
from src.core.price_engine import PriceEngine
from src.core.wallet_manager import WalletManager
from src.monitoring.metrics import MetricsCollector, setup_logging
from src.workers.scheduler import BackgroundScheduler

logger = logging.getLogger(__name__)
settings = get_settings()


async def _build_chain_adapters(wallet_manager: WalletManager) -> None:
    """Register EVM adapters for all configured chains (no Solana)."""
    from src.chains.evm.adapter import EVMAdapter

    # (chain_key, chain_id, ws_attr, http_attr, ws_backup_attr)
    evm_chains = [
        # Tier 1 — high priority
        ("ethereum",      1,          "eth_rpc_ws",          "eth_rpc_http",          "eth_rpc_ws_backup"),
        ("bsc",           56,         "bsc_rpc_ws",          "bsc_rpc_http",          "bsc_rpc_ws_backup"),
        ("polygon",       137,        "polygon_rpc_ws",      "polygon_rpc_http",      "polygon_rpc_ws_backup"),
        ("arbitrum",      42161,      "arb_rpc_ws",          "arb_rpc_http",          "arb_rpc_ws_backup"),
        ("optimism",      10,         "op_rpc_ws",           "op_rpc_http",           "op_rpc_ws_backup"),
        ("base",          8453,       "base_rpc_ws",         "base_rpc_http",         "base_rpc_ws_backup"),
        ("avalanche",     43114,      "avax_rpc_ws",         "avax_rpc_http",         "avax_rpc_ws_backup"),
        # Tier 2 — medium volume
        ("blast",         81457,      "blast_rpc_ws",        "blast_rpc_http",        None),
        ("linea",         59144,      "linea_rpc_ws",        "linea_rpc_http",        None),
        ("zksync",        324,        "zksync_rpc_ws",       "zksync_rpc_http",       None),
        ("scroll",        534352,     "scroll_rpc_ws",       "scroll_rpc_http",       None),
        ("fantom",        250,        "fantom_rpc_ws",       "fantom_rpc_http",       None),
        ("cronos",        25,         "cronos_rpc_ws",       "cronos_rpc_http",       None),
        ("celo",          42220,      "celo_rpc_ws",         "celo_rpc_http",         None),
        ("gnosis",        100,        "gnosis_rpc_ws",       "gnosis_rpc_http",       None),
        ("mantle",        5000,       "mantle_rpc_ws",       "mantle_rpc_http",       None),
        ("mode",          34443,      "mode_rpc_ws",         "mode_rpc_http",         None),
        ("core",          1116,       "core_rpc_ws",         "core_rpc_http",         None),
        ("metis",         1088,       "metis_rpc_ws",        "metis_rpc_http",        None),
        ("kava",          2222,       "kava_rpc_ws",         "kava_rpc_http",         None),
        ("moonbeam",      1284,       "moonbeam_rpc_ws",     "moonbeam_rpc_http",     None),
        ("fuse",          122,        "fuse_rpc_ws",         "fuse_rpc_http",         None),
        ("aurora",        1313161554, "aurora_rpc_ws",       "aurora_rpc_http",       None),
        ("sei",           1329,       "sei_rpc_ws",          "sei_rpc_http",          None),
        ("taiko",         167000,     "taiko_rpc_ws",        "taiko_rpc_http",        None),
        ("sonic",         146,        "sonic_rpc_ws",        "sonic_rpc_http",        None),
        ("berachain",     80094,      "berachain_rpc_ws",    "berachain_rpc_http",    None),
        ("manta",         169,        "manta_rpc_ws",        "manta_rpc_http",        None),
        ("fraxtal",       252,        "fraxtal_rpc_ws",      "fraxtal_rpc_http",      None),
        ("polygon_zkevm", 1101,       "polygon_zkevm_rpc_ws","polygon_zkevm_rpc_http",None),
        ("klaytn",        8217,       "klaytn_rpc_ws",       "klaytn_rpc_http",       None),
        # Tier 3 — extended coverage
        ("moonriver",     1285,       "moonriver_rpc_ws",    "moonriver_rpc_http",    None),
        ("canto",         7700,       "canto_rpc_ws",        "canto_rpc_http",        None),
        ("evmos",         9001,       "evmos_rpc_ws",        "evmos_rpc_http",        None),
        ("conflux",       1030,       "conflux_rpc_ws",      "conflux_rpc_http",      None),
        ("xlayer",        196,        "xlayer_rpc_ws",       "xlayer_rpc_http",       None),
        ("zetachain",     7000,       "zetachain_rpc_ws",    "zetachain_rpc_http",    None),
        ("merlin",        4200,       "merlin_rpc_ws",       "merlin_rpc_http",       None),
        ("bob",           60808,      "bob_rpc_ws",          "bob_rpc_http",          None),
        ("cyber",         7560,       "cyber_rpc_ws",        "cyber_rpc_http",        None),
        ("degen",         666666666,  "degen_rpc_ws",        "degen_rpc_http",        None),
        ("gravity",       1625,       "gravity_rpc_ws",      "gravity_rpc_http",      None),
        ("viction",       88,         "viction_rpc_ws",      "viction_rpc_http",      None),
        ("harmony",       1666600000, "harmony_rpc_ws",      "harmony_rpc_http",      None),
        ("velas",         106,        "velas_rpc_ws",        "velas_rpc_http",        None),
        ("oasis_sapphire",23294,      "oasis_sapphire_rpc_ws","oasis_sapphire_rpc_http",None),
        ("neon",          245022934,  "neon_rpc_ws",         "neon_rpc_http",         None),
    ]

    for chain_key, chain_id, ws_attr, http_attr, ws_backup_attr in evm_chains:
        http = getattr(settings, http_attr, "")
        ws = getattr(settings, ws_attr, "") if ws_attr else ""
        ws_backup = getattr(settings, ws_backup_attr, "") if ws_backup_attr else ""

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
        else:
            logger.debug("Skipping chain %s (no RPC configured)", chain_key)


async def _build_telegram_bot(wallet_manager: WalletManager, redis: aioredis.Redis):
    """Build and return the Telegram bot (None if no token configured)."""
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
        redis=redis,
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

    # Redis
    redis = aioredis.from_url(settings.redis_url, decode_responses=False)

    # Core services
    price_engine = PriceEngine()
    wallet_manager = WalletManager()
    await _build_chain_adapters(wallet_manager)

    # Telegram bot
    bot = await _build_telegram_bot(wallet_manager, redis)

    # Wire alert callback into the transaction engine
    if bot:
        from src.core.transaction_engine import TransactionEngine
        tx_engine = TransactionEngine(alert_callback=bot.send_trade_alert)
        wallet_manager.set_transaction_engine(tx_engine)

    # Restore subscriptions from Redis
    await wallet_manager.restore_subscriptions()

    # Background scheduler
    scheduler = BackgroundScheduler(price_engine=price_engine)
    await scheduler.start()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    # Start Telegram bot (background task)
    bot_task: Optional[asyncio.Task] = None
    if bot:
        bot_task = asyncio.create_task(bot.run_polling())

    # Start FastAPI
    config = uvicorn.Config(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    logger.info("All services running — API on %s:%d", settings.api_host, settings.api_port)

    await shutdown_event.wait()
    logger.info("Shutting down...")

    server.should_exit = True
    await scheduler.stop()
    if bot_task:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    await asyncio.gather(api_task, return_exceptions=True)
    await redis.aclose()

    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
