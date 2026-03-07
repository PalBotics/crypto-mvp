# Architecture

## System overview

crypto-mvp is a single-machine Python application that implements a
funding-rate capture paper-trading strategy against perpetual futures markets.
There is no real order execution.  All trades are simulated locally using the
last market tick as the fill price.

The system is deliberately narrow: one strategy, one exchange per run, one
account at a time.  The goal is to build a provably correct paper-trading loop
before any live capital is risked.

All persistence is PostgreSQL.  All configuration is environment variables
loaded from a `.env` file by Pydantic-Settings.  All logging is structured
JSON via structlog.

---

## Component map

```
┌─────────────────────────────────────────────────────────────────────┐
│  apps/                                                              │
│  ┌──────────────┐  ┌─────────────────────────────────────────────┐ │
│  │  collector/  │  │              paper_trader/                  │ │
│  │              │  │                                             │ │
│  │ MarketData   │  │ PaperTradingLoop                            │ │
│  │ Collector    │  │  ├─ FundingCaptureStrategy                  │ │
│  │              │  │  ├─ RiskEngine                              │ │
│  │ Polls ticks  │  │  ├─ AlertEvaluator                         │ │
│  │ + funding    │  │  └─ execute_one_paper_market_intent()       │ │
│  │ snapshots    │  │                                             │ │
│  └──────┬───────┘  └────────────────┬────────────────────────────┘ │
│         │                           │                               │
│  ┌──────▼───────────────────────────▼──────────────────────────┐   │
│  │  PostgreSQL (via SQLAlchemy)                                │   │
│  │                                                             │   │
│  │  market_ticks  funding_rate_snapshots  system_events        │   │
│  │  order_intents  order_records  fill_records                 │   │
│  │  position_snapshots  pnl_snapshots  funding_payments        │   │
│  │  strategy_signals  risk_events                              │   │
│  └──────────────────────────┬──────────────────────────────────┘   │
│                             │                                       │
│  ┌──────────────────────────▼──────────────────────────────────┐   │
│  │  dashboard/  (FastAPI — read-only HTTP)                     │   │
│  │  /health  /runs/{account}/summary  /positions  /pnl        │   │
│  │  /fills   /risk-events                                      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### apps/collector

Runs a polling loop at a configurable interval.  Each cycle:
1. Calls `adapter.fetch_ticker(symbol)` → normalized `MarketEvent`
2. Persists a `MarketTick` row.
3. Optionally calls `adapter.fetch_funding_rate(symbol)` → `FundingRateSnapshot`.

Supports three adapters: `mock` (deterministic, no network), `coinbase`
(spot ticks via public endpoints), `binance` (futures ticks + funding via
public endpoints).

### apps/paper_trader

`PaperTradingLoop` is the primary runtime.  It runs `N` iterations per
invocation.  Each iteration:

1. `FundingCaptureStrategy.evaluate()` — reads current position state, emits
   a `StrategySignal` and two `OrderIntent` rows if entry or exit is warranted.
2. `session.flush()` — makes the new intents visible to subsequent queries
   without committing.
3. Drain loop: calls `execute_one_paper_market_intent()` until no pending
   intents remain for this `mode`.
4. `accrue_funding_payment()` — computes and persists one `FundingPayment` for
   any open perp position.
5. `AlertEvaluator.evaluate()` — checks four conditions; logs warnings; creates
   a `RiskEvent` and flushes for critical alerts.
6. `session.commit()` — all iteration changes commit atomically.

### apps/execution_engine

Thin one-shot wrapper that calls `execute_one_paper_market_intent()` once.
Not used by `PaperTradingLoop` directly — `PaperTradingLoop` calls
`execute_one_paper_market_intent` in its own drain loop.

### apps/dashboard

FastAPI application.  HTTP layer only — all query logic lives in
`core/reporting/queries.py`.  Session is injected per-request via FastAPI
`Depends`.

### core/alerting

`AlertEvaluator` wraps four checks:
- `stale_funding_data` — latest `FundingRateSnapshot` is too old (warning)
- `position_pnl_drawdown` — net realized PnL + funding payments below threshold
  (critical; persists a `RiskEvent`)
- `open_position_no_recent_fill` — open position with no recent fill (warning)
- `no_funding_edge` — latest funding rate below minimum threshold (info)

### core/risk

`RiskEngine` runs four pre-trade hard checks in strict order.  The first
failure short-circuits and persists a `RiskEvent`:
1. Kill switch — unconditional block when `kill_switch_active=True`.
2. Stale funding data — blocks if `(now - latest_funding_ts) > max_data_age_seconds`.
3. Funding edge — blocks entry intents (`reduce_only=False`) when
   `funding_rate < min_entry_funding_rate`.
4. Max notional — blocks if `quantity × mark_price > max_notional_per_symbol`.

### core/paper

Domain functions that own no transactions:

| Module | Responsibility |
|--------|----------------|
| `simulator.py` | Simulates fill: market order filled at ask (buy) or bid (sell) |
| `fees.py` | `FixedBpsFeeModel` — taker fee as basis points of notional |
| `position_tracker.py` | Maintains `PositionSnapshot` via FIFO fill accounting |
| `pnl_calculator.py` | Creates `PnLSnapshot` from fill + updated position |
| `funding_accrual.py` | Computes and persists `FundingPayment` for open position |
| `execution_flow.py` | Orchestrates one intent → tick → risk → simulate → persist |
| `contracts_adapters.py` | Converts ORM objects to/from typed domain contracts |

### core/strategy

`FundingCaptureStrategy` — one strategy, fully implemented:
- Entry: `funding_rate ≥ entry_threshold` and no open position → spot buy +
  perp sell (both `reduce_only=False`)
- Exit: `funding_rate ≤ exit_threshold` and open position exists → spot sell +
  perp buy (both `reduce_only=True`)

### core/reporting

Five read-only aggregate query functions returning plain dataclasses.  These
are the only layer the dashboard consumes.

### core/exchange

`ExchangeAdapter` ABC with three concrete implementations selected by
`get_exchange_adapter(name)`:
- `MockExchangeAdapter` — deterministic; suitable for unit tests
- `CoinbaseAdapter` — public REST endpoints (spot only; no funding)
- `BinanceAdapter` — USD-M Futures public endpoints (ticks + funding)

---

## Data flow

```
FundingRateSnapshot
  (written by collector, read by RiskEngine + AlertEvaluator)
        │
        ▼
FundingCaptureStrategy.evaluate()
  → StrategySignal + OrderIntent rows (mode="paper")
        │
        ▼
execute_one_paper_market_intent()
  reads:  OrderIntent (pending, mode=X) + MarketTick (latest for symbol)
  checks: RiskEngine.check() → may write RiskEvent, set intent.status="rejected"
  if pass:
    PaperOrderSimulator.simulate() → fill price + fee
    fill_event_to_record()         → FillRecord
    order_record_from_intent()     → OrderRecord
    update_position_from_fill()    → PositionSnapshot (upsert)
    create_pnl_snapshot_from_fill() → PnLSnapshot
    intent.status = "filled"
        │
        ▼
accrue_funding_payment()
  reads:  latest PositionSnapshot (quantity > 0)
  writes: FundingPayment (payment_amount = -qty × mark_price × funding_rate)
        │
        ▼
AlertEvaluator.evaluate()
  reads:  FundingRateSnapshot, PnLSnapshot, FundingPayment,
          PositionSnapshot, FillRecord, OrderRecord, OrderIntent
  writes: RiskEvent (critical alerts only)
        │
        ▼
session.commit()
  All of the above persisted atomically per iteration.
```

---

## Key design decisions

### Decimal over float

All financial values use `decimal.Decimal`.  Floats accumulate rounding error
that compounds across thousands of iterations.  `Decimal` with explicit
precision eliminates the entire class of rounding drift bugs.  The cost is
slightly more verbose code; the benefit is exact arithmetic everywhere.

### Caller owns the transaction

No domain function (strategy, execution, risk, PnL, alerts) calls
`session.commit()`.  Domain functions may call `session.flush()` to make
pending writes visible to subsequent queries within the same transaction, but
the commit boundary is always owned by the outermost caller (`PaperTradingLoop`
in paper trading; tests in unit tests; FastAPI's session dependency in the
dashboard).

This means every iteration either fully commits or fully rolls back on error.
It also makes domain functions independently testable without needing
transaction management inside them.

### mode / account_name as run isolation

`OrderIntent.mode` is a string that tags every intent with the run context.
`PositionSnapshot.account_name`, `FundingPayment.account_name`, and all
reporting queries filter on this field.  The default is `"paper"`.

When replay is implemented, the run_id will be injected as `mode`, so all
records from that replay are isolated from the live paper run — the same DB
can hold multiple runs without interference.

### reduce_only as entry/exit discriminator

`OrderIntent.reduce_only=False` → opening intent (new position or add to
existing).  `reduce_only=True` → closing intent (reduce or close existing
position).

The risk engine uses this to gate the funding-edge check: it only blocks on
`funding_rate < min_entry_funding_rate` when `reduce_only=False`.  Exit intents
always pass the funding-edge check — you do not need a funding edge to exit.

### autoflush=False

All sessions are created with `autoflush=False`.  The paper trading loop calls
`session.flush()` explicitly after strategy evaluation so that new `OrderIntent`
rows are visible to the execution drain loop within the same transaction.
Without this explicit flush, pending intents would not appear in the query that
looks for pending intents.

---

## Deliberately deferred

| Capability | Reason for deferral |
|---|---|
| Live order execution | No paper-trading track record yet; Gate D not passed |
| Backtesting / replay | Requires historical data ingest and snapshot replay runner |
| Multi-exchange | Significant infra complexity; one exchange sufficient for MVP |
| Frontend / UI | Dashboard is JSON API; a UI is a separate project |
| Max daily loss, circuit breaker, emergency flatten | Deferred to risk engine completion sprint (Group B) |
| Signal aggregation | One strategy sufficient for initial validation |
| `apps/strategy_engine/main.py` | Strategy runs embedded in PaperTradingLoop; a standalone engine is future work |
