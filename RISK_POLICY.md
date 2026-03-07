# Risk Policy

## Guiding principles

1. **No real capital before paper trading passes.**  The system must demonstrate
   stable paper trading behaviour — consistent PnL accounting, correct position
   tracking, no silent data loss — before any live integration is considered.
   Gate D (defined below) must be satisfied first.

2. **One strategy at a time.**  Only one `FundingCaptureStrategy` instance runs
   per invocation.  Multi-strategy aggregation is explicitly deferred.  Running
   two overlapping instances against the same account name is undefined
   behaviour and must be prevented operationally.

3. **Hard controls block first; alerting surfaces degraded conditions.**
   Pre-trade hard checks (RiskEngine) reject individual orders silently but
   durably (via `RiskEvent` rows).  Post-iteration alerts (AlertEvaluator) are
   for monitoring — they do not by themselves halt execution.

4. **Preserve the audit trail.**  Every risk block and every critical alert
   persists a `RiskEvent` row to the database before the iteration commits.
   Nothing is silently discarded.

---

## Current hard controls (implemented)

All four controls live in `core/risk/engine.py` (`RiskEngine.check()`).  They
are evaluated in strict order per `OrderIntent`.  The first failure
short-circuits and the intent is marked `rejected`.

### 1. Kill switch

**Trigger:** `RiskConfig.kill_switch_active = True`

**Effect:** Every incoming order intent is rejected unconditionally, regardless
of market conditions.  Activation is a code-level configuration change; there
is no runtime toggle or API.

**What it blocks:** All new fills, position changes, and PnL changes.  Funding
accrual and alerting still run.

**`rule_name` in RiskEvent:** `kill_switch_active`

---

### 2. Stale data block

**Trigger:** `(now − latest_funding_ts) > max_data_age_seconds`

**Effect:** Entry and exit intents are both blocked when the funding timestamp
passed to the execution loop is older than the configured threshold.

`latest_funding_ts` is supplied by `PaperTradingLoop` as
`datetime.now(timezone.utc)` at the start of the intent-drain phase.  In the
current implementation this means stale-data blocking depends on the collector
having run recently enough that the funding-rate snapshot is fresh.

**Default:** `max_data_age_seconds = 3600` (configured in `RiskConfig`)

**`rule_name` in RiskEvent:** `stale_funding_data`

---

### 3. Funding edge block (entry only)

**Trigger:** `funding_rate < min_entry_funding_rate` and `order_intent.reduce_only = False`

**Effect:** Entry intents are blocked when the funding rate falls below the
minimum threshold.  Exit intents (`reduce_only = True`) bypass this check —
you are always allowed to close an existing position.

**Default:** `min_entry_funding_rate = 0.0001` (1 basis point per 8-hour
period; configured in `RiskConfig`)

**`rule_name` in RiskEvent:** `funding_below_threshold`

---

### 4. Max notional block

**Trigger:** `order_intent.quantity × mark_price > max_notional_per_symbol`

**Effect:** Any intent whose estimated notional value (quantity × latest ask
price from `MarketTick`) exceeds the per-symbol ceiling is rejected.

**Default:** `max_notional_per_symbol = 1_000_000` USDT (configured in `RiskConfig`)

**`rule_name` in RiskEvent:** `max_notional_exceeded`

---

## Post-iteration alert conditions (implemented)

Alert conditions live in `core/alerting/evaluator.py` (`AlertEvaluator`).
They run after all intents for an iteration are settled, before `session.commit()`.
No alert by itself halts execution — alerts are observability signals.

| Alert type | Severity | Persists RiskEvent? | Condition |
|---|---|---|---|
| `stale_funding_data` | warning | no | Latest `FundingRateSnapshot` missing or older than `stale_data_threshold_seconds` |
| `position_pnl_drawdown` | critical | **yes** | Net PnL (realized + funding payments) < `drawdown_threshold` |
| `open_position_no_recent_fill` | warning | no | Open position exists but no fill within `no_fill_threshold_seconds` |
| `no_funding_edge` | info | no | Latest funding rate < `min_funding_rate` |

---

## Controls that are missing and must be built before live trading

The following controls are explicitly deferred.  Gate D cannot be passed until
every item in this section is implemented and tested.

### Max daily loss

**What it should do:** Track cumulative realized loss within a UTC calendar
day.  If the daily loss exceeds a hard threshold, activate the kill switch
automatically for the remainder of that day.

**Why it is missing:** Requires a daily-reset accumulator and automatic kill
switch activation.  Neither exists yet.

**Risk without it:** An adverse market move can compound losses across many
iterations with no automatic halt.

---

### Circuit breaker

**What it should do:** Count consecutive RiskEngine blocks (any rule) within
a rolling window.  If the block count exceeds a threshold, halt the loop and
emit a `SystemEvent` requiring manual acknowledgement before restarting.

**Why it is missing:** Requires state held across iterations (not per-intent).
The current RiskEngine evaluates each intent in isolation.

**Risk without it:** Rapid-fire blocks may indicate a misconfigured strategy or
broken data feed; without a circuit breaker the loop continues to attempt
(and log) failed intents indefinitely.

---

### Emergency flatten

**What it should do:** Detect open positions that have no corresponding closing
strategy signal for more than a configurable period, and automatically emit
`reduce_only=True` intents to close them.

**Why it is missing:** Requires a "position age" tracker and an out-of-band
intent generator that does not go through the normal strategy path.

**Risk without it:** If the strategy logic fails to emit an exit signal (e.g.,
due to a bug), positions remain open indefinitely with no automatic recovery.

---

### Hedge leg mismatch detection

**What it should do:** Verify that the spot leg and the perp leg of the
delta-neutral pair remain size-matched within a configurable tolerance after
every fill.  Emit a critical alert if they diverge.

**Why it is missing:** Requires tracking two correlated positions (spot and
perp for the same underlying) and computing the net delta.  The current model
treats each position independently.

**Risk without it:** A partial fill on one leg leaves a directional residual
exposure that is invisible to the current alerting layer.

---

## Gate D — prerequisites for any real capital

All of the following must be true before a live exchange integration is
permitted:

1. **Paper trading stability:** At least 30 consecutive days of paper trading
   with no silent data loss, no negative-quantity positions, and no PnL
   accounting discrepancies.

2. **Risk engine completion:** All four missing controls above are implemented
   and covered by unit tests.

3. **Migration parity:** All database models have a corresponding Alembic
   migration.  `alembic upgrade head` on a fresh database creates every table
   used at runtime.  (Fixed in Sprint 15 audit — `funding_payments` migration
   `386b20f64042` generated and applied.)

4. **Kill switch test:** A manual test demonstrating that setting
   `kill_switch_active=True` stops all new fills within one iteration with no
   uncommitted PnL change.

5. **Max daily loss test:** A simulation demonstrating that a sequence of
   losing fills triggers the daily loss limit and halts the loop.

6. **Emergency flatten test:** A simulation demonstrating that a "stuck
   position" (no exit signal for > threshold period) triggers emergency
   flattening.

7. **Hedge leg mismatch test:** A simulation demonstrating that a partial fill
   on one leg triggers a critical alert and blocks new entry intents until
   acknowledged.

8. **Exchange adapter review:** A code review of the live exchange adapter(s)
   covering authentication, order placement, error handling, and rate limits.

---

## Manual review process during limited live deployment

Once Gate D is passed, the initial live deployment will be limited and manually
supervised.  The process is:

1. Start with the smallest viable position size on a single symbol.
2. Review the dashboard (`/runs/{account_name}/summary`) after every live
   iteration.  Look for anomalies: unexpected position changes, risk events,
   unusual PnL swings.
3. Review `risk_events` after every session: any block that was not expected
   requires an explanation before the next session starts.
4. Any `position_pnl_drawdown` alert (even without the daily loss limit
   triggering) is grounds for manual halting the loop.
5. Do not leave the loop unattended until at least five consecutive live
   sessions have run without any unexpected risk events.
