# Delta-Neutral Strategy — Backtest Results

*Last updated: 2026-03-23*
*Strategy: Long ETH spot + Short ETH-PERP perpetual*
*Capital: $2,500 | Contracts: 8 (0.80 ETH) | Entry threshold: +5.00% APR*

## Summary

The delta-neutral strategy was backtested across 6 distinct market regimes
spanning January 2020 to March 2025. Funding rates are synthetic but
calibrated to historically realistic values for each regime.

**Key finding:** Net directional PnL is $0.00 across all regimes -
the hedge eliminates price exposure completely. Returns are driven
entirely by funding income.

## Results — Base Case (5bps fees per leg)

| Regime | Period | Funding APR | Net PnL | Annualized | Max DD | Fees |
|---|---|---|---|---|---|---|
| COVID crash | Mar-Apr 2020 | 5.5% | $0.88 | 0.21% | $0.17 | $0.34 |
| Bull run 2021 | Oct-Nov 2021 | 21.9% | $114.13 | 27.32% | $1.94 | $6.12 |
| Bear market 2022 | May-Jul 2022 | 5.5% | $14.67 | 2.33% | $2.08 | $3.54 |
| Ranging 2023 | Jan-Mar 2023 | 16.4% | $48.89 | 7.93% | $0.81 | $2.41 |
| ETF run-up 2024 | Oct-Dec 2024 | 27.4% | $165.90 | 26.33% | $1.57 | $4.76 |
| Pullback 2025 | Jan-Mar 2025 | 8.8% | $41.95 | 6.80% | $2.47 | $4.14 |
| **Average** | | | | **11.82%** | | |

## Results — With 20% Slippage Buffer (5bps × 1.20)

| Regime | Period | Funding APR | Net PnL | Annualized | Max DD | Fees |
|---|---|---|---|---|---|---|
| COVID crash | Mar-Apr 2020 | 5.5% | $0.81 | 0.19% | $0.20 | $0.41 |
| Bull run 2021 | Oct-Nov 2021 | 21.9% | $112.91 | 27.02% | $2.42 | $7.35 |
| Bear market 2022 | May-Jul 2022 | 5.5% | $13.96 | 2.22% | $2.52 | $4.24 |
| Ranging 2023 | Jan-Mar 2023 | 16.4% | $48.41 | 7.85% | $1.00 | $2.90 |
| ETF run-up 2024 | Oct-Dec 2024 | 27.4% | $164.95 | 26.18% | $1.99 | $5.71 |
| Pullback 2025 | Jan-Mar 2025 | 8.8% | $41.12 | 6.67% | $3.01 | $4.97 |
| **Average** | | | | **11.69%** | | |

## Gate E Assessment

Phase 8 exit criteria requires positive edge in at least 4 of 6 regimes
after realistic fee and slippage assumptions.

- Base case: 6/6 regimes positive
- With slippage buffer: 6/6 regimes positive
- Gate E: PASS

## Notes on Methodology

- ETH spot prices from Kraken historical CSV (59,618 hourly candles, Jan 2020-Dec 2025)
- Funding rates are synthetic, calibrated to realistic per-regime values
- Entry occurs when funding APR >= 5.00%, exit when funding APR <= 2.00%
- Net directional PnL = $0.00 in all cases (hedge working correctly)
- Fees: 5bps per leg per entry/exit (Coinbase CFM maker rate)
- Capital: $2,500 | Position: 8 contracts (0.80 ETH)
