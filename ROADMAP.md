# Roadmap

## Phase status

The project is structured into twelve phases (0–11).  Phases 0–8 map to the
paper-trading build-out.  Phases 9–11 cover live trading and are gated by
Gate D (see `RISK_POLICY.md`).

| Phase | Name | Status |
|---|---|---|
| 0 | Infrastructure & data models | Complete |
| 1 | Market data collection | Complete |
| 2 | Exchange adapters | Partially complete |
| 3 | Paper trade simulation | Complete |
| 4 | Strategy & signal generation | Partially complete |
| 5 | Risk engine | Partially complete |
| 6 | Alerting & monitoring | Complete |
| 7 | Dashboard & reporting API | Complete |
| 8 | Backtesting & replay | Not started |
| 9 | Live execution integration | Not started |
| 10 | Multi-strategy / multi-exchange | Not started |
| 11 | Production hardening | Not started |

---

### Phase 0 — Infrastructure & data models — **Complete**

- PostgreSQL + SQLAlchemy 2.x ORM
- 11 database models (market_ticks, funding_rate_snapshots, system_events,
  order_intents, order_records, fill_records, position_snapshots, pnl_snapshots,
  funding_payments, strategy_signals, risk_events)
- 2 Alembic migration files covering 10 of 11 tables
- Pydantic-Settings configuration + `.env` loading
- structlog structured logging
- `bootstrap_app()` startup helper
- Docker Compose for local PostgreSQL

**Known gap (fixed in Sprint 15 audit):** `funding_payments` was missing from
both original Alembic migrations.  Migration `386b20f64042` was generated and
applied during the Sprint 15 audit sprint.  `alembic upgrade head` on a fresh
database now creates all 11 tables.

---

### Phase 1 — Market data collection — **Complete**

- `MarketDataCollector` polling loop with configurable interval
- `MarketTick` persistence from normalized `MarketEvent` contract
- Optional `FundingRateSnapshot` persistence
- `ExchangeAdapter` ABC defining the adapter contract

---

### Phase 2 — Exchange adapters — **Partially complete**

**Complete:**
- `MockExchangeAdapter` — deterministic, no network required
- `CoinbaseAdapter` — public REST endpoints, spot ticks only
- `BinanceAdapter` — USD-M Futures public endpoints, ticks + funding rates

**Missing:**
- Authenticated Coinbase Advanced Trade adapter for live order placement
- Authenticated Binance Futures adapter for live order placement
- Adapter health-check / reconnect logic
- Rate-limit handling beyond the polling interval

---

### Phase 3 — Paper trade simulation — **Complete**

- `PaperOrderSimulator` — market orders filled at ask (buy) or bid (sell)
- `FixedBpsFeeModel` — fixed taker fee as basis points of notional
- `update_position_from_fill()` — FIFO position accounting
- `create_pnl_snapshot_from_fill()` — PnL accounting from fill + position delta
- `accrue_funding_payment()` — per-iteration funding accrual
- `execute_one_paper_market_intent()` — end-to-end intent → fill pipeline
- `PaperTradingLoop` — per-iteration orchestrator (strategy → execute → fund → alert → commit)

---

### Phase 4 — Strategy & signal generation — **Partially complete**

**Complete:**
- `FundingCaptureStrategy` — delta-neutral spot long + perp short
  - Entry: `funding_rate ≥ entry_threshold`, no open position
  - Exit: `funding_rate ≤ exit_threshold`, open position exists
- `StrategySignal` persistence with `decision_json`
- `FundingCaptureConfig` with configurable thresholds and position size

**Missing:**
- KPI metrics (Sharpe ratio, max drawdown, funding income vs fee drag)
- Stress tests against synthetic adverse rate scenarios
- Walk-forward parameter validation

---

### Phase 5 — Risk engine — **Partially complete**

**Complete (hard controls in `RiskEngine`):**
- Kill switch (`kill_switch_active`)
- Stale data block (`max_data_age_seconds`)
- Funding edge block for entry intents (`min_entry_funding_rate`)
- Max notional per symbol (`max_notional_per_symbol`)

**Missing (required before Gate D):**
- Max daily loss limit with automatic kill switch activation
- Circuit breaker (block count threshold within rolling window)
- Emergency flatten (auto-close stuck open positions)
- Hedge leg mismatch detection (spot qty ≠ perp qty within tolerance)

---

### Phase 6 — Alerting & monitoring — **Complete**

- `AlertEvaluator` with 4 conditions evaluated post-iteration:
  - `stale_funding_data` (warning)
  - `position_pnl_drawdown` (critical + RiskEvent persisted)
  - `open_position_no_recent_fill` (warning)
  - `no_funding_edge` (info)
- Configurable thresholds via `AlertConfig`
- Wired into `PaperTradingLoop` as optional dependency

---

### Phase 7 — Dashboard & reporting API — **Complete**

- `core/reporting/queries.py` — 5 read-only query functions
- FastAPI app (`apps/dashboard/`) with 6 endpoints
- Pydantic v2 response schemas
- Session injection via FastAPI `Depends`

---

### Phase 8 — Backtesting & replay — **Not started**

- `apps/backtester/main.py` is an empty stub
- Domain layer is replay-ready (`mode` / `account_name` used as `run_id`)
- `PaperOrderSimulator` rejects `mode != "paper"` — must be relaxed for replay

**What is needed:**
- Historical data loader (or snapshot export from collector)
- Replay runner that injects historical ticks as market data
- Isolation: each replay run tagged with a unique `run_id` as `mode`
- Comparison tooling: replay results vs paper results for the same period

---

### Phases 9–11 — Live trading / multi-strategy / production — **Not started**

Gated by Gate D.  Not planned until paper trading passes the 30-day stability
requirement and all Phase 5 gaps are closed.

---

## Sprint history summary

| Sprint | Added |
|---|---|
| 1 | Project skeleton, `pyproject.toml`, Docker Compose, DB session, bootstrap |
| 2 | `MarketDataCollector`, `MockExchangeAdapter`, `CoinbaseAdapter`, first Alembic migration |
| 3 | `BinanceAdapter`, funding-rate collection, `FundingRateSnapshot` model |
| 4 | `PaperOrderSimulator` (market orders), `FixedBpsFeeModel`, domain contracts |
| 5 | `update_position_from_fill()`, `create_pnl_snapshot_from_fill()` |
| 6 | `execute_one_paper_market_intent()`, contracts adapters, `PnLSnapshot` |
| 7 | `FundingCaptureStrategy`, `StrategySignal`, `FundingCaptureConfig` |
| 8 | `RiskEngine` with 4 hard checks, `RiskEvent`, `RiskConfig` |
| 9 | `accrue_funding_payment()`, `FundingPayment` model |
| 10 | `PaperTradingLoop` orchestrator, second Alembic migration (trading tables) |
| 11–12 | Integration wiring, test coverage, `IterationSummary` |
| 13 | `core/reporting/queries.py` — 5 read-only query functions, 31 unit tests |
| 14 | FastAPI dashboard API — 6 endpoints, Pydantic v2 schemas, 25 integration tests |
| 15 | `core/alerting/evaluator.py` — 4 alert conditions, wired into loop, 24 unit tests |

> Sprints 1–12 timings are approximate, inferred from code comments and model
> creation dates.  Sprints 13–15 are exactly as implemented.

---

## Current open punch list

### Phase 2 gaps — live collector

- [ ] Authenticated Coinbase Advanced Trade adapter (order placement)
- [ ] Authenticated Binance Futures adapter (order placement)
- [ ] Adapter reconnect / exponential backoff on exchange errors
- [ ] Rate-limit handling beyond polling interval

### Phase 4 gaps — strategy KPIs and stress tests

- [ ] Sharpe ratio calculation over a completed paper run
- [ ] Realized max drawdown metric
- [ ] Funding income vs cumulative fee drag report
- [ ] Stress test: synthetic funding-rate reversal mid-position
- [ ] Walk-forward threshold validation

### Phase 5 gaps — risk engine completion

- [ ] Max daily loss limit with automatic kill switch
- [ ] Circuit breaker (N consecutive blocks → halt loop)
- [ ] Emergency flatten (auto-close open positions with no exit signal)
- [ ] Hedge leg mismatch detection (spot qty ≠ perp qty)

### Cross-cutting items

- [x] ~~**Migration gap:** generate Alembic migration for `funding_payments` table~~ Fixed: migration `386b20f64042` generated and applied during Sprint 15 audit
- [ ] **Slippage model:** `FixedBpsFeeModel` applies zero slippage; real fills
      will incur market impact — a slippage model should be added before
      paper/live comparisons are made
- [ ] **PostgreSQL migration validation:** run `alembic upgrade head` on a fresh
      PostgreSQL database and confirm all 11 tables are created
- [ ] **Rollback testing:** confirm `downgrade` scripts work for both existing
      migrations (no test currently exists)
- [ ] **.env.example file:** a template `.env.example` is referenced in the
      original README but does not exist in the repo

---

## Next planned work — Group B: risk engine completion

Priority order for the next sprint group:

1. `funding_payments` Alembic migration — trivial fix, unblocks DB parity
2. Max daily loss limit (`RiskEngine` extension)
3. Circuit breaker (per-invocation state; possibly a new `CircuitBreakerState`
   model or an in-memory counter with session flush)
4. Emergency flatten (out-of-band intent generator)
5. Hedge leg mismatch detection (delta calculator across position snapshots)
6. Slippage model addition to `PaperOrderSimulator`

Gate D cannot be passed until items 1–5 are complete.
