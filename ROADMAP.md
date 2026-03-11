# Roadmap

## Regulatory note

The platform has pivoted from funding-rate capture as the primary live
strategy to Kraken spot market making.  Funding-rate capture depends on
perpetual futures access that is not currently viable for US retail live
deployment.  The strategy remains fully supported in paper trading and replay
as a research track.

## Phase status

The project is structured into twelve phases (0–11).  Phases 0–6 are complete
core platform capabilities, Phase 7 is the live-strategy rollout pivot, and
Phases 8–11 cover refinement and expansion.

| Phase | Name | Status |
|---|---|---|
| 0 | Project framing | Complete |
| 1 | Core platform scaffold | Complete |
| 2 | Market data ingestion (Kraken REST) | Complete |
| 3 | Paper trading engine | Complete |
| 4 | Strategy 1: funding-rate capture (paper only) | Complete |
| 5 | Risk engine and controls | Complete |
| 6 | Observability and dashboard | Complete |
| 7 | Live rollout: Kraken spot market making (XBTUSD) | In progress |
| 8 | Market making strategy refinement | Planned |
| 9 | Strategy 2: funding-rate capture research | Planned |
| 10 | AI-assisted optimization | Planned |
| 11 | Multi-strategy platform | Planned |

---

### Phase 0 — Project framing — **Complete**

- Scope, architecture boundaries, risk policy, and staged delivery model defined.

### Phase 1 — Core platform scaffold — **Complete**

- SQLAlchemy/PostgreSQL data model, migrations, settings, logging, and service bootstrap.

### Phase 2 — Market data ingestion — **Complete**

- Kraken spot + futures REST collector implemented and production-shaped.
- 24-hour soak test completed.

### Phase 3 — Paper trading engine — **Complete**

- Paper execution flow, position/PnL accounting, and funding accrual integrated.

### Phase 4 — Strategy 1 funding-rate capture — **Complete (paper only)**

- Funding-capture strategy, signal generation, and replay-compatible execution path completed.
- Live deployment is blocked for US residents; this strategy remains research-only in paper/replay.

### Phase 5 — Risk engine and controls — **Complete**

- Pre-trade hard controls, kill-switch pathways, and risk event persistence implemented.

### Phase 6 — Observability and dashboard — **Complete**

- Alert evaluation, reporting queries, and dashboard API endpoints implemented.

### Phase 7 — Live rollout: simple spot market making on Kraken spot — **Next**

Primary live strategy target:
- Instrument: `XBTUSD`
- Exchange: Kraken spot (US-accessible)
- Method: quote around mid-price, enforce inventory bounds, capture spread

Rollout steps:
1. Read-only live market connectivity — **Complete** (collector already running on Kraken spot mainnet)
2. Live signal generation, no orders
3. Live order placement with tiny size (`$1000` initial allocation, fully prepared to lose)
4. One strategy, one market, one exchange
5. Manual daily review

### Phase 8 — Market making strategy refinement — **Planned**

- Better spread calibration
- Smarter inventory management
- Order book depth awareness
- Quote freshness and cancel/replace tuning

## Feature Backlog: Multi-Asset Support

**Requested:** 2026-03-11
**Status:** Backlog — do not start until Phase 8 exit
criteria are met

**Goal**
Extend the platform to track and trade cryptocurrencies
beyond XBTUSD (Bitcoin). Each new asset runs the same
market-making strategy independently with its own
position, PnL tracking, and quotes.

**Guiding rule (from project scope)**
Only add one new axis of complexity at a time. Multi-
asset work begins only after the single-asset strategy
has proven a persistent edge with realistic fee and
slippage assumptions.

**What needs to change when ready**

Backend:
- Collector: add symbol list to config, collect ticks
	and order book snapshots per symbol
- Strategy: symbol passed as config parameter, already
	supported in MarketMakingConfig
- Paper trader: run one strategy instance per symbol,
	independent position and PnL per symbol
- Database: all tables already keyed by symbol — no
	schema changes required
- API: add symbol filter parameter to all endpoints
	that return market or position data

Dashboard:
- Symbol selector in header or sidebar to switch active
	symbol view
- All panels filter by selected symbol
- Overview shows aggregate account value across all
	symbols
- Market Range chart switches to selected symbol data

**Candidate symbols to add first**
- ETHUSD (Ethereum) — highest liquidity after BTC
- SOLUSD (Solana) — high volatility, good for MM
- Any symbol available on Kraken spot with sufficient
	order book depth

**Exit criteria before starting**
- Phase 8 complete: strategy edge proven out of sample
- Single-asset system stable for 30+ days live
- No open risk or observability gaps

### Phase 9 — Strategy 2: funding-rate capture research — **Planned**

- Continue as paper-trading/replay research.
- Revisit live execution only if regulatory access changes or a compliant venue is available.

### Phase 10 — AI-assisted optimization — **Planned**

- AI-assisted parameter search, scenario generation, and guardrailed tuning workflows.

### Phase 11 — Multi-strategy platform — **Planned**

- Multi-strategy orchestration, shared risk budget, and portfolio-level controls.

---

## Current sprint plan

- Sprint A: Extend collector to capture order book snapshots.
- Sprint B: Build `MarketMakingStrategy` with configurable spread and inventory bounds.
- Sprint C: Wire strategy into the paper trading loop and validate with replay.
- Sprint D: Update KPIs and alerting for market-making metrics.
- Sprint E: Limited live deployment on Kraken spot.
