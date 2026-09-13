"""Structured logging and Prometheus metrics."""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import structlog

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


def setup_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    logging.basicConfig(level=level)
    # Quiet noisy libraries
    for lib in ("web3", "asyncio", "httpx", "aiohttp", "websockets"):
        logging.getLogger(lib).setLevel(logging.WARNING)


class MetricsCollector:
    """Prometheus metrics for operational visibility."""

    def __init__(self) -> None:
        if not PROMETHEUS_AVAILABLE:
            return

        self.transactions_total = Counter(
            "snipe_transactions_total", "Total transactions processed", ["chain", "status"]
        )
        self.trades_total = Counter(
            "snipe_trades_total", "Total trades classified", ["chain", "side"]
        )
        self.latency_histogram = Histogram(
            "snipe_latency_ms", "End-to-end latency in ms", ["chain"],
            buckets=[50, 100, 250, 500, 1000, 2500, 5000, 10000],
        )
        self.rpc_errors_total = Counter(
            "snipe_rpc_errors_total", "RPC errors", ["chain"]
        )
        self.ws_reconnects_total = Counter(
            "snipe_ws_reconnects_total", "WebSocket reconnections", ["chain"]
        )
        self.tracked_wallets = Gauge(
            "snipe_tracked_wallets", "Number of tracked wallets"
        )
        self.event_queue_size = Gauge(
            "snipe_event_queue_size", "Current event queue depth"
        )
        self.price_fetch_errors = Counter(
            "snipe_price_fetch_errors_total", "Price fetch failures", ["source"]
        )
        self.alerts_sent_total = Counter(
            "snipe_alerts_sent_total", "Telegram alerts sent", ["type"]
        )

    def start_server(self, port: int = 9090) -> None:
        if PROMETHEUS_AVAILABLE:
            start_http_server(port)
            logging.getLogger(__name__).info(f"Prometheus metrics on :{port}")

    def record_trade(self, chain: str, side: str) -> None:
        if PROMETHEUS_AVAILABLE:
            self.trades_total.labels(chain=chain, side=side).inc()

    def record_latency(self, chain: str, latency_ms: int) -> None:
        if PROMETHEUS_AVAILABLE:
            self.latency_histogram.labels(chain=chain).observe(latency_ms)

    def record_rpc_error(self, chain: str) -> None:
        if PROMETHEUS_AVAILABLE:
            self.rpc_errors_total.labels(chain=chain).inc()

    def record_ws_reconnect(self, chain: str) -> None:
        if PROMETHEUS_AVAILABLE:
            self.ws_reconnects_total.labels(chain=chain).inc()

    def set_tracked_wallets(self, count: int) -> None:
        if PROMETHEUS_AVAILABLE:
            self.tracked_wallets.set(count)

    def set_queue_size(self, size: int) -> None:
        if PROMETHEUS_AVAILABLE:
            self.event_queue_size.set(size)


# Global singleton
metrics = MetricsCollector()
