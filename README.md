# Snipe Token — Smart Money Wallet Intelligence Bot

> Real-time multi-chain wallet tracker, Smart Money scorer, consensus detector, and Telegram alert bot with optional paper/live copy trading.

---

## Features

| Feature | Description |
|---|---|
| **Multi-chain tracking** | Ethereum, Base, Arbitrum, BSC, Polygon, Optimism, Avalanche, Solana (Phase 1) |
| **Real-time alerts** | Telegram buy/sell/position alerts with inline buttons |
| **Smart Money Score** | Composite 0-100 score (win rate, ROI, profit factor, drawdown, sample size) |
| **Consensus detection** | Alerts when ≥N smart wallets buy the same token within a time window |
| **Paper copy trading** | Simulate copying trades with no real transactions |
| **Live copy trading** | Optional, requires explicit opt-in — disabled by default |
| **Backtesting** | "What if I had copied this wallet?" analysis |
| **Risk engine** | GoPlus (EVM) + RugCheck (Solana) integration |
| **REST API** | FastAPI with endpoints for wallets, analytics, trades, positions |
| **Dashboard** | Next.js dark-theme UI with overview, wallet detail, positions, top trades |
| **Observability** | Prometheus metrics + structured JSON logging |

---

## Quick Start

### Prerequisites

- Docker + Docker Compose v2
- A Telegram bot token (create via [@BotFather](https://t.me/BotFather))
- RPC endpoints for the chains you want to track

### 1. Clone and configure

```bash
git clone <repo>
cd snipe-token
cp .env.example .env
```

Edit `.env` — at minimum set:

```env
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_IDS=your_chat_id_here
TELEGRAM_ADMIN_IDS=your_chat_id_here

# At least one RPC — use Alchemy/Infura/QuickNode free tiers
ETH_RPC_WS=wss://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
ETH_RPC_HTTP=https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY
```

### 2. Start everything

```bash
docker compose up -d
```

This starts: PostgreSQL → Redis → migrations → bot → API → dashboard.

| Service | URL |
|---|---|
| Telegram bot | (your chat) |
| REST API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Dashboard | http://localhost:3000 |
| Prometheus | http://localhost:9090/metrics |

### 3. Add your first wallet

Via Telegram:
```
/addwallet 0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045 ethereum Smart Money
```

Via API:
```bash
curl -X POST http://localhost:8000/wallets/ \
  -H "Content-Type: application/json" \
  -d '{"address":"0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045","chain_key":"ethereum","label":"Smart Money"}'
```

---

## Telegram Commands

| Command | Description |
|---|---|
| `/addwallet <address> <chain> [label]` | Track a new wallet |
| `/removewallet <address>` | Stop tracking a wallet |
| `/listwallets` | List all tracked wallets |
| `/wallet <address>` | Detailed stats + score breakdown |
| `/ranking [chain]` | Top wallets by Smart Money Score |
| `/positions [address]` | Open positions |
| `/toptrades` | Best trades by ROI |
| `/backtest <address> <period>` | Simulate copy trading (7d/30d/90d/365d) |
| `/settings` | View current configuration |
| `/health` | System health check |
| `/emergency` | **ADMIN** — Emergency stop live copy trading |

---

## Copy Trading

**Paper mode** (default) — simulates trades, never touches real funds:
```env
# No special config needed — paper mode is always available
```

**Live mode** — disabled by default, requires explicit opt-in:
```env
COPY_TRADING_LIVE_ENABLED=true
COPY_TRADING_WALLET_PRIVATE_KEY=your_private_key  # stored only in .env, never logged
COPY_TRADING_MAX_TRADE_SIZE_USD=100
COPY_TRADING_MAX_DAILY_LOSS_USD=500
```

> **Security**: The private key is read from `.env` at startup and is never logged, printed, sent to Telegram, or stored in the database. Live execution is a placeholder pending DEX SDK integration — see `src/copytrading/live_trader.py`.

---

## Architecture

```
Blockchain RPC
    │ WebSocket (newHeads/logsSubscribe)
    ▼
ChainAdapter (EVMAdapter / SolanaAdapter)
    │ RawTransaction
    ▼
TransactionEngine
    ├─ Deduplication (Redis SET NX)
    ├─ DEX parser (Uniswap V2/V3, Raydium, Orca …)
    ├─ TradeEngine (BUY/SELL/STABLE_SWAP/WRAP_UNWRAP)
    ├─ PositionEngine (Average Cost / FIFO)
    ├─ PriceEngine (DexScreener → Birdeye → CoinGecko)
    ├─ RiskEngine (GoPlus / RugCheck)
    └─ AlertCallback → TelegramBot
              │
              ▼
    ConsensusDetector (Redis sorted sets)
    BackgroundScheduler (unrealized PnL, metrics, scores)
    FastAPI REST API
    Next.js Dashboard
```

---

## Development

```bash
# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Run tests
pytest

# Start API only (no bot)
uvicorn api.main:app --reload

# Start everything (no Docker)
python main.py
```

---

## Directory Structure

```
snipe-token/
├── api/                  # FastAPI application
│   ├── main.py
│   └── routes/           # wallets, analytics, trades, tokens, copy_trading, backtest, health
├── config/
│   └── config.yaml       # Chain configs, DEX addresses, scoring weights
├── dashboard/            # Next.js 14 app router
│   └── app/              # page.tsx, wallets/, trades/, positions/
├── migrations/           # Alembic migrations
├── src/
│   ├── analytics/        # wallet_stats, smart_money_score, consensus, ranking, clustering
│   ├── backtesting/      # engine.py
│   ├── chains/           # base_adapter, evm/, solana/
│   ├── config.py         # Pydantic Settings
│   ├── copytrading/      # paper_trader, live_trader
│   ├── core/             # price_engine, trade_engine, position_engine, risk_engine, wallet_manager, transaction_engine
│   ├── database/         # models, connection, repositories
│   ├── monitoring/       # metrics (Prometheus + structlog)
│   ├── telegram/         # bot, alerts, commands, keyboards
│   └── workers/          # scheduler (background tasks)
├── tests/                # pytest unit tests
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── main.py               # Application entry point
└── requirements.txt
```

---

## Configuration Reference

See `.env.example` for a fully annotated list of all environment variables.

Key sections:
- `TELEGRAM_*` — Bot token and chat IDs
- `*_RPC_WS/HTTP` — Chain RPC endpoints (one per chain)
- `COPY_TRADING_*` — Copy trading limits and safety controls
- `COINGECKO_API_KEY`, `BIRDEYE_API_KEY` — Price feed keys

---

## Security

- Private keys are stored **only** in `.env` — never in the database, logs, or Telegram
- Live copy trading is **disabled by default** (`COPY_TRADING_LIVE_ENABLED=false`)
- Emergency stop via `/emergency` Telegram command (admin only)
- Risk checks run on every token before any copy trade executes
- Daily loss limit enforced in `LiveTrader`
