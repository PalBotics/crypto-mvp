# crypto-mvp

Modular crypto automation platform MVP implementing a funding-rate capture
strategy with paper trading, a read-only dashboard API, and a pre-trade risk
engine.  No real capital is used.  Live order execution is explicitly deferred.

## What the system does

- **Collects** live market ticks and perpetual funding-rate snapshots from
  Coinbase (spot), Binance (futures), or a deterministic mock adapter.
- **Papers trades** a delta-neutral funding-capture pair (spot long + perp
  short) governed by configurable funding-rate thresholds.
- **Enforces** four hard pre-trade risk checks (kill switch, stale data,
  funding edge, max notional) and logs every block as a `RiskEvent`.
- **Accrues** funding payments each iteration for any open perpetual position.
- **Evaluates** four post-iteration alert conditions (stale data, PnL
  drawdown, no-fill, low funding edge) and logs critical ones as `RiskEvent`
  rows before the iteration commits.
- **Exposes** a read-only FastAPI dashboard over HTTP with six endpoints.
- **Never** places a real order on any exchange.

## What is not yet built

- Live order execution (no real exchange API calls)
- Backtesting and replay against historical data (`apps/backtester/` stub only)
- Frontend / UI (dashboard is JSON API only)
- Multi-exchange simultaneous runs
- Max daily loss limit, circuit breaker, emergency-flatten, hedge-leg mismatch
  detection (see `RISK_POLICY.md`)
- Signal aggregation across multiple strategies
- `apps/strategy_engine/` (stub only — strategy runs inside `PaperTradingLoop`)

## Repository structure

```
crypto-mvp/
├── apps/
│   ├── collector/       # Market data collector — ticks + funding snapshots
│   ├── paper_trader/    # PaperTradingLoop orchestrator (strategy + risk + alerts)
│   ├── execution_engine/# Thin wrapper for one-shot paper intent execution
│   ├── dashboard/       # FastAPI read-only HTTP API (6 endpoints)
│   ├── strategy_engine/ # Stub — empty
│   └── backtester/      # Stub — empty
├── core/
│   ├── alerting/        # AlertEvaluator — 4 post-iteration alert conditions
│   ├── app/             # bootstrap_app() — settings + logging + DB check
│   ├── config/          # Pydantic-settings, .env loading
│   ├── db/              # SQLAlchemy engine, session factory
│   ├── domain/          # Typed contracts (MarketEvent, FillEvent) + normalizers
│   ├── exchange/        # ExchangeAdapter ABC + mock / Coinbase / Binance impls
│   ├── models/          # SQLAlchemy ORM models (11 tables)
│   ├── paper/           # Paper trading domain: simulator, position, PnL, fees,
│   │                    #   funding accrual, execution flow, contract adapters
│   ├── reporting/       # Read-only query functions (5 functions, 6 row types)
│   ├── risk/            # RiskEngine — 4 pre-trade hard checks
│   ├── strategy/        # FundingCaptureStrategy
│   └── utils/           # Logging, time helpers, UUID generation
├── migrations/          # Alembic migration scripts
│   └── versions/        # 2 chained migration files
├── tests/
│   ├── unit/            # 164 unit tests (pytest, SQLite in-memory)
│   └── integration/     # Integration tests (Coinbase live, DB connection)
├── alembic.ini
├── docker-compose.yml   # PostgreSQL 16 on port 5432
└── pyproject.toml
```

## Environment setup

### Prerequisites

- Python 3.12+
- Docker (for PostgreSQL)

### Steps

```powershell
# 1. Clone
git clone https://github.com/palbotics/crypto-mvp.git
cd crypto-mvp

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate         # Linux / macOS

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Start PostgreSQL
docker compose up -d

# 5. Create a .env file (all fields have defaults; override as needed)
# Minimum viable .env for local development:
```

```ini
# .env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=crypto_mvp
DB_USER=postgres
DB_PASSWORD=postgres

COLLECT_INTERVAL_SECONDS=60
COLLECT_SPOT_EXCHANGE=kraken
COLLECT_PERP_EXCHANGE=kraken_futures
COLLECT_SPOT_SYMBOL=XBTUSD
COLLECT_PERP_SYMBOL=XBTUSD
COLLECT_SPOT_EXCHANGE_SYMBOL=XXBTZUSD
COLLECT_PERP_EXCHANGE_SYMBOL=PF_XBTUSD
COLLECT_ADAPTER_NAME=kraken_rest
COLLECT_SPOT_BASE_URL=https://api.kraken.com
COLLECT_FUTURES_BASE_URL=https://futures.kraken.com
COLLECT_REQUEST_TIMEOUT_SECONDS=10
```

```powershell
# 6. Apply database migrations
alembic upgrade head
```

> **Note:** `.env.example` is included in the repo and is the source of truth
> for supported environment variables.

## Running the market data collector

```powershell
# Kraken spot + futures REST polling
python -m apps.collector.main

# Optional override example (PowerShell) for a different symbol pair
$env:COLLECT_SPOT_SYMBOL="ETHUSD"
$env:COLLECT_SPOT_EXCHANGE_SYMBOL="XETHZUSD"
$env:COLLECT_PERP_SYMBOL="ETHUSD"
$env:COLLECT_PERP_EXCHANGE_SYMBOL="PF_ETHUSD"
python -m apps.collector.main
```

## Running the paper trading loop

The paper trading loop runs `N` iterations of: evaluate strategy → execute
pending intents → accrue funding → evaluate alerts → commit.

```powershell
python -m apps.paper_trader.main
```

The loop is configured inline in `apps/paper_trader/main.py`:
- `spot_symbol`, `perp_symbol`, `exchange`
- `entry_funding_rate_threshold`, `exit_funding_rate_threshold`
- `position_size`
- `iterations` (default: 1 — one iteration per invocation)

Before running, the database must have at least one `MarketTick` row for the
configured symbol (the paper simulator uses the last tick as fill price).

## Running a replay

Replay is not yet implemented.  `apps/backtester/main.py` is an empty stub.
The domain layer is designed to support it via the `mode` parameter (which
doubles as `account_name` / `run_id`), but no replay runner exists.

## Starting the dashboard API

```powershell
uvicorn apps.dashboard.main:app --reload
```

Packaging note: PyWebView was the original planned desktop packaging approach,
but it is not compatible with Python 3.14 in this project environment. The
dashboard desktop shell is packaged with Qt WebEngine (`QWebEngineView`) via
PySide6/PyQt6, which provides an equivalent native window experience.

Available endpoints (all read-only, all return JSON):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| GET | `/runs/{account_name}/summary` | Aggregated run summary |
| GET | `/runs/{account_name}/positions` | Open positions |
| GET | `/runs/{account_name}/pnl` | PnL summary |
| GET | `/runs/{account_name}/fills` | Recent fills (default 20, max 100) |
| GET | `/runs/{account_name}/risk-events` | Risk events (default 50, max 200) |

`account_name` matches the `mode` field used when creating `OrderIntent` rows
(e.g., `"paper"` for the default paper trading run).

Interactive docs: `http://localhost:8000/docs`

## Running the test suite

```powershell
# All tests (164 unit tests as of Sprint 15)
.venv\Scripts\python.exe -m pytest tests/unit/ -v

# With coverage
.venv\Scripts\python.exe -m pytest tests/unit/ --cov=core --cov=apps

# Integration tests (require PostgreSQL and optional live network)
.venv\Scripts\python.exe -m pytest tests/integration/ -v
```

Unit tests use an in-memory SQLite database and do not require PostgreSQL.
Integration tests require a running PostgreSQL instance.

## Development tools

```powershell
# Lint
ruff check .

# Type check
mypy core/ apps/

# Format check
ruff format --check .
```

## License

MIT