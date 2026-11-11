"""Auto-detect which EVM chains a wallet address is active on.

Calls eth_getTransactionCount on public RPCs concurrently.
No API keys required — uses free public endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# chain_key → (chain_id, public_rpc_url, explorer_url)
CHAIN_RPC_MAP: dict[str, tuple[int, str, str]] = {
    "ethereum":      (1,           "https://eth.llamarpc.com",                              "https://etherscan.io"),
    "bsc":           (56,          "https://bsc-dataseed.binance.org",                      "https://bscscan.com"),
    "polygon":       (137,         "https://polygon-rpc.com",                               "https://polygonscan.com"),
    "arbitrum":      (42161,       "https://arb1.arbitrum.io/rpc",                          "https://arbiscan.io"),
    "optimism":      (10,          "https://mainnet.optimism.io",                           "https://optimistic.etherscan.io"),
    "base":          (8453,        "https://mainnet.base.org",                              "https://basescan.org"),
    "avalanche":     (43114,       "https://api.avax.network/ext/bc/C/rpc",                 "https://snowscan.xyz"),
    "fantom":        (250,         "https://rpc.ftm.tools",                                 "https://ftmscan.com"),
    "cronos":        (25,          "https://evm.cronos.org",                                "https://cronoscan.com"),
    "zksync":        (324,         "https://mainnet.era.zksync.io",                         "https://explorer.zksync.io"),
    "linea":         (59144,       "https://rpc.linea.build",                               "https://lineascan.build"),
    "scroll":        (534352,      "https://rpc.scroll.io",                                 "https://scrollscan.com"),
    "blast":         (81457,       "https://rpc.blast.io",                                  "https://blastscan.io"),
    "mantle":        (5000,        "https://rpc.mantle.xyz",                                "https://mantlescan.xyz"),
    "mode":          (34443,       "https://mainnet.mode.network",                          "https://explorer.mode.network"),
    "manta":         (169,         "https://pacific-rpc.manta.network/http",               "https://pacific-explorer.manta.network"),
    "celo":          (42220,       "https://forno.celo.org",                               "https://celoscan.io"),
    "metis":         (1088,        "https://andromeda.metis.io/?owner=1088",               "https://andromeda-explorer.metis.io"),
    "moonbeam":      (1284,        "https://rpc.api.moonbeam.network",                      "https://moonscan.io"),
    "moonriver":     (1285,        "https://rpc.api.moonriver.moonbeam.network",           "https://moonriver.moonscan.io"),
    "fuse":          (122,         "https://rpc.fuse.io",                                   "https://explorer.fuse.io"),
    "gnosis":        (100,         "https://rpc.gnosischain.com",                           "https://gnosisscan.io"),
    "aurora":        (1313161554,  "https://mainnet.aurora.dev",                            "https://explorer.aurora.dev"),
    "kava":          (2222,        "https://evm.kava.io",                                   "https://kavascan.com"),
    "core":          (1116,        "https://rpc.coredao.org",                               "https://scan.coredao.org"),
    "sei":           (1329,        "https://evm-rpc.sei-apis.com",                          "https://seitrace.com"),
    "polygon_zkevm": (1101,        "https://zkevm-rpc.com",                                "https://zkevm.polygonscan.com"),
    "taiko":         (167000,      "https://rpc.mainnet.taiko.xyz",                         "https://taikoscan.io"),
    "fraxtal":       (252,         "https://rpc.frax.com",                                  "https://fraxscan.com"),
    "klaytn":        (8217,        "https://public-en-cypress.klaytn.net",                  "https://klaytnscope.com"),
    "pulsechain":    (369,         "https://rpc.pulsechain.com",                            "https://scan.pulsechain.com"),
    "sonic":         (146,         "https://rpc.soniclabs.com",                             "https://sonicscan.org"),
    "berachain":     (80094,       "https://rpc.berachain.com",                             "https://berascan.com"),
    "worldchain":    (480,         "https://worldchain-mainnet.g.alchemy.com/public",       "https://worldchain-mainnet.explorer.alchemy.com"),
    "boba":          (288,         "https://mainnet.boba.network",                          "https://bobascan.com"),
    "iotex":         (4689,        "https://babel-api.mainnet.iotex.io",                   "https://iotexscan.io"),
    "telos":         (40,          "https://mainnet.telos.net/evm",                         "https://teloscan.io"),
    "oasis":         (42262,       "https://emerald.oasis.dev",                             "https://explorer.emerald.oasis.dev"),
    "okc":           (66,          "https://exchainrpc.okex.org",                           "https://www.oklink.com/okc"),
    "kcc":           (321,         "https://rpc-mainnet.kcc.network",                       "https://explorer.kcc.io"),
    "heco":          (128,         "https://http-mainnet.hecochain.com",                   "https://hecoinfo.com"),
    # Tier 3 — extended coverage
    "moonriver":     (1285,        "https://rpc.api.moonriver.moonbeam.network",            "https://moonriver.moonscan.io"),
    "canto":         (7700,        "https://canto.gravitychain.io",                         "https://evm.explorer.canto.io"),
    "evmos":         (9001,        "https://evmos-evm.publicnode.com",                      "https://escan.live"),
    "conflux":       (1030,        "https://evm.confluxrpc.com",                            "https://evm.confluxscan.io"),
    "xlayer":        (196,         "https://rpc.xlayer.tech",                               "https://www.oklink.com/xlayer"),
    "zetachain":     (7000,        "https://zetachain-evm.blockpi.network/v1/rpc/public",   "https://explorer.zetachain.com"),
    "merlin":        (4200,        "https://rpc.merlinchain.io",                            "https://scan.merlinchain.io"),
    "bob":           (60808,       "https://rpc.gobob.xyz",                                 "https://explorer.gobob.xyz"),
    "cyber":         (7560,        "https://cyber.alt.technology",                          "https://cyberscan.co"),
    "degen":         (666666666,   "https://rpc.degen.tips",                               "https://explorer.degen.tips"),
    "gravity":       (1625,        "https://rpc.gravity.xyz",                               "https://explorer.gravity.xyz"),
    "viction":       (88,          "https://rpc.viction.xyz",                               "https://vicscan.xyz"),
    "harmony":       (1666600000,  "https://api.harmony.one",                               "https://explorer.harmony.one"),
    "velas":         (106,         "https://evmexplorer.velas.com/rpc",                     "https://evmexplorer.velas.com"),
    "oasis_sapphire":(23294,       "https://sapphire.oasis.io",                             "https://explorer.oasis.io/mainnet/sapphire"),
    "neon":          (245022934,   "https://neon-proxy-mainnet.solana.p2p.org",             "https://neonscan.org"),
}

# Chains considered highest priority (fastest to check first)
PRIORITY_CHAINS = [
    "ethereum", "bsc", "base", "arbitrum", "polygon", "optimism",
    "avalanche", "fantom", "cronos", "zksync", "linea", "blast",
]


async def _check_tx_count(
    session: aiohttp.ClientSession,
    chain_key: str,
    rpc_url: str,
    address: str,
    timeout: float,
) -> Optional[str]:
    """Returns chain_key if address has transactions on this chain, else None."""
    payload = {
        "jsonrpc": "2.0",
        "method": "eth_getTransactionCount",
        "params": [address, "latest"],
        "id": 1,
    }
    try:
        async with session.post(
            rpc_url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status == 200:
                data = await resp.json(content_type=None)
                result = data.get("result", "0x0")
                count = int(result, 16) if isinstance(result, str) and result.startswith("0x") else 0
                if count > 0:
                    return chain_key
    except Exception as exc:
        logger.debug("Chain %s check failed: %s", chain_key, exc)
    return None


async def detect_active_chains(
    address: str,
    timeout: float = 4.0,
    max_concurrent: int = 15,
    priority_only: bool = False,
) -> list[str]:
    """
    For a given EVM address, return list of chain_keys where tx_count > 0.
    Runs all RPC checks concurrently (max_concurrent at a time).

    Args:
        address: EVM hex address (0x...)
        timeout: Per-RPC timeout in seconds
        max_concurrent: Max concurrent RPC calls
        priority_only: If True, only check PRIORITY_CHAINS (faster, 12 chains)
    """
    if not address or not address.startswith("0x") or len(address) != 42:
        return []

    sem = asyncio.Semaphore(max_concurrent)
    chains_to_check = {
        k: v for k, v in CHAIN_RPC_MAP.items()
        if not priority_only or k in PRIORITY_CHAINS
    }

    async def _bounded(chain_key: str, rpc_url: str) -> Optional[str]:
        async with sem:
            return await _check_tx_count(session, chain_key, rpc_url, address, timeout)

    results: list[str] = []
    async with aiohttp.ClientSession() as session:
        tasks = [
            _bounded(chain_key, rpc_url)
            for chain_key, (_, rpc_url, _) in chains_to_check.items()
        ]
        done = await asyncio.gather(*tasks, return_exceptions=True)
        for r in done:
            if isinstance(r, str):
                results.append(r)

    # Sort: priority chains first, then alphabetical
    priority_set = set(PRIORITY_CHAINS)
    results.sort(key=lambda k: (0 if k in priority_set else 1, k))
    return results


def get_chain_explorer(chain_key: str) -> str:
    """Return the explorer base URL for a chain."""
    entry = CHAIN_RPC_MAP.get(chain_key)
    return entry[2] if entry else "https://etherscan.io"


def get_dexscreener_chain_slug(chain_key: str) -> str:
    """Map internal chain_key to DexScreener chain slug."""
    _map = {
        "ethereum":      "ethereum",
        "bsc":           "bsc",
        "polygon":       "polygon",
        "arbitrum":      "arbitrum",
        "optimism":      "optimism",
        "base":          "base",
        "avalanche":     "avalanche",
        "fantom":        "fantom",
        "cronos":        "cronos",
        "zksync":        "zksync",
        "linea":         "linea",
        "scroll":        "scroll",
        "blast":         "blast",
        "mantle":        "mantle",
        "mode":          "mode",
        "manta":         "manta",
        "celo":          "celo",
        "metis":         "metis",
        "moonbeam":      "moonbeam",
        "moonriver":     "moonriver",
        "fuse":          "fuse",
        "gnosis":        "gnosischain",
        "aurora":        "aurora",
        "kava":          "kava",
        "core":          "core",
        "sei":           "sei",
        "polygon_zkevm": "polygonzkevm",
        "taiko":         "taiko",
        "fraxtal":       "fraxtal",
        "klaytn":        "klaytn",
        "pulsechain":    "pulsechain",
        "sonic":         "sonic",
        "berachain":     "berachain",
        "worldchain":    "worldchain",
        "boba":          "boba",
        "iotex":         "iotex",
        "telos":         "telos",
        "okc":           "okc",
        "kcc":           "kcc",
        "heco":          "heco",
        "moonriver":     "moonriver",
        "canto":         "canto",
        "evmos":         "evmos",
        "conflux":       "conflux",
        "xlayer":        "xlayer",
        "zetachain":     "zetachain",
        "merlin":        "merlin",
        "bob":           "bob",
        "cyber":         "cyber",
        "degen":         "degen",
        "gravity":       "gravity",
        "viction":       "tomochain",
        "harmony":       "harmony",
        "velas":         "velas",
        "oasis_sapphire":"oasis",
        "neon":          "neon",
    }
    return _map.get(chain_key, chain_key)
