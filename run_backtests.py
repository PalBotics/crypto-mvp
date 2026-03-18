"""
Run all 36 backtest combinations across 6 market regimes x 6 configs.
Usage: python run_backtests.py
Output: backtest_results/summary.csv + printed table
"""

import subprocess
import sys
import re
import csv
import os
from pathlib import Path

PYTHON = str(Path(sys.executable))
SCRIPT = "scripts/backtest.py"
OUT_DIR = Path("backtest_results")
OUT_DIR.mkdir(exist_ok=True)

RUNS = [
    # regime,       start,          end,            bid, tp
    # COVID crash (Mar–Apr 2020, $10k→$4k→$7k)
    ("covid",  "2020-03-01", "2020-04-30", 120, 20),
    ("covid",  "2020-03-01", "2020-04-30", 120, 10),
    ("covid",  "2020-03-01", "2020-04-30", 120,  5),
    ("covid",  "2020-03-01", "2020-04-30", 180, 20),
    ("covid",  "2020-03-01", "2020-04-30", 180, 10),
    ("covid",  "2020-03-01", "2020-04-30",  80,  5),
    # Bull run peak (Oct–Nov 2021, $43k→$68k)
    ("bull",   "2021-10-01", "2021-11-30", 120, 20),
    ("bull",   "2021-10-01", "2021-11-30", 120, 10),
    ("bull",   "2021-10-01", "2021-11-30", 120,  5),
    ("bull",   "2021-10-01", "2021-11-30", 180, 20),
    ("bull",   "2021-10-01", "2021-11-30", 180, 10),
    ("bull",   "2021-10-01", "2021-11-30",  80,  5),
    # Bear market collapse (May–Jul 2022, $38k→$19k)
    ("bear",   "2022-05-01", "2022-07-31", 120, 20),
    ("bear",   "2022-05-01", "2022-07-31", 120, 10),
    ("bear",   "2022-05-01", "2022-07-31", 120,  5),
    ("bear",   "2022-05-01", "2022-07-31", 180, 20),
    ("bear",   "2022-05-01", "2022-07-31", 180, 10),
    ("bear",   "2022-05-01", "2022-07-31",  80,  5),
    # Slow recovery / ranging (Jan–Mar 2023, $16k→$28k)
    ("range",  "2023-01-01", "2023-03-31", 120, 20),
    ("range",  "2023-01-01", "2023-03-31", 120, 10),
    ("range",  "2023-01-01", "2023-03-31", 120,  5),
    ("range",  "2023-01-01", "2023-03-31", 180, 20),
    ("range",  "2023-01-01", "2023-03-31", 180, 10),
    ("range",  "2023-01-01", "2023-03-31",  80,  5),
    # ETF run-up (Oct–Dec 2024, $60k→$109k)
    ("etf",    "2024-10-01", "2024-12-31", 120, 20),
    ("etf",    "2024-10-01", "2024-12-31", 120, 10),
    ("etf",    "2024-10-01", "2024-12-31", 120,  5),
    ("etf",    "2024-10-01", "2024-12-31", 180, 20),
    ("etf",    "2024-10-01", "2024-12-31", 180, 10),
    ("etf",    "2024-10-01", "2024-12-31",  80,  5),
    # Current pullback (Jan–Mar 2025, $109k→$71k)
    ("now",    "2025-01-01", "2025-03-13", 120, 20),
    ("now",    "2025-01-01", "2025-03-13", 120, 10),
    ("now",    "2025-01-01", "2025-03-13", 120,  5),
    ("now",    "2025-01-01", "2025-03-13", 180, 20),
    ("now",    "2025-01-01", "2025-03-13", 180, 10),
    ("now",    "2025-01-01", "2025-03-13",  80,  5),
]

def parse_output(lines):
    """Extract metrics from backtester console output."""
    text = "\n".join(lines)

    def find(pattern, default="?"):
        m = re.search(pattern, text, re.MULTILINE)
        return m.group(1).strip() if m else default

    fills_line = find(r"^Total fills:\s+(.+)$")
    total_fills = fills_line.split()[0] if fills_line != "?" else "?"
    buys  = re.search(r"\((\d+) buys",  fills_line) 
    sells = re.search(r"(\d+) sells\)", fills_line)

    return {
        "fills": total_fills,
        "buys":  buys.group(1)  if buys  else "?",
        "sells": sells.group(1) if sells else "?",
        "net_pnl":     find(r"^Net PnL:\s+(.+)$"),
        "return_pct":  find(r"^Return:\s+(.+)$"),
        "max_dd":      find(r"^Max drawdown:\s+(.+)$"),
        "snapshots":   find(r"^Snapshots replayed:\s+(.+)$"),
    }

results = []
total = len(RUNS)

for i, (regime, start, end, bid, tp) in enumerate(RUNS, 1):
    label = f"{regime}_bo{bid}_tp{tp}"
    outfile = str(OUT_DIR / f"{label}.csv")

    print(f"[{i:2d}/{total}] {label} ...", end=" ", flush=True)

    proc = subprocess.run(
        [PYTHON, SCRIPT,
         "--start", start,
         "--end",   end,
         "--bid-offset",    str(bid),
         "--target-profit", str(tp),
         "--output", outfile],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    if proc.returncode != 0:
        print(f"ERROR\n{proc.stderr[-300:]}")
        metrics = {"fills":"ERR","buys":"ERR","sells":"ERR",
                   "net_pnl":"ERR","return_pct":"ERR","max_dd":"ERR","snapshots":"ERR"}
    else:
        metrics = parse_output(proc.stdout.splitlines())
        print(f"fills={metrics['fills']} ({metrics['buys']}B/{metrics['sells']}S)  "
              f"net={metrics['net_pnl']}  ret={metrics['return_pct']}  dd={metrics['max_dd']}")

    results.append({
        "regime": regime,
        "start": start,
        "end": end,
        "bid_offset": bid,
        "target_profit": tp,
        **metrics,
    })

# ── Summary table ────────────────────────────────────────────────────────────
print("\n" + "="*90)
print(f"{'Regime':<8} {'Bid':>5} {'TP':>4} {'Fills':>6} {'B/S':>7} "
      f"{'Net PnL':>10} {'Return':>8} {'MaxDD':>8}")
print("-"*90)

for r in results:
    bs = f"{r['buys']}/{r['sells']}"
    print(f"{r['regime']:<8} {r['bid_offset']:>5} {r['target_profit']:>4} "
          f"{r['fills']:>6} {bs:>7} "
          f"{r['net_pnl']:>10} {r['return_pct']:>8} {r['max_dd']:>8}")

# ── Wins per config ──────────────────────────────────────────────────────────
print("\n" + "="*90)
print("CONFIG WINS (regimes with positive Net PnL)")
print("-"*90)

configs = [(bid, tp) for bid, tp in set((r["bid_offset"], r["target_profit"]) for r in results)]
configs.sort()

for bid, tp in configs:
    subset = [r for r in results if r["bid_offset"] == bid and r["target_profit"] == tp]
    def to_float(s):
        try:
            return float(re.sub(r"[^0-9.\-]", "", s))
        except:
            return None
    wins = [r for r in subset if (to_float(r["net_pnl"]) or 0) > 0]
    win_regimes = ", ".join(r["regime"] for r in wins)
    print(f"  bid={bid:3d} tp={tp:2d}: {len(wins)}/6 positive  [{win_regimes}]")

# ── Best per regime ──────────────────────────────────────────────────────────
print("\n" + "="*90)
print("BEST CONFIG PER REGIME (by Net PnL)")
print("-"*90)

for regime in ["covid", "bull", "bear", "range", "etf", "now"]:
    subset = [r for r in results if r["regime"] == regime]
    def to_float(s):
        try:
            return float(re.sub(r"[^0-9.\-]", "", s))
        except:
            return -9999
    best = max(subset, key=lambda r: to_float(r["net_pnl"]))
    print(f"  {regime:<6}: bid={best['bid_offset']} tp={best['target_profit']:2d} "
          f"→ net={best['net_pnl']}  ret={best['return_pct']}")

# ── Save CSV ─────────────────────────────────────────────────────────────────
summary_path = OUT_DIR / "summary.csv"
with open(summary_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=results[0].keys())
    writer.writeheader()
    writer.writerows(results)

print(f"\nSaved {summary_path}")