from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.backtester.replay import ReplayConfig, run_replay
from core.models.fill_record import FillRecord
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord

EXCHANGE = "binance"
SPOT_SYMBOL = "BTC-USD"
PERP_SYMBOL = "BTC-PERP"


def _seed_market_ticks(session: Session) -> None:
    now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    for symbol in (SPOT_SYMBOL, PERP_SYMBOL):
        session.add(
            MarketTick(
                exchange=EXCHANGE,
                adapter_name=EXCHANGE,
                symbol=symbol,
                exchange_symbol=symbol,
                bid_price=Decimal("49990"),
                ask_price=Decimal("50010"),
                mid_price=Decimal("50000"),
                last_price=Decimal("50000"),
                bid_size=None,
                ask_size=None,
                event_ts=now,
                ingested_ts=now,
                sequence_id=None,
            )
        )
    session.commit()


def _seed_funding_snapshots(session: Session) -> tuple[datetime, datetime]:
    start = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    rates = [
        Decimal("0.0005"),
        Decimal("0.0003"),
        Decimal("0.00004"),
        Decimal("0.0005"),
        Decimal("0.00001"),
    ]

    for i, rate in enumerate(rates):
        ts = start + timedelta(minutes=i)
        session.add(
            FundingRateSnapshot(
                exchange=EXCHANGE,
                adapter_name=EXCHANGE,
                symbol=PERP_SYMBOL,
                exchange_symbol=PERP_SYMBOL,
                funding_rate=rate,
                funding_interval_hours=8,
                predicted_funding_rate=None,
                mark_price=Decimal("50000"),
                index_price=Decimal("49995"),
                next_funding_ts=None,
                event_ts=ts,
                ingested_ts=ts,
            )
        )

    session.commit()
    end = start + timedelta(minutes=len(rates) - 1)
    return start, end


def _fill_count_for_run(session: Session, run_id: str) -> int:
    stmt = (
        select(func.count(FillRecord.id))
        .select_from(FillRecord)
        .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
        .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
        .where(OrderIntent.mode == run_id)
    )
    return int(session.execute(stmt).scalar_one())


def test_run_replay_uses_funding_snapshots_and_isolates_runs(db_session: Session) -> None:
    _seed_market_ticks(db_session)
    start_ts, end_ts = _seed_funding_snapshots(db_session)

    config = ReplayConfig(
        exchange=EXCHANGE,
        spot_symbol=SPOT_SYMBOL,
        perp_symbol=PERP_SYMBOL,
        start_ts=start_ts,
        end_ts=end_ts,
        entry_funding_rate_threshold=Decimal("0.0001"),
        exit_funding_rate_threshold=Decimal("0.00005"),
        position_size=Decimal("1"),
        max_data_age_seconds=3600,
        max_notional_per_symbol=Decimal("1000000"),
        min_entry_funding_rate=Decimal("0.0001"),
        fee_bps=Decimal("10"),
    )

    first = run_replay(db_session, config)

    assert first.snapshots_replayed == 5
    assert first.iterations_with_entry >= 1
    assert first.iterations_with_exit >= 1
    assert first.total_fills > 0
    assert isinstance(first.total_realized_pnl, Decimal)
    assert UUID(first.run_id)

    second = run_replay(db_session, config)

    assert second.run_id != first.run_id
    assert UUID(second.run_id)

    first_fill_count = _fill_count_for_run(db_session, first.run_id)
    second_fill_count = _fill_count_for_run(db_session, second.run_id)

    assert first_fill_count > 0
    assert second_fill_count > 0
    assert first_fill_count == first.total_fills
    assert second_fill_count == second.total_fills
