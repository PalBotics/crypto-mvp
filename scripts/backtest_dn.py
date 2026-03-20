from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import requests

OKX_FUNDING_URL = "https://www.okx.com/api/v5/public/funding-rate-history"
REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1


@dataclass(frozen=True)
class HourlyCandle:
    ts: datetime
    close: Decimal


@dataclass(frozen=True)
class FundingEvent:
    ts: datetime
    funding_rate_8h: Decimal
    hourly_rate: Decimal


@dataclass(frozen=True)
class FillEvent:
    ts: datetime
    action: str
    eth_price: Decimal
    funding_apr: Decimal
    margin_posted: Decimal
    fee: Decimal


@dataclass(frozen=True)
class HourlyPnlRow:
    ts: datetime
    eth_price: Decimal
    funding_apr: Decimal
    in_position: bool
    cash: Decimal
    unrealized_pnl: Decimal
    total_funding_income_cumulative: Decimal
    account_value: Decimal


class BacktestError(Exception):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest delta-neutral funding capture strategy")
    parser.add_argument("--start", type=str, default="2024-10-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default="2024-12-31", help="End date YYYY-MM-DD")
    parser.add_argument("--capital", type=str, default="2500.0", help="Starting capital in USD")
    parser.add_argument("--contract-qty", type=int, default=8, help="Number of 0.10 ETH contracts")
    parser.add_argument("--entry-apr", type=str, default="5.0", help="Entry threshold APR percent")
    parser.add_argument("--exit-apr", type=str, default="2.0", help="Exit threshold APR percent")
    parser.add_argument("--margin-rate", type=str, default="0.10", help="Initial margin rate")
    parser.add_argument("--fee-bps", type=str, default="5.0", help="Taker fee in bps per leg")
    parser.add_argument("--spot-csv", type=str, default="testdata/ETHUSD_60.csv", help="Path to hourly spot CSV")
    parser.add_argument("--funding-rate", type=str, default=None, help="Constant hourly funding rate (synthetic) or live from API (default)")
    parser.add_argument("--output", type=str, default="backtest_results_dn.csv", help="CSV output path")
    return parser.parse_args()


def parse_date_utc(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}"


def pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def quant_decimal(value: Decimal, places: str = "0.00000001") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def request_json(url: str, *, params: dict[str, object]) -> object:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # pragma: no cover - network failures are runtime-specific
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS)
            else:
                break

    raise BacktestError(f"API request failed after {MAX_RETRIES} retries: {url} :: {last_error}")


def fetch_spot_candles_from_csv(csv_path: str, start_dt: datetime, end_exclusive: datetime) -> list[HourlyCandle]:
    print(f"Loading ETH spot data from {csv_path}...")
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise BacktestError(
            f"Spot data file not found: {csv_path}\n"
            "To extract from the Kraken zip: Extract testdata/Kraken_OHLCVT.zip and ensure ETHUSD_60.csv is present."
        )

    candles_by_ts: dict[int, HourlyCandle] = {}
    start_unix = int(start_dt.timestamp())
    end_unix = int(end_exclusive.timestamp())

    with csv_file.open("r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        row_count = 0
        for row in reader:
            row_count += 1
            if len(row) < 5:
                continue
            try:
                ts_unix = int(float(row[0]))
                close = Decimal(str(row[4]))
            except (ValueError, IndexError):
                continue

            if ts_unix < start_unix or ts_unix >= end_unix:
                continue

            candle_ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
            candles_by_ts[ts_unix] = HourlyCandle(ts=candle_ts, close=close)

    candles = [candles_by_ts[key] for key in sorted(candles_by_ts)]
    if not candles:
        raise BacktestError(
            f"No candles loaded from {csv_path} for period {start_dt.strftime('%Y-%m-%d')} "
            f"through {(end_exclusive - timedelta(days=1)).strftime('%Y-%m-%d')}"
        )

    print(f"  Loaded {len(candles)} hourly candles from CSV")
    return candles


def fetch_okx_funding_events(start_dt: datetime, end_exclusive: datetime) -> list[FundingEvent]:
    print("Fetching ETH perpetual funding data from OKX...")
    start_ms = int((start_dt - timedelta(hours=8)).timestamp() * 1000)
    end_ms = int(end_exclusive.timestamp() * 1000) - 1
    events_by_ts: dict[int, FundingEvent] = {}
    batch = 0
    before_cursor: str | None = None

    while True:
        batch += 1
        params: dict[str, object] = {
            "instId": "ETH-USD-SWAP",
            "limit": 100,
        }
        if before_cursor is not None:
            params["before"] = before_cursor

        payload = request_json(OKX_FUNDING_URL, params=params)
        if not isinstance(payload, dict):
            raise BacktestError("Unexpected OKX funding response payload")

        data = payload.get("data", [])
        if not isinstance(data, list):
            raise BacktestError("Unexpected OKX data payload")

        if not data:
            break

        for row in data:
            try:
                funding_ms = int(row["fundingTime"])
                if funding_ms < start_ms or funding_ms > end_ms:
                    continue
                rate_8h = Decimal(str(row["fundingRate"]))
                hourly_rate = rate_8h / Decimal("8")
                events_by_ts[funding_ms] = FundingEvent(
                    ts=datetime.fromtimestamp(funding_ms / 1000, tz=timezone.utc),
                    funding_rate_8h=rate_8h,
                    hourly_rate=hourly_rate,
                )
            except (KeyError, ValueError, TypeError):
                continue

        print(f"  OKX batch {batch}: collected {len(events_by_ts)} funding events")
        if len(data) < 100:
            break
        before_cursor = data[-1]["fundingTime"]

    events = [events_by_ts[key] for key in sorted(events_by_ts)]
    if not events:
        raise BacktestError("No OKX funding events returned for requested period")
    return events


def annualize_hourly_rate(hourly_rate: Decimal) -> Decimal:
    return hourly_rate * Decimal("24") * Decimal("365") * Decimal("100")


def write_hourly_csv(path: Path, rows: list[HourlyPnlRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "ts",
                "eth_price",
                "funding_apr",
                "in_position",
                "cash",
                "unrealized_pnl",
                "total_funding_income_cumulative",
                "account_value",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.ts.isoformat(),
                    str(quant_decimal(row.eth_price)),
                    str(quant_decimal(row.funding_apr)),
                    str(row.in_position),
                    str(quant_decimal(row.cash)),
                    str(quant_decimal(row.unrealized_pnl)),
                    str(quant_decimal(row.total_funding_income_cumulative)),
                    str(quant_decimal(row.account_value)),
                ]
            )


def run_backtest(args: argparse.Namespace) -> int:
    start_dt = parse_date_utc(args.start)
    end_exclusive = parse_date_utc(args.end) + timedelta(days=1)
    if end_exclusive <= start_dt:
        raise BacktestError("--end must be on or after --start")

    capital = Decimal(str(args.capital))
    contract_qty = int(args.contract_qty)
    entry_apr_threshold = Decimal(str(args.entry_apr))
    exit_apr_threshold = Decimal(str(args.exit_apr))
    margin_rate = Decimal(str(args.margin_rate))
    fee_bps = Decimal(str(args.fee_bps))
    fee_rate = fee_bps / Decimal("10000")
    spot_qty = Decimal(contract_qty) * Decimal("0.10")

    candles = fetch_spot_candles_from_csv(args.spot_csv, start_dt, end_exclusive)
    
    # Use synthetic funding rate if provided, otherwise fetch from API
    if args.funding_rate is not None:
        print(f"Using synthetic hourly funding rate: {args.funding_rate}")
        synthetic_rate = Decimal(str(args.funding_rate))
        funding_events = [
            FundingEvent(
                ts=candle.ts,
                funding_rate_8h=synthetic_rate * Decimal("8"),
                hourly_rate=synthetic_rate,
            )
            for candle in candles
        ]
    else:
        funding_events = fetch_okx_funding_events(start_dt, end_exclusive)

    cash = capital
    in_position = False
    entry_eth_price: Decimal | None = None
    entry_funding_apr: Decimal | None = None
    margin_posted = Decimal("0")
    total_funding_income = Decimal("0")
    total_fees = Decimal("0")
    net_directional_pnl_total = Decimal("0")
    entries = 0
    exits = 0
    hours_in_position = 0
    in_position_aprs: list[Decimal] = []
    fills: list[FillEvent] = []
    hourly_rows: list[HourlyPnlRow] = []

    funding_index = 0
    last_hourly_rate = Decimal("0")
    peak_funding_apr = Decimal("-999999")

    peak_account_value = capital
    max_drawdown = Decimal("0")

    first_price = candles[0].close
    last_price = candles[-1].close

    for candle in candles:
        eth_price = candle.close
        while funding_index < len(funding_events) and funding_events[funding_index].ts <= candle.ts:
            last_hourly_rate = funding_events[funding_index].hourly_rate
            funding_index += 1

        funding_apr = annualize_hourly_rate(last_hourly_rate)
        if funding_apr > peak_funding_apr:
            peak_funding_apr = funding_apr

        if not in_position and funding_apr >= entry_apr_threshold:
            entry_fee = spot_qty * eth_price * fee_rate * Decimal("2")
            margin_posted = spot_qty * eth_price * margin_rate
            cash -= entry_fee + margin_posted
            total_fees += entry_fee
            in_position = True
            entry_eth_price = eth_price
            entry_funding_apr = funding_apr
            entries += 1
            fills.append(
                FillEvent(
                    ts=candle.ts,
                    action="enter",
                    eth_price=eth_price,
                    funding_apr=funding_apr,
                    margin_posted=margin_posted,
                    fee=entry_fee,
                )
            )

        net_directional = Decimal("0")
        unrealized_pnl = Decimal("0")

        if in_position:
            hours_in_position += 1
            in_position_aprs.append(funding_apr)
            notional = spot_qty * eth_price
            hourly_income = notional * last_hourly_rate
            total_funding_income += hourly_income
            cash += hourly_income

            assert entry_eth_price is not None
            spot_pnl = (eth_price - entry_eth_price) * spot_qty
            perp_pnl = (entry_eth_price - eth_price) * spot_qty
            net_directional = spot_pnl + perp_pnl
            unrealized_pnl = net_directional + total_funding_income

            if funding_apr < exit_apr_threshold:
                exit_fee = spot_qty * eth_price * fee_rate * Decimal("2")
                cash += margin_posted
                cash -= exit_fee
                total_fees += exit_fee
                total_exit_directional = net_directional
                net_directional_pnl_total += total_exit_directional
                in_position = False
                margin_posted = Decimal("0")
                entry_eth_price = None
                entry_funding_apr = None
                exits += 1
                fills.append(
                    FillEvent(
                        ts=candle.ts,
                        action="exit",
                        eth_price=eth_price,
                        funding_apr=funding_apr,
                        margin_posted=Decimal("0"),
                        fee=exit_fee,
                    )
                )
                net_directional = Decimal("0")
                unrealized_pnl = Decimal("0")

        account_value = cash + margin_posted + net_directional
        if account_value > peak_account_value:
            peak_account_value = account_value
        drawdown = peak_account_value - account_value
        if drawdown > max_drawdown:
            max_drawdown = drawdown

        hourly_rows.append(
            HourlyPnlRow(
                ts=candle.ts,
                eth_price=eth_price,
                funding_apr=funding_apr,
                in_position=in_position,
                cash=cash,
                unrealized_pnl=unrealized_pnl,
                total_funding_income_cumulative=total_funding_income,
                account_value=account_value,
            )
        )

    if in_position:
        eth_price = candles[-1].close
        assert entry_eth_price is not None
        spot_pnl = (eth_price - entry_eth_price) * spot_qty
        perp_pnl = (entry_eth_price - eth_price) * spot_qty
        net_directional = spot_pnl + perp_pnl
        exit_fee = spot_qty * eth_price * fee_rate * Decimal("2")
        cash += margin_posted
        cash -= exit_fee
        total_fees += exit_fee
        net_directional_pnl_total += net_directional
        exits += 1
        fills.append(
            FillEvent(
                ts=candles[-1].ts,
                action="force_exit",
                eth_price=eth_price,
                funding_apr=annualize_hourly_rate(last_hourly_rate),
                margin_posted=Decimal("0"),
                fee=exit_fee,
            )
        )
        margin_posted = Decimal("0")
        in_position = False

    final_account_value = cash
    net_pnl = final_account_value - capital
    days = Decimal(str((end_exclusive - start_dt).days))
    total_hours = len(candles)
    period_return_pct = (net_pnl / capital) * Decimal("100") if capital != 0 else Decimal("0")
    annualized_return_pct = (net_pnl / capital) * (Decimal("365") / days) * Decimal("100") if capital != 0 and days != 0 else Decimal("0")
    funding_income_annualized = (total_funding_income / capital) * (Decimal("365") / days) * Decimal("100") if capital != 0 and days != 0 else Decimal("0")
    avg_funding_apr = sum(in_position_aprs, Decimal("0")) / Decimal(len(in_position_aprs)) if in_position_aprs else Decimal("0")
    hours_pct = (Decimal(hours_in_position) / Decimal(total_hours) * Decimal("100")) if total_hours else Decimal("0")

    print("=" * 48)
    print(f"DELTA-NEUTRAL BACKTEST  [{args.start} to {args.end}]")
    print("=" * 48)
    print(f"Period:                 {int(days)} days")
    print(f"ETH price range:        {money(first_price)} --> {money(last_price)}")
    print(f"Capital:                {money(capital)}")
    print(f"Contract qty:           {contract_qty} ({quant_decimal(spot_qty, '0.00')} ETH)")
    print(f"Entry threshold:        {pct(entry_apr_threshold)} APR")
    print(f"Exit threshold:         {pct(exit_apr_threshold)} APR")
    print("-" * 48)
    print(f"Entries:                {entries}")
    print(f"Exits:                  {exits}")
    print(f"Hours in position:      {hours_in_position} / {total_hours} total ({pct(hours_pct)})")
    print("-" * 48)
    print(f"Total funding income:   {money(total_funding_income)}")
    print(f"Total fees paid:        {money(total_fees)}")
    print(f"Net directional PnL:    {money(net_directional_pnl_total)}  (should be near $0)")
    print(f"Net PnL:                {money(net_pnl)}")
    print(f"Return (period):        {pct(period_return_pct)}")
    print(f"Return (annualized):    {pct(annualized_return_pct)}")
    print(f"Funding income (ann.):  {pct(funding_income_annualized)}")
    print(f"Max drawdown:           {money(max_drawdown)}")
    print("=" * 48)
    print(f"Avg funding APR (in-position hours): {pct(avg_funding_apr)}")
    print(f"Peak funding APR seen:  {pct(peak_funding_apr)}")
    print("=" * 48)

    write_hourly_csv(Path(args.output), hourly_rows)
    print(f"Wrote hourly PnL CSV:   {args.output}")

    return 0


def main() -> int:
    try:
        return run_backtest(parse_args())
    except BacktestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())