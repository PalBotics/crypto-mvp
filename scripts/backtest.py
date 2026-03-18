from __future__ import annotations

import argparse
import csv
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable

import numpy as np
from sqlalchemy import select

from core.db.session import SessionLocal
from core.models.order_book_snapshot import OrderBookSnapshot
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _fmt_money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'))}"


def _fmt_percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"


def _parse_date_utc(date_text: str) -> datetime:
    parsed = datetime.strptime(date_text, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc)


@dataclass
class FillEvent:
    ts: datetime
    side: str
    price: Decimal
    qty: Decimal
    fee: Decimal
    cash_after: Decimal
    position_after: Decimal
    unrealized_pnl_at_fill: Decimal


class ReplayMarketMakingStrategy(MarketMakingStrategy):
    """Strategy wrapper that avoids DB queries during replay TWAP calculation."""

    def __init__(self, config: MarketMakingConfig) -> None:
        super().__init__(config)
        self._replay_twap: Decimal | None = None

    def set_replay_twap(self, twap: Decimal | None) -> None:
        self._replay_twap = twap

    def _calculate_twap(self, session, current_ts: datetime, current_mid: Decimal) -> tuple[Decimal, int]:
        if self._replay_twap is None:
            return current_mid, 0
        return self._replay_twap, 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay market-making strategy over historical order book snapshots")
    parser.add_argument("--days", type=int, default=30, help="Days of history to replay (default: 30)")
    parser.add_argument("--start", type=str, default=None, help="Filter snapshots on or after UTC date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="Filter snapshots before UTC date YYYY-MM-DD")
    parser.add_argument("--spread-bps", type=str, default=None, help="MM spread bps override (default: strategy config)")
    parser.add_argument("--bid-offset", type=float, default=120.0, help="ASK->BID offset bps (default: 120)")
    parser.add_argument("--near-bps", type=float, default=30.0, help="ASK_SG_NEAR_BPS (default: 30)")
    parser.add_argument("--far-bps", type=float, default=80.0, help="ASK_SG_FAR_BPS (default: 80)")
    parser.add_argument("--target-profit", type=float, default=None, help="MM target profit bps override")
    parser.add_argument("--capital", type=str, default="1000", help="Starting USD capital (default: 1000)")
    parser.add_argument("--output", type=str, default="backtest_results.csv", help="CSV output path")
    return parser.parse_args()


def compute_time_bounds(args: argparse.Namespace) -> tuple[datetime | None, datetime | None]:
    start_ts = _parse_date_utc(args.start) if args.start else None
    end_ts = _parse_date_utc(args.end) if args.end else None

    if start_ts is None and end_ts is None:
        now = datetime.now(timezone.utc)
        start_ts = now - timedelta(days=int(args.days))

    return start_ts, end_ts


def load_snapshots(start_ts: datetime | None, end_ts: datetime | None) -> list[OrderBookSnapshot]:
    stmt = (
        select(OrderBookSnapshot)
        .where(OrderBookSnapshot.exchange == "kraken")
        .where(OrderBookSnapshot.symbol == "XBTUSD")
    )
    if start_ts is not None:
        stmt = stmt.where(OrderBookSnapshot.event_ts >= start_ts)
    if end_ts is not None:
        stmt = stmt.where(OrderBookSnapshot.event_ts < end_ts)

    stmt = stmt.order_by(OrderBookSnapshot.event_ts.asc())

    with SessionLocal() as session:
        rows = session.execute(stmt).scalars().all()
    return [row for row in rows if row.mid_price is not None]


def build_strategy(args: argparse.Namespace) -> ReplayMarketMakingStrategy:
    base = MarketMakingConfig()
    cfg_kwargs: dict[str, object] = {
        "unified_sizing_enabled": True,
        "bid_offset_bps": float(args.bid_offset),
        "ask_sg_near_bps": float(args.near_bps),
        "ask_sg_far_bps": float(args.far_bps),
    }
    if args.spread_bps is not None:
        cfg_kwargs["spread_bps"] = Decimal(str(args.spread_bps))
    if args.target_profit is not None:
        cfg_kwargs["mm_target_profit_bps"] = float(args.target_profit)

    config = MarketMakingConfig(**{**base.__dict__, **cfg_kwargs})
    return ReplayMarketMakingStrategy(config)


def compute_twap(twap_window: deque[tuple[datetime, Decimal]], current_ts: datetime) -> Decimal | None:
    cutoff = current_ts - timedelta(hours=8)
    while twap_window and twap_window[0][0] < cutoff:
        twap_window.popleft()

    if not twap_window:
        return None

    mids = [mid for _, mid in twap_window]
    return sum(mids, Decimal("0")) / Decimal(len(mids))


def compute_twap_slope(slope_window: deque[tuple[datetime, Decimal]]) -> float | None:
    if len(slope_window) < 2:
        return None

    oldest_ts, oldest_mid = slope_window[0]
    newest_ts, newest_mid = slope_window[-1]
    if oldest_mid == Decimal("0"):
        return None

    elapsed_minutes = (newest_ts - oldest_ts).total_seconds() / 60.0
    if elapsed_minutes <= 0:
        return None

    slope_bps_per_min = ((newest_mid - oldest_mid) / oldest_mid) * Decimal("10000")
    return float(slope_bps_per_min / Decimal(str(elapsed_minutes)))


def compute_concavity(concavity_window: deque[Decimal]) -> float | None:
    if len(concavity_window) < 10:
        return None

    y = np.array([float(v) for v in concavity_window], dtype=float)
    x = np.arange(y.size, dtype=float)
    coeffs = np.polyfit(x, y, 2)
    return float(coeffs[0])


def allowed_sides(position_qty: Decimal, max_inventory: Decimal) -> set[str]:
    if position_qty >= max_inventory:
        return {"sell"}
    if position_qty <= Decimal("0"):
        return {"buy", "sell"}
    return {"buy", "sell"}


def write_csv(path: Path, fills: Iterable[FillEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "ts",
                "side",
                "price",
                "qty",
                "fee",
                "cash_after",
                "position_after",
                "unrealized_pnl_at_fill",
            ]
        )
        for fill in fills:
            writer.writerow(
                [
                    fill.ts.isoformat(),
                    fill.side,
                    str(fill.price),
                    str(fill.qty),
                    str(fill.fee),
                    str(fill.cash_after),
                    str(fill.position_after),
                    str(fill.unrealized_pnl_at_fill),
                ]
            )


def run_backtest(args: argparse.Namespace) -> int:
    start_ts, end_ts = compute_time_bounds(args)
    snapshots = load_snapshots(start_ts, end_ts)
    if not snapshots:
        print("No snapshots found for requested range.")
        return 1

    strategy = build_strategy(args)
    config = strategy.config

    starting_capital = Decimal(str(args.capital))
    cash = starting_capital
    position_qty = Decimal("0")
    avg_entry_price: Decimal | None = None

    twap_window: deque[tuple[datetime, Decimal]] = deque(maxlen=480)
    slope_window: deque[tuple[datetime, Decimal]] = deque(maxlen=10)
    concavity_window: deque[Decimal] = deque(maxlen=25)

    fills: list[FillEvent] = []
    buy_count = 0
    sell_count = 0
    total_fees = Decimal("0")

    peak_value = starting_capital
    max_drawdown = Decimal("0")

    root_logger = logging.getLogger()
    previous_level = root_logger.level
    root_logger.setLevel(logging.WARNING)
    try:
        for snap in snapshots:
            ts = snap.event_ts
            mid = _to_decimal(snap.mid_price)

            twap_window.append((ts, mid))
            slope_window.append((ts, mid))
            concavity_window.append(mid)

            twap = compute_twap(twap_window, ts)
            slope = compute_twap_slope(slope_window)
            concavity = compute_concavity(concavity_window)

            strategy.set_replay_twap(twap)

            try:
                intents = strategy.evaluate(
                    session=None,
                    order_book=snap,
                    current_position=position_qty,
                    current_ts=ts,
                    twap=twap,
                    avg_entry_price=avg_entry_price,
                    allowed_sides=allowed_sides(position_qty, config.max_inventory),
                    twap_slope_bps_per_min=slope,
                    concavity=concavity,
                )
            except Exception as exc:
                print(f"Warning: evaluate() failed at {ts.isoformat()}: {exc}")
                continue

            for intent in intents:
                side = str(intent.side).lower()
                intent_price = _to_decimal(intent.limit_price)
                intent_qty = _to_decimal(intent.quantity)
                fee_bps = Decimal(str(config.mm_fee_bps))

                if side == "buy" and mid <= intent_price:
                    cost = intent_qty * intent_price
                    fee = cost * (fee_bps / Decimal("10000"))
                    if cash < (cost + fee):
                        continue

                    total_qty = position_qty + intent_qty
                    if position_qty > 0 and avg_entry_price is not None:
                        avg_entry_price = ((position_qty * avg_entry_price) + (intent_qty * intent_price)) / total_qty
                    else:
                        avg_entry_price = intent_price

                    cash -= (cost + fee)
                    position_qty = total_qty
                    total_fees += fee
                    buy_count += 1

                    unrealized_at_fill = Decimal("0")
                    if position_qty > 0 and avg_entry_price is not None:
                        unrealized_at_fill = position_qty * (mid - avg_entry_price)

                    fills.append(
                        FillEvent(
                            ts=ts,
                            side="buy",
                            price=intent_price,
                            qty=intent_qty,
                            fee=fee,
                            cash_after=cash,
                            position_after=position_qty,
                            unrealized_pnl_at_fill=unrealized_at_fill,
                        )
                    )

                if side == "sell" and mid >= intent_price:
                    sell_qty = min(intent_qty, position_qty)
                    if sell_qty <= 0:
                        continue

                    proceeds = sell_qty * intent_price
                    fee = proceeds * (fee_bps / Decimal("10000"))
                    cash += (proceeds - fee)
                    position_qty -= sell_qty
                    total_fees += fee
                    sell_count += 1

                    if position_qty == 0:
                        avg_entry_price = None

                    unrealized_at_fill = Decimal("0")
                    if position_qty > 0 and avg_entry_price is not None:
                        unrealized_at_fill = position_qty * (mid - avg_entry_price)

                    fills.append(
                        FillEvent(
                            ts=ts,
                            side="sell",
                            price=intent_price,
                            qty=sell_qty,
                            fee=fee,
                            cash_after=cash,
                            position_after=position_qty,
                            unrealized_pnl_at_fill=unrealized_at_fill,
                        )
                    )

            current_account_value = cash + (position_qty * mid)
            if current_account_value > peak_value:
                peak_value = current_account_value
            drawdown = peak_value - current_account_value
            if drawdown > max_drawdown:
                max_drawdown = drawdown
    finally:
        root_logger.setLevel(previous_level)

    final_mid = _to_decimal(snapshots[-1].mid_price)
    final_position_value = position_qty * final_mid
    final_account_value = cash + final_position_value

    avg_entry_for_calc = avg_entry_price if avg_entry_price is not None else Decimal("0")
    net_pnl = final_account_value - starting_capital
    unrealized_pnl = (
        position_qty * (final_mid - avg_entry_for_calc)
        if position_qty > 0 and avg_entry_price is not None
        else Decimal("0")
    )
    realized_pnl = net_pnl - unrealized_pnl + total_fees

    total_fills = len(fills)
    total_days = Decimal(str(max(args.days, 1)))
    avg_fills_per_day = Decimal(total_fills) / total_days

    start_date = snapshots[0].event_ts.date()
    end_date = snapshots[-1].event_ts.date()
    ret_pct = (net_pnl / starting_capital) * Decimal("100")

    print("-----------------------------------------------")
    print(f"BACKTEST RESULTS  [{start_date} to {end_date}]")
    print("-----------------------------------------------")
    print(f"Snapshots replayed:     {len(snapshots)}")
    print(f"Total fills:            {total_fills}  ({buy_count} buys, {sell_count} sells)")
    print(f"Total fees paid:        {_fmt_money(total_fees)}")
    print(f"Realized PnL:           {_fmt_money(realized_pnl)}")
    print(
        "Unrealized PnL:         "
        f"{_fmt_money(unrealized_pnl)}  (position: {position_qty} BTC @ "
        f"${avg_entry_for_calc.quantize(Decimal('0.01'))})"
    )
    print(f"Net PnL:                {_fmt_money(net_pnl)}")
    print(f"Final account value:    {_fmt_money(final_account_value)}  (started {_fmt_money(starting_capital)})")
    print(f"Return:                 {_fmt_percent(ret_pct)}")
    print(f"Max drawdown:           {_fmt_money(max_drawdown)}")
    print(f"Avg fills/day:          {avg_fills_per_day.quantize(Decimal('0.01'))}")
    print("-----------------------------------------------")
    print("Config used:")
    print(
        f"  bid_offset_bps={config.bid_offset_bps}, near_bps={config.ask_sg_near_bps}, "
        f"far_bps={config.ask_sg_far_bps}"
    )
    print("  unified_sizing_enabled=True")
    print("-----------------------------------------------")

    output_path = Path(args.output)
    write_csv(output_path, fills)
    print(f"Wrote fills CSV: {output_path}")

    return 0


def main() -> None:
    args = parse_args()
    raise SystemExit(run_backtest(args))


if __name__ == "__main__":
    main()
