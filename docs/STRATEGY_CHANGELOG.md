# Strategy Changelog

## 2026-03-11

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

---

## 2026-03-11

### 17:34 EST — Ask Price Fix: Cost-Basis + Fees + Profit Margin
**Problem:** Ask price was calculated at exactly breakeven (50bps above entry),
covering round-trip fees but leaving zero net profit per trade.

**Fix:** Ask price now uses explicit fee + profit markup:
  `ask_price = avg_entry_price × (1 + (2 × MM_FEE_BPS + MM_TARGET_PROFIT_BPS) / 10000)`

**Config at deployment:**
- `MM_FEE_BPS=25.0` (25bps per side, 50bps round-trip)
- `MM_TARGET_PROFIT_BPS=20.0` (20bps net profit per round-trip)
- Total markup: 70bps above avg entry price

**Impact:** Ask moved from ~$70,919 → ~$71,060 on current position (entry $70,566).
Net profit per filled sell: ~$141 per BTC.

**Files changed:** `core/strategy/market_making.py`, `core/config/settings.py`,
`apps/paper_trader/main.py`, `.env.example`

---

### ~17:15 EST — Bid Spread Reduced: 35bps → 20bps
**Change:** `MM_SPREAD_BPS` reduced from 35 to 20 to gather data on fill rate
vs spread quality tradeoff. Can be reverted.

**Impact:** Buy quote moved from ~$247 below TWAP to ~$141 below TWAP.
Expected result: higher fill frequency, potentially tighter spread captured.

---

### ~17:00 EST — Buy Price Anchor Fixed: Raw Mid → TWAP
**Problem:** Buy quote was anchored to raw order book mid price, causing
the bid line to oscillate $10–$99 between 60-second snapshots — not
reflective of true price trend.

**Fix:** Buy quote now anchors to externally-fetched TWAP:
  `buy_price = twap × (1 - MM_SPREAD_BPS / 10000)`
  Fallback to mid_price if TWAP unavailable.

Also fixed: buy spread changed from half-spread to full MM_SPREAD_BPS.
Old mid-price override path (when mid < avg_entry) removed — bid line
now stays anchored to TWAP regardless of entry price.

**Files changed:** `core/strategy/market_making.py`, `apps/paper_trader/main.py`

---

### ~15:15 EST — SG Strategy Deployed (sell-side sizing fix)
**Problem:** Sell side used fixed quote size (~0.00284 BTC) regardless of
SG curve position, while buy side was already SG-scaled. This caused
sells to consistently exceed accumulated position size.

**Fix:** Sell sizing now mirrors buy-side SG logic but inverted —
the further ask price is above the SG curve, the larger the sell.

**Sell size matrix (slope × distance above SG):**

|                   | Steep (<-30) | Flat (-30 to +15) | Rising (>+15) |
|-------------------|-------------|-------------------|---------------|
| Near (<10bps)     | 0.25        | 0.10              | 0.00          |
| Mid (10–40bps)    | 0.75        | 0.50              | 0.10          |
| Far (>40bps)      | 1.50        | 1.00              | 0.25          |

**Hard rule added:** `sell_size = min(sg_adjusted_size, current_position_qty)`
Sell suppressed entirely if position is zero.

**Files changed:** `core/strategy/market_making.py`

---

### ~10:15 EST — SG-Based Strategy Deployed (buy-side sizing)
**Initial SG strategy deployment.** Buy sizing driven by SG curve signals:
- Signal 1: SG slope (buy at all? how much?)
- Signal 2: Distance of mid below SG curve (scale size)
- Signal 3: Concavity modifier (fine-tune)

**Buy size matrix (slope × distance below SG):**

|                   | Steep (<-30) | Flat (-30 to +15) | Rising (>+15) |
|-------------------|-------------|-------------------|---------------|
| Near (<10bps)     | 0.00        | 0.10              | 0.25          |
| Mid (10–40bps)    | 0.10        | 0.50              | 0.75          |
| Far (>40bps)      | 0.25        | 1.00              | 1.50          |

**Config at deployment:**
- `SG_SIZING_ENABLED=true`
- `MM_SPREAD_BPS=35`
- SG curve: 25-period, d2 mode, 4H TWAP window

**Baseline at deployment:** Net PnL $17.64, position +0.00726 BTC (accumulated
from prior algorithm testing over previous ~26 hours).

---

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