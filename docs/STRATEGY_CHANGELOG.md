## 2026-03-12 — Unified Ask-Anchored Sizing + Stable Bid Price

### Motivation
The previous SG-based sizing model used mid-price distance below the TWAP as its primary signal. This was unstable: the TWAP chased price down during sustained downtrends, causing the signal to report "near zone" even during genuine deep dips, and resulting in undersized buys at exactly the wrong moments. The bid price was similarly reactive — anchored to TWAP minus a fixed offset — which caused it to follow price down and trigger too many fills at mid-dip levels rather than preserving capacity for the bottom.

### Changes

**1. Unified ask-relative sizing model** (`core/strategy/market_making.py`)

Replaced `_compute_sg_size_multiplier()` with `_compute_unified_size_multiplier()`. The new model is built on two signals that combine into a single matrix lookup per side.

Signal 1 — Ask-relative distance (stable, symmetric):
- Buy side:  `distance_bps = (ask_price - market_price) / ask_price × 10000`
- Sell side: `distance_bps = (market_price - ask_price) / ask_price × 10000`
- Both sides use `ask_price` as the stable anchor (moves slowly, only when avg_entry shifts)
- If distance_bps <= 0: order suppressed entirely (wrong side of ask)
- Zones: Near < 30 bps, Mid 30–80 bps, Far >= 80 bps (identical thresholds both sides)

Signal 2 — TWAP slope (momentum modifier, inverts between sides):
- Buy side: brake when TWAP falling, boost when TWAP rising
- Sell side: brake when TWAP rising, boost when TWAP falling
- Zones: Steep falling < -15, Mild falling -15 to -5, Neutral -5 to +5, Mild rising +5 to +15, Steep rising > +15 bps/min

Buy matrix (distance zone columns, TWAP slope rows):
```
                  Near    Mid     Far
Steep falling     0.10    0.25    0.50
Mild falling      0.25    0.50    0.75
Neutral           0.50    1.00    1.50
Mild rising       0.75    1.25    1.50
Steep rising      0.75    1.25    1.50
```

Sell matrix:
```
                  Near    Mid     Far
Steep falling     0.50    1.25    1.50
Mild falling      0.25    1.00    1.25
Neutral           0.50    1.00    1.50
Mild rising       0.25    0.50    0.75
Steep rising      0.10    0.25    0.50
```

Concavity modifier applied after matrix lookup: positive concavity → ×1.25, negative → ×0.50.

Feature flag: `UNIFIED_SIZING_ENABLED` (default: false). When disabled, returns base size unchanged.

New config fields added: `ask_sg_near_bps`, `ask_sg_far_bps`, `twap_slope_mild_threshold`, `twap_slope_steep_threshold`, `twap_slope_rising_threshold`, `twap_slope_steep_rising_threshold`, `unified_sizing_enabled`.

Removed config fields: `sg_distance_near_bps`, `sg_distance_far_bps`, `sg_slope_steep_threshold`, `sg_slope_rising_threshold`.

New structured log event: `unified_sizing_applied` (side, distance_bps, distance_zone, twap_slope_bps_per_min, twap_slope_zone, base_multiplier, concavity_modifier, final_multiplier).

New suppression log events: `unified_buy_suppressed`, `unified_sell_suppressed`.

**2. Ask-anchored bid price** (`core/strategy/market_making.py`, `apps/paper_trader/main.py`)

Replaced TWAP-relative bid calculation with ask-anchored bid:
- `ask_price = avg_entry × (1 + total_markup_bps / 10000)` when in position
- `ask_price = twap × (1 + total_markup_bps / 10000)` when flat (no position)
- `bid_price = ask_price × (1 - bid_offset_bps / 10000)`
- Default `bid_offset_bps = 120.0`

This decouples the bid from short-term price movement. The bid only shifts when avg_entry changes (i.e. when fills actually occur), making it a strategy-relative anchor rather than a reactive one.

New config field: `bid_offset_bps` (default: 120.0). New env var: `MM_BID_OFFSET_BPS`.

With current config (mm_fee_bps=25, mm_target_profit_bps=20, bid_offset_bps=120):
- total_markup_bps = 70
- bid-to-ask spread = 121.5 bps
- net spread after round-trip fees = ~71.5 bps

**3. TWAP slope computation** (`apps/paper_trader/main.py`)

Added `_compute_twap_slope()`: queries last 10 order book snapshots filtered by exchange and symbol, computes `(newest_mid - oldest_mid) / oldest_mid × 10000 / elapsed_minutes`. Returns `float | None` if fewer than 2 snapshots or elapsed time is zero. Passed into `evaluate()` as `twap_slope_bps_per_min`.

Old SG snapshot helper replaced with concavity-only helper `_latest_concavity_snapshot()`.

### Test coverage
14 new unified sizing tests added, 4 bid-anchor tests added. All 40 tests passing.

### Active config
```
UNIFIED_SIZING_ENABLED=true
MM_BID_OFFSET_BPS=120.0
ASK_SG_NEAR_BPS=30.0
ASK_SG_FAR_BPS=80.0
TWAP_SLOPE_STEEP_THRESHOLD=-15.0
TWAP_SLOPE_MILD_THRESHOLD=-5.0
TWAP_SLOPE_RISING_THRESHOLD=5.0
TWAP_SLOPE_STEEP_RISING_THRESHOLD=15.0
MM_FEE_BPS=25.0
MM_TARGET_PROFIT_BPS=20.0
```

### Known follow-up items
- `MM_SPREAD_BPS` still referenced in logging metadata and `signal_main.py` — can be removed in a follow-up cleanup once those references are updated
- Concavity thresholds not yet tuned for the new unified model

# Strategy Changelog

## 2026-03-11

### ~21:15 EST - Max Inventory Cap Breach Fix (MM_MAX_INVENTORY_PCT)
**Problem:** BTC inventory could exceed `MM_MAX_INVENTORY_PCT` because buy eligibility
checked only `current_position < max_inventory`, not projected post-fill size.
This allowed overshoot when remaining capacity was smaller than the next buy size.

**Fix:**
- Added projected-cap guard in strategy buy sizing:
  - `remaining_inventory = max_inventory - position_btc`
  - `buy_quote_size` is clipped to remaining capacity before intent creation
  - floor rounding is used for cap clipping (`ROUND_DOWN`) to avoid rounding up past cap
- Updated paper trader account-value basis used for limit sizing to use current mid mark:
  - `account_value_for_limits = cash_value + current_position * snapshot.mid_price`

**Result:** Buy intents can no longer increase position beyond max inventory in a
single fill, including when remaining capacity is very small.

**Tests:**
- `test_max_inventory_cap_prevents_buy_at_limit`
- `test_max_inventory_cap_uses_current_account_value`
- Full strategy test module passed: `37 passed`

**Files changed:** `core/strategy/market_making.py`, `apps/paper_trader/main.py`,
`tests/unit/test_strategy_market_making.py`

### 17:34 EST — Guardrail Verification
Confirmed all three sell-side guardrails intact in `core/strategy/market_making.py`
after all patches applied today:
- Position cap: `sell_quote_size = min(sell_quote_size, current_position_qty)` (line 255)
- Zero-position suppression: sell intent never appended when position = 0 (lines 239-244)
- Structured logs: `sg_sell_suppressed` (reason field) and `sg_sell_capped`
  (uncapped_sell_size, capped_sell_size fields) both present (lines 241, 247, 258)

Note: one historical oversell detected at 16:33 UTC (overage: 0.000165 BTC, ~$11.65)
occurred before paper trader was restarted with new code. Guardrail was in code but
not yet running in memory at that time.

---

### 17:34 EST — Ask Price Fix: Cost-Basis + Fees + Profit Margin
**Problem:** Ask price was calculated at exactly breakeven (50bps above entry),
covering round-trip fees but leaving zero net profit per trade.

**Fix:** Ask price now uses explicit fee + profit markup:
  `ask_price = avg_entry_price x (1 + (2 x MM_FEE_BPS + MM_TARGET_PROFIT_BPS) / 10000)`

**Config at deployment:**
- `MM_FEE_BPS=25.0` (25bps per side, 50bps round-trip)
- `MM_TARGET_PROFIT_BPS=20.0` (20bps net profit per round-trip)
- Total markup: 70bps above avg entry price

**Impact:** Ask moved from ~$70,919 to ~$71,060 on current position (entry $70,566).
Net profit per filled sell: ~$141 per BTC.

**Files changed:** `core/strategy/market_making.py`, `core/config/settings.py`,
`apps/paper_trader/main.py`, `.env.example`

---

### ~17:15 EST — Bid Spread Reduced: 35bps to 20bps
**Change:** `MM_SPREAD_BPS` reduced from 35 to 20 to gather data on fill rate
vs spread quality tradeoff. Can be reverted.

**Impact:** Buy quote moved from ~$247 below TWAP to ~$141 below TWAP.
Expected result: higher fill frequency, potentially tighter spread captured.

---

### ~17:00 EST — Buy Price Anchor Fixed: Raw Mid to TWAP
**Problem:** Buy quote was anchored to raw order book mid price, causing
the bid line to oscillate $10-$99 between 60-second snapshots.

**Fix:** Buy quote now anchors to externally-fetched TWAP:
  `buy_price = twap x (1 - MM_SPREAD_BPS / 10000)`
  Fallback to mid_price if TWAP unavailable.

Also fixed: buy spread changed from half-spread to full MM_SPREAD_BPS.
Old mid-price override path (when mid < avg_entry) removed.

**Files changed:** `core/strategy/market_making.py`, `apps/paper_trader/main.py`

---

### ~15:15 EST — SG Strategy Deployed (sell-side sizing fix)
**Problem:** Sell side used fixed quote size (~0.00284 BTC) regardless of
SG curve position, causing sells to exceed accumulated position size.

**Fix:** Sell sizing now mirrors buy-side SG logic but inverted.
Hard rule added: `sell_size = min(sg_adjusted_size, current_position_qty)`
Sell suppressed entirely if position is zero.

**Files changed:** `core/strategy/market_making.py`

---

### ~10:15 EST — SG-Based Strategy Deployed (buy-side sizing)
Initial SG strategy deployment. Buy sizing driven by SG curve signals:
- SG slope, distance of mid below SG curve, concavity modifier

**Config at deployment:**
- `SG_SIZING_ENABLED=true`
- `MM_SPREAD_BPS=35`
- SG curve: 25-period, d2 mode, 4H TWAP window

**Baseline at deployment:** Net PnL $17.64, position +0.00726 BTC

---

*Session-end baseline (before ask fix deploy):*
- Total fills: 60 | Net PnL: ~$25.10 | Realized PnL: $21.68
- Fees paid: $16.59 | Position: +0.00073 BTC long @ $70,566

## Pre-2026-03-11 (prior session)

### Algorithm testing period
Multiple algorithm tweaks over ~26 hours resulted in accumulated long
position of +0.00726 BTC and net PnL of $17.64 at start of 3/11 session.
Position retained intentionally to preserve historical data continuity.

---

*Baseline metrics at end of 2026-03-11 session (pre-deploy of ask fix):*
- Total fills: 60
- Net PnL: ~$25.10
- Realized PnL: $21.68
- Fees paid: $16.59
- Position: +0.00073 BTC long @ $70,566