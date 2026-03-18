from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from core.db.session import SessionLocal
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot

EXCHANGE_SYMBOL = "XXBTZUSD"
EXCHANGE = "kraken"
ADAPTER_NAME = "kraken_rest"
SYMBOL = "XBTUSD"

SPREAD = Decimal("0.10")
HALF_SPREAD = Decimal("0.05")
DEPTH_STEP = Decimal("0.10")
DEFAULT_SIZE = Decimal("1.0")
BATCH_SIZE = 500


def parse_date_utc(date_text: str) -> datetime:
    parsed = datetime.strptime(date_text, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Kraken OHLCV CSV data into order_book_snapshots and market_ticks."
    )
    parser.add_argument("--file", type=str, required=True, help="Path to CSV file")
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Only import rows on or after this UTC date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Only import rows before this UTC date (YYYY-MM-DD)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and count rows without inserting")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip rows whose event_ts already exists for kraken/XBTUSD (default: True)",
    )

    args = parser.parse_args()

    if args.start:
        parse_date_utc(args.start)
    if args.end:
        parse_date_utc(args.end)

    if args.start and args.end:
        start_dt = parse_date_utc(args.start)
        end_dt = parse_date_utc(args.end)
        if end_dt <= start_dt:
            parser.error("--end must be greater than --start")

    return args


def make_order_book_row(timestamp_unix: int, high: Decimal, low: Decimal, close: Decimal, ingested_ts: datetime) -> OrderBookSnapshot:
    event_ts = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)

    # CSV has no VWAP; midpoint is derived from high/low.
    mid = (high + low) / Decimal("2")
    bid_1 = mid - HALF_SPREAD
    ask_1 = mid + HALF_SPREAD
    bid_2 = bid_1 - DEPTH_STEP
    ask_2 = ask_1 + DEPTH_STEP
    bid_3 = bid_2 - DEPTH_STEP
    ask_3 = ask_2 + DEPTH_STEP

    spread_bps = (SPREAD / mid) * Decimal("10000") if mid > 0 else Decimal("0")

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


def make_market_tick_row(timestamp_unix: int, high: Decimal, low: Decimal, close: Decimal, ingested_ts: datetime) -> MarketTick:
    event_ts = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)

    # CSV has no VWAP; midpoint is derived from high/low.
    mid = (high + low) / Decimal("2")
    bid = mid - HALF_SPREAD
    ask = mid + HALF_SPREAD

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


def flush_chunk(
    session: Any,
    books_chunk: list[OrderBookSnapshot],
    ticks_chunk: list[MarketTick],
    dry_run: bool,
    skip_existing: bool,
    chunk_index: int,
) -> tuple[int, int, int]:
    filtered_books, filtered_ticks, skipped_books, skipped_ticks = dedupe_chunk(
        session,
        books_chunk,
        ticks_chunk,
        skip_existing,
    )

    if dry_run:
        inserted_books = len(filtered_books)
        inserted_ticks = len(filtered_ticks)
    else:
        if filtered_books:
            session.bulk_save_objects(filtered_books)
        if filtered_ticks:
            session.bulk_save_objects(filtered_ticks)
        session.commit()
        inserted_books = len(filtered_books)
        inserted_ticks = len(filtered_ticks)

    skipped_total = skipped_books + skipped_ticks
    print(
        f"Chunk {chunk_index}: inserted {inserted_books} books, {inserted_ticks} ticks "
        f"(skipped {skipped_total} duplicates)"
    )
    return inserted_books, inserted_ticks, skipped_total


def process_csv(
    file_path: str,
    start_dt: datetime | None,
    end_dt: datetime | None,
    dry_run: bool,
    skip_existing: bool,
) -> tuple[int, int, int, int, datetime | None, datetime | None]:
    inserted_books_total = 0
    inserted_ticks_total = 0
    skipped_duplicates_total = 0
    total_rows_in_file = 0

    min_event_ts: datetime | None = None
    max_event_ts: datetime | None = None

    books_chunk: list[OrderBookSnapshot] = []
    ticks_chunk: list[MarketTick] = []
    chunk_index = 0

    with SessionLocal() as session:
        with open(file_path, "r", newline="", encoding="utf-8") as csv_file:
            reader = csv.reader(csv_file)
            for row in reader:
                total_rows_in_file += 1
                if not row:
                    continue
                if len(row) != 7:
                    raise ValueError(f"Invalid row with {len(row)} columns (expected 7): {row}")

                timestamp_unix = int(row[0])
                open_price = Decimal(str(row[1]))
                high = Decimal(str(row[2]))
                low = Decimal(str(row[3]))
                close = Decimal(str(row[4]))
                volume = Decimal(str(row[5]))
                trade_count = int(row[6])

                _ = open_price
                _ = volume
                _ = trade_count

                event_ts = datetime.fromtimestamp(timestamp_unix, tz=timezone.utc)

                if start_dt is not None and event_ts < start_dt:
                    continue
                if end_dt is not None and event_ts >= end_dt:
                    continue

                if min_event_ts is None or event_ts < min_event_ts:
                    min_event_ts = event_ts
                if max_event_ts is None or event_ts > max_event_ts:
                    max_event_ts = event_ts

                now = datetime.now(timezone.utc)
                books_chunk.append(make_order_book_row(timestamp_unix, high, low, close, now))
                ticks_chunk.append(make_market_tick_row(timestamp_unix, high, low, close, now))

                if len(books_chunk) >= BATCH_SIZE:
                    chunk_index += 1
                    try:
                        inserted_books, inserted_ticks, skipped = flush_chunk(
                            session,
                            books_chunk,
                            ticks_chunk,
                            dry_run,
                            skip_existing,
                            chunk_index,
                        )
                    except Exception:
                        if not dry_run:
                            session.rollback()
                        raise

                    inserted_books_total += inserted_books
                    inserted_ticks_total += inserted_ticks
                    skipped_duplicates_total += skipped
                    books_chunk = []
                    ticks_chunk = []

            if books_chunk or ticks_chunk:
                chunk_index += 1
                try:
                    inserted_books, inserted_ticks, skipped = flush_chunk(
                        session,
                        books_chunk,
                        ticks_chunk,
                        dry_run,
                        skip_existing,
                        chunk_index,
                    )
                except Exception:
                    if not dry_run:
                        session.rollback()
                    raise

                inserted_books_total += inserted_books
                inserted_ticks_total += inserted_ticks
                skipped_duplicates_total += skipped

    return (
        inserted_books_total,
        inserted_ticks_total,
        skipped_duplicates_total,
        total_rows_in_file,
        min_event_ts,
        max_event_ts,
    )


def main() -> None:
    args = parse_args()

    start_dt = parse_date_utc(args.start) if args.start else None
    end_dt = parse_date_utc(args.end) if args.end else None

    (
        inserted_books,
        inserted_ticks,
        skipped_duplicates,
        total_rows_in_file,
        min_event_ts,
        max_event_ts,
    ) = process_csv(
        file_path=args.file,
        start_dt=start_dt,
        end_dt=end_dt,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
    )

    if min_event_ts is not None and max_event_ts is not None:
        date_range_text = f"{min_event_ts.date()} to {max_event_ts.date()}"
    else:
        date_range_text = "n/a"

    print(
        f"Seeded {inserted_books} order_book_snapshots and {inserted_ticks} market_ticks\n"
        f"Date range: {date_range_text}\n"
        f"Skipped {skipped_duplicates} duplicates\n"
        f"Total rows in file: {total_rows_in_file}"
    )


if __name__ == "__main__":
    main()
