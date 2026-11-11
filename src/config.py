"""Application configuration loaded from .env and config.yaml."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_ids: str = ""
    telegram_admin_ids: str = ""

    # Database (defaults to SQLite — no server needed)
    database_url: str = "sqlite+aiosqlite:///snipe_token.db"
    database_sync_url: str = "sqlite:///snipe_token.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"  # ignored when use_fakeredis=True
    use_fakeredis: bool = True  # set to False to use a real Redis server

    # EVM RPCs
    eth_rpc_ws: str = ""
    eth_rpc_http: str = "https://eth-mainnet.g.alchemy.com/v2/demo"
    eth_rpc_ws_backup: str = ""

    base_rpc_ws: str = ""
    base_rpc_http: str = "https://mainnet.base.org"
    base_rpc_ws_backup: str = ""

    arb_rpc_ws: str = ""
    arb_rpc_http: str = "https://arb1.arbitrum.io/rpc"
    arb_rpc_ws_backup: str = ""

    bsc_rpc_ws: str = ""
    bsc_rpc_http: str = "https://bsc-dataseed1.binance.org"
    bsc_rpc_ws_backup: str = ""

    polygon_rpc_ws: str = ""
    polygon_rpc_http: str = "https://polygon-rpc.com"
    polygon_rpc_ws_backup: str = ""

    op_rpc_ws: str = ""
    op_rpc_http: str = "https://mainnet.optimism.io"
    op_rpc_ws_backup: str = ""

    avax_rpc_ws: str = ""
    avax_rpc_http: str = "https://api.avax.network/ext/bc/C/rpc"
    avax_rpc_ws_backup: str = ""

    # Solana
    solana_rpc_ws: str = ""
    solana_rpc_http: str = "https://api.mainnet-beta.solana.com"
    solana_rpc_ws_backup: str = ""

    # Priority 2 chains
    blast_rpc_ws: str = ""
    blast_rpc_http: str = "https://rpc.blast.io"
    linea_rpc_ws: str = ""
    linea_rpc_http: str = "https://rpc.linea.build"
    zksync_rpc_ws: str = ""
    zksync_rpc_http: str = "https://mainnet.era.zksync.io"
    scroll_rpc_ws: str = ""
    scroll_rpc_http: str = "https://rpc.scroll.io"

    # Tier 2 chains — public RPCs (override with premium RPCs via .env)
    fantom_rpc_ws: str = ""
    fantom_rpc_http: str = "https://rpc.ftm.tools"
    cronos_rpc_ws: str = ""
    cronos_rpc_http: str = "https://evm.cronos.org"
    celo_rpc_ws: str = ""
    celo_rpc_http: str = "https://forno.celo.org"
    gnosis_rpc_ws: str = ""
    gnosis_rpc_http: str = "https://rpc.gnosischain.com"
    mantle_rpc_ws: str = ""
    mantle_rpc_http: str = "https://rpc.mantle.xyz"
    mode_rpc_ws: str = ""
    mode_rpc_http: str = "https://mainnet.mode.network"
    core_rpc_ws: str = ""
    core_rpc_http: str = "https://rpc.coredao.org"
    metis_rpc_ws: str = ""
    metis_rpc_http: str = "https://andromeda.metis.io/?owner=1088"
    kava_rpc_ws: str = ""
    kava_rpc_http: str = "https://evm.kava.io"
    moonbeam_rpc_ws: str = ""
    moonbeam_rpc_http: str = "https://rpc.api.moonbeam.network"
    fuse_rpc_ws: str = ""
    fuse_rpc_http: str = "https://rpc.fuse.io"
    aurora_rpc_ws: str = ""
    aurora_rpc_http: str = "https://mainnet.aurora.dev"
    sei_rpc_ws: str = ""
    sei_rpc_http: str = "https://evm-rpc.sei-apis.com"
    taiko_rpc_ws: str = ""
    taiko_rpc_http: str = "https://rpc.mainnet.taiko.xyz"
    sonic_rpc_ws: str = ""
    sonic_rpc_http: str = "https://rpc.soniclabs.com"
    berachain_rpc_ws: str = ""
    berachain_rpc_http: str = "https://rpc.berachain.com"
    manta_rpc_ws: str = ""
    manta_rpc_http: str = "https://pacific-rpc.manta.network/http"
    fraxtal_rpc_ws: str = ""
    fraxtal_rpc_http: str = "https://rpc.frax.com"
    polygon_zkevm_rpc_ws: str = ""
    polygon_zkevm_rpc_http: str = "https://zkevm-rpc.com"
    klaytn_rpc_ws: str = ""
    klaytn_rpc_http: str = "https://public-en-cypress.klaytn.net"

    # Tier 3 chains
    moonriver_rpc_ws: str = ""
    moonriver_rpc_http: str = "https://rpc.api.moonriver.moonbeam.network"
    canto_rpc_ws: str = ""
    canto_rpc_http: str = "https://canto.gravitychain.io"
    evmos_rpc_ws: str = ""
    evmos_rpc_http: str = "https://evmos-evm.publicnode.com"
    conflux_rpc_ws: str = ""
    conflux_rpc_http: str = "https://evm.confluxrpc.com"
    xlayer_rpc_ws: str = ""
    xlayer_rpc_http: str = "https://rpc.xlayer.tech"
    zetachain_rpc_ws: str = ""
    zetachain_rpc_http: str = "https://zetachain-evm.blockpi.network/v1/rpc/public"
    merlin_rpc_ws: str = ""
    merlin_rpc_http: str = "https://rpc.merlinchain.io"
    bob_rpc_ws: str = ""
    bob_rpc_http: str = "https://rpc.gobob.xyz"
    cyber_rpc_ws: str = ""
    cyber_rpc_http: str = "https://cyber.alt.technology"
    degen_rpc_ws: str = ""
    degen_rpc_http: str = "https://rpc.degen.tips"
    gravity_rpc_ws: str = ""
    gravity_rpc_http: str = "https://rpc.gravity.xyz"
    viction_rpc_ws: str = ""
    viction_rpc_http: str = "https://rpc.viction.xyz"
    harmony_rpc_ws: str = ""
    harmony_rpc_http: str = "https://api.harmony.one"
    velas_rpc_ws: str = ""
    velas_rpc_http: str = "https://evmexplorer.velas.com/rpc"
    oasis_sapphire_rpc_ws: str = ""
    oasis_sapphire_rpc_http: str = "https://sapphire.oasis.io"
    neon_rpc_ws: str = ""
    neon_rpc_http: str = "https://neon-proxy-mainnet.solana.p2p.org"

    # Price APIs
    dexscreener_base_url: str = "https://api.dexscreener.com"
    coingecko_api_key: str = ""
    coingecko_base_url: str = "https://api.coingecko.com/api/v3"
    birdeye_api_key: str = ""
    defined_api_key: str = ""
    moralis_api_key: str = ""

    # Copy Trading
    copy_trading_live_enabled: bool = False
    copy_trading_wallet_private_key: str = ""
    copy_trading_wallet_address: str = ""
    copy_trading_max_trade_size_usd: float = 100.0
    copy_trading_max_daily_loss_usd: float = 500.0
    copy_trading_max_position_size_usd: float = 200.0
    copy_trading_default_copy_percent: float = 5.0
    copy_trading_max_slippage_bps: int = 300

    # Security
    api_secret_key: str = "changeme"
    encryption_key: str = ""

    # Application
    environment: str = "development"
    log_level: str = "INFO"
    debug: bool = False

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Monitoring
    prometheus_port: int = 9090
    enable_metrics: bool = True

    @property
    def allowed_chat_ids(self) -> list[int]:
        if not self.telegram_chat_ids:
            return []
        return [int(x.strip()) for x in self.telegram_chat_ids.split(",") if x.strip()]

    @property
    def admin_ids(self) -> list[int]:
        if not self.telegram_admin_ids:
            return []
        return [int(x.strip()) for x in self.telegram_admin_ids.split(",") if x.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_chain_config() -> dict[str, Any]:
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {}


@lru_cache
def get_chain_config() -> dict[str, Any]:
    return load_chain_config()
