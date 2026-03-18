from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests
from sqlalchemy import select

from core.db.session import SessionLocal
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot

KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_INTERVAL = 60
PAIR = "XBTUSD"
EXCHANGE_SYMBOL = "XXBTZUSD"
EXCHANGE = "kraken"
ADAPTER_NAME = "kraken_rest"
SYMBOL = "XBTUSD"

SPREAD = Decimal("0.10")
HALF_SPREAD = Decimal("0.05")
DEPTH_STEP = Decimal("0.10")
DEFAULT_SIZE = Decimal("1.0")
BATCH_SIZE = 500
MAX_DAYS = 90
REQUEST_TIMEOUT_SECONDS = 20
RATE_LIMIT_SLEEP_SECONDS = 1.1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed historical Kraken OHLC data into order_book_snapshots and market_ticks."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to fetch (default: 30). 720 hourly candles ~= 30 days in one call.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Download and prepare rows without inserting")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip rows whose event_ts already exists for kraken/XBTUSD (default: True)",
    )
    args = parser.parse_args()

    if args.days < 1 or args.days > MAX_DAYS:
        parser.error(f"--days must be between 1 and {MAX_DAYS}")

    return args


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def get_ohlc_rows(payload: dict[str, Any]) -> list[list[Any]]:
    error_list = payload.get("error", [])
    if error_list:
        raise RuntimeError(f"Kraken API returned error(s): {error_list}")

    result = payload.get("result", {})
    pair_key = None
    for key in result:
        if key != "last":
            pair_key = key
            break

    if pair_key is None:
        return []

    rows = result.get(pair_key, [])
    if not isinstance(rows, list):
        return []

    return rows


def fetch_ohlc_batch(since_unix: int) -> list[list[Any]]:
    response = requests.get(
        KRAKEN_OHLC_URL,
        params={
            "pair": PAIR,
            "interval": KRAKEN_INTERVAL,
            "since": since_unix,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    return get_ohlc_rows(payload)


def download_candles(start_unix: int, cutoff_unix: int, target_count: int) -> list[list[Any]]:
    since_unix = start_unix
    calls = 0
    by_ts: dict[int, list[Any]] = {}

    while True:
        rows = fetch_ohlc_batch(since_unix)
        calls += 1
        if not rows:
            break

        for row in rows:
            ts = int(row[0])
            if ts < start_unix:
                continue
            if ts > cutoff_unix:
                continue
            by_ts[ts] = row

        downloaded = len(by_ts)
        print(f"Downloaded {downloaded}/{target_count} candles (1hr intervals)... (API calls: {calls})")

        if downloaded >= target_count:
            break

        last_ts = int(rows[-1][0])
        if last_ts >= cutoff_unix:
            break

        next_since = last_ts
        if next_since <= since_unix:
            next_since = since_unix + (KRAKEN_INTERVAL * 60)
        since_unix = next_since

        time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    ordered = [by_ts[ts] for ts in sorted(by_ts.keys())]
    return ordered


def make_order_book_row(candle: list[Any], ingested_ts: datetime) -> OrderBookSnapshot:
    candle_unix = int(candle[0])
    close = Decimal(str(candle[4]))
    vwap = Decimal(str(candle[5]))

    mid = vwap
    bid_1 = mid - HALF_SPREAD
    ask_1 = mid + HALF_SPREAD
    bid_2 = bid_1 - DEPTH_STEP
    ask_2 = ask_1 + DEPTH_STEP
    bid_3 = bid_2 - DEPTH_STEP
    ask_3 = ask_2 + DEPTH_STEP

    spread_bps = (SPREAD / mid) * Decimal("10000") if mid > 0 else Decimal("0")
    event_ts = datetime.fromtimestamp(candle_unix, tz=timezone.utc)

    return OrderBookSnapshot(
        exchange=EXCHANGE,
        adapter_name=ADAPTER_NAME,
        symbol=SYMBOL,
        exchange_symbol=EXCHANGE_SYMBOL,
        bid_price_1=bid_1,
        bid_size_1=DEFAULT_SIZE,
        ask_price_1=ask_1,
        ask_size_1=DEFAULT_SIZE,
        bid_price_2=bid_2,
        bid_size_2=DEFAULT_SIZE,
        ask_price_2=ask_2,
        ask_size_2=DEFAULT_SIZE,
        bid_price_3=bid_3,
        bid_size_3=DEFAULT_SIZE,
        ask_price_3=ask_3,
        ask_size_3=DEFAULT_SIZE,
        spread=SPREAD,
        spread_bps=spread_bps,
        mid_price=mid,
        event_ts=event_ts,
        ingested_ts=ingested_ts,
    )


def make_market_tick_row(candle: list[Any], ingested_ts: datetime) -> MarketTick:
    candle_unix = int(candle[0])
    close = Decimal(str(candle[4]))
    vwap = Decimal(str(candle[5]))

    mid = vwap
    bid = mid - HALF_SPREAD
    ask = mid + HALF_SPREAD
    event_ts = datetime.fromtimestamp(candle_unix, tz=timezone.utc)

    return MarketTick(
        exchange=EXCHANGE,
        adapter_name=ADAPTER_NAME,
        symbol=SYMBOL,
        exchange_symbol=EXCHANGE_SYMBOL,
        bid_price=bid,
        ask_price=ask,
        mid_price=mid,
        last_price=close,
        bid_size=DEFAULT_SIZE,
        ask_size=DEFAULT_SIZE,
        event_ts=event_ts,
        ingested_ts=ingested_ts,
        sequence_id=None,
    )


def build_rows(candles: list[list[Any]]) -> tuple[list[OrderBookSnapshot], list[MarketTick]]:
    now = datetime.now(timezone.utc)
    books = [make_order_book_row(candle, now) for candle in candles]
    ticks = [make_market_tick_row(candle, now) for candle in candles]
    return books, ticks


def dedupe_chunk(
    session: Any,
    books_chunk: list[OrderBookSnapshot],
    ticks_chunk: list[MarketTick],
    skip_existing: bool,
) -> tuple[list[OrderBookSnapshot], list[MarketTick], int, int]:
    if not skip_existing or (not books_chunk and not ticks_chunk):
        return books_chunk, ticks_chunk, 0, 0

    ts_values = [row.event_ts for row in books_chunk]
    min_ts = min(ts_values)
    max_ts = max(ts_values)

    existing_book_ts = set(
        session.execute(
            select(OrderBookSnapshot.event_ts).where(
                OrderBookSnapshot.exchange == EXCHANGE,
                OrderBookSnapshot.symbol == SYMBOL,
                OrderBookSnapshot.event_ts >= min_ts,
                OrderBookSnapshot.event_ts <= max_ts,
            )
        ).scalars()
    )
    existing_tick_ts = set(
        session.execute(
            select(MarketTick.event_ts).where(
                MarketTick.exchange == EXCHANGE,
                MarketTick.symbol == SYMBOL,
                MarketTick.event_ts >= min_ts,
                MarketTick.event_ts <= max_ts,
            )
        ).scalars()
    )

    filtered_books = [row for row in books_chunk if row.event_ts not in existing_book_ts]
    filtered_ticks = [row for row in ticks_chunk if row.event_ts not in existing_tick_ts]

    skipped_books = len(books_chunk) - len(filtered_books)
    skipped_ticks = len(ticks_chunk) - len(filtered_ticks)
    return filtered_books, filtered_ticks, skipped_books, skipped_ticks


def insert_rows(
    books: list[OrderBookSnapshot],
    ticks: list[MarketTick],
    dry_run: bool,
    skip_existing: bool,
) -> tuple[int, int, int]:
    inserted_books = 0
    inserted_ticks = 0
    skipped_duplicates = 0

    books_chunks = chunked(books, BATCH_SIZE)
    ticks_chunks = chunked(ticks, BATCH_SIZE)
    total_chunks = max(len(books_chunks), len(ticks_chunks))

    with SessionLocal() as session:
        for idx in range(total_chunks):
            books_chunk = books_chunks[idx] if idx < len(books_chunks) else []
            ticks_chunk = ticks_chunks[idx] if idx < len(ticks_chunks) else []

            filtered_books, filtered_ticks, skipped_books, skipped_ticks = dedupe_chunk(
                session,
                books_chunk,
                ticks_chunk,
                skip_existing,
            )
            skipped_duplicates += skipped_books + skipped_ticks

            if dry_run:
                inserted_books += len(filtered_books)
                inserted_ticks += len(filtered_ticks)
                print(
                    f"Chunk {idx + 1}/{total_chunks}: dry-run prepared "
                    f"{len(filtered_books)} books, {len(filtered_ticks)} ticks "
                    f"(skipped {skipped_books + skipped_ticks} duplicates)"
                )
                continue

            if not filtered_books and not filtered_ticks:
                print(
                    f"Chunk {idx + 1}/{total_chunks}: inserted 0 books, 0 ticks "
                    f"(skipped {skipped_books + skipped_ticks} duplicates)"
                )
                continue

            try:
                if filtered_books:
                    session.bulk_save_objects(filtered_books)
                if filtered_ticks:
                    session.bulk_save_objects(filtered_ticks)
                session.commit()
            except Exception:
                session.rollback()
                raise

            inserted_books += len(filtered_books)
            inserted_ticks += len(filtered_ticks)
            print(
                f"Chunk {idx + 1}/{total_chunks}: inserted "
                f"{len(filtered_books)} books, {len(filtered_ticks)} ticks "
                f"(skipped {skipped_books + skipped_ticks} duplicates)"
            )

    return inserted_books, inserted_ticks, skipped_duplicates


def main() -> None:
    args = parse_args()

    now_unix = int(time.time())
    start_unix = now_unix - (args.days * 86400)
    cutoff_unix = now_unix - 120
    target_count = args.days * 24

    print(
        f"Starting seed: days={args.days}, dry_run={args.dry_run}, "
        f"skip_existing={args.skip_existing}"
    )

    candles = download_candles(start_unix=start_unix, cutoff_unix=cutoff_unix, target_count=target_count)
    if not candles:
        print("No candles downloaded; nothing to do.")
        return

    if len(candles) < 600:
        print(
            "Warning: downloaded fewer candles than requested target. "
            "Expected approximately 720 hourly candles for a full 30-day backfill from Kraken OHLC."
        )

    books, ticks = build_rows(candles)
    inserted_books, inserted_ticks, skipped_duplicates = insert_rows(
        books,
        ticks,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
    )

    first_ts = datetime.fromtimestamp(int(candles[0][0]), tz=timezone.utc)
    last_ts = datetime.fromtimestamp(int(candles[-1][0]), tz=timezone.utc)

    print(
        f"Seeded {inserted_books} order_book_snapshots and {inserted_ticks} market_ticks\n"
        f"Date range: {first_ts.date()} to {last_ts.date()}\n"
        f"Skipped {skipped_duplicates} duplicates"
    )


if __name__ == "__main__":
    main()
