# crypto-mvp

Modular crypto automation platform MVP.

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 16
- Docker (for local PostgreSQL)

### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/palbotics/crypto-mvp.git
   cd crypto-mvp
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1  # Windows
   source .venv/bin/activate    # Linux/Mac
   ```

3. **Install dependencies**
   ```bash
   pip install -e .
   pip install -e ".[dev]"  # Include dev dependencies
   ```

4. **Start PostgreSQL**
   ```bash
   docker compose up -d
   ```

5. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env as needed
   ```

6. **Run migrations**
   ```bash
   alembic upgrade head
   ```

### Running the Collector

The market data collector supports multiple exchange adapters.

#### Mock Adapter (Testing)

```bash
# .env configuration
COLLECT_EXCHANGE=mock
COLLECT_SYMBOL=BTC-USD
COLLECT_INTERVAL_SECONDS=5

# Run collector
python -m apps.collector.main
```

#### Coinbase Adapter (Live Data)

Sprint 2 implementation includes Coinbase Advanced Trade API support using public endpoints.

```bash
# .env configuration
COLLECT_EXCHANGE=coinbase
COLLECT_SYMBOL=BTC-USD
COLLECT_INTERVAL_SECONDS=5

# Run collector
python -m apps.collector.main
```

**Supported Coinbase symbols:** BTC-USD, ETH-USD, SOL-USD, etc. (any valid Coinbase product ID)

**Note:** Coinbase public endpoints have rate limits (~10 req/sec). The default 5-second interval is well within limits.

**No API keys required** for market data collection (public endpoints only).

#### Binance Adapter (Funding + Market Data)

Sprint 3 adds Binance USD-M Futures adapter support, including funding-rate
collection through public endpoints.

```bash
# .env configuration
COLLECT_EXCHANGE=binance
COLLECT_SYMBOL=BTCUSDT
COLLECT_INTERVAL_SECONDS=5

# Optional funding collection
COLLECT_FUNDING=true
COLLECT_FUNDING_SYMBOL=BTCUSDT

# Run collector
python -m apps.collector.main
```

### Optional Funding Collection

Funding persistence is optional and disabled by default.

- `COLLECT_FUNDING=false` (default): collect/persist `market_ticks` only
- `COLLECT_FUNDING=true`: additionally attempt funding collection each cycle
- `COLLECT_FUNDING_SYMBOL`: derivatives symbol used for funding endpoint calls

Current behavior by adapter:

- `coinbase`: `fetch_funding_rate` returns `None` in current spot flow
- `mock`: `fetch_funding_rate` returns `None`
- `binance`: returns normalized funding payload when available

### Testing

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/ -v

# Run with coverage
pytest --cov=core --cov=apps
```

### Development

```bash
# Lint code
ruff check .

# Type check
mypy core/ apps/

# Format check
ruff format --check .
```

## Project Structure

```
crypto-mvp/
├── apps/               # Service entrypoints
│   ├── collector/      # Market data collector
│   ├── strategy_engine/
│   ├── execution_engine/
│   ├── backtester/
│   └── dashboard/
├── core/               # Shared core functionality
│   ├── config/         # Settings and configuration
│   ├── db/             # Database session management
│   ├── exchange/       # Exchange adapter interfaces
│   ├── models/         # SQLAlchemy ORM models
│   ├── risk/           # Risk management
│   └── utils/          # Utilities
├── migrations/         # Alembic database migrations
└── tests/              # Test suite
```

## Smoke Testing Coinbase Integration

To validate the Coinbase adapter with live data:

1. **Ensure database is running:**
   ```bash
   docker compose up -d
   ```

2. **Update `.env`:**
   ```
   COLLECT_EXCHANGE=coinbase
   COLLECT_SYMBOL=BTC-USD
   COLLECT_INTERVAL_SECONDS=5
   ```

3. **Run collector for 30-60 seconds:**
   ```bash
   python -m apps.collector.main
   # Press Ctrl+C to stop
   ```

4. **Verify data in PostgreSQL:**
   ```bash
   docker exec -it crypto-mvp-postgres psql -U postgres -d crypto_mvp
   ```
   ```sql
   SELECT 
     exchange, 
     symbol, 
     bid_price, 
     ask_price, 
     event_ts 
   FROM market_ticks 
   WHERE exchange = 'coinbase' 
   ORDER BY event_ts DESC 
   LIMIT 10;
   ```

**Expected behavior:**
- Collector logs show `exchange=coinbase`
- New rows appear in `market_ticks` table every 5 seconds
- `bid_price`, `ask_price`, `last_price` contain realistic BTC prices
- No errors or connection issues

**Troubleshooting:**
- If you see connection errors, check your internet connection
- If you see rate limit errors (HTTP 429), increase `COLLECT_INTERVAL_SECONDS`
- Logs are structured JSON in production, readable console output in development

## License

MIT