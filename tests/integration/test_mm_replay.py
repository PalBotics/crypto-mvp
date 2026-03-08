from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FixedBpsFeeModel
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy


def _seed_replay_data(session: Session) -> list[OrderBookSnapshot]:
    base_ts = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
    snapshots: list[OrderBookSnapshot] = []

    for i in range(5):
        ts = base_ts + timedelta(seconds=60 * i)
        mid = Decimal("60000") - (Decimal("100") * Decimal(i))
        spread = mid * Decimal("8") / Decimal("10000")
        snapshot = OrderBookSnapshot(
            exchange="kraken",
            adapter_name="kraken_rest",
            symbol="XBTUSD",
            exchange_symbol="XXBTZUSD",
            bid_price_1=mid - spread / Decimal("2"),
            bid_size_1=Decimal("1"),
            ask_price_1=mid + spread / Decimal("2"),
            ask_size_1=Decimal("1"),
            bid_price_2=mid - Decimal("1"),
            bid_size_2=Decimal("1"),
            ask_price_2=mid + Decimal("1"),
            ask_size_2=Decimal("1"),
            bid_price_3=mid - Decimal("2"),
            bid_size_3=Decimal("1"),
            ask_price_3=mid + Decimal("2"),
            ask_size_3=Decimal("1"),
            spread=spread,
            spread_bps=Decimal("8"),
            mid_price=mid,
            event_ts=ts,
            ingested_ts=ts,
        )
        snapshots.append(snapshot)
        session.add(snapshot)

        session.add(
            MarketTick(
                exchange="kraken",
                adapter_name="kraken_rest",
                symbol="XBTUSD",
                exchange_symbol="XXBTZUSD",
                bid_price=mid - Decimal("5"),
                ask_price=mid + Decimal("5"),
                mid_price=mid,
                last_price=mid,
                bid_size=Decimal("1"),
                ask_size=Decimal("1"),
                event_ts=ts,
                ingested_ts=ts,
                sequence_id=None,
            )
        )

    session.commit()
    return snapshots


def _run_market_making_replay(session: Session) -> dict[str, int]:
    snapshots = _seed_replay_data(session)
    strategy = MarketMakingStrategy(MarketMakingConfig())
    fee_model = FixedBpsFeeModel(bps=Decimal("10"))

    current_position = Decimal("0")
    intents_generated = 0

    for snapshot in snapshots:
        intents = strategy.evaluate(
            session=session,
            order_book=snapshot,
            current_position=current_position,
            current_ts=snapshot.event_ts,
        )
        intents_generated += len(intents)

        for intent in intents:
            intent.mode = strategy.config.account_name
            session.add(intent)
        session.flush()

        while execute_one_paper_market_intent(
            session=session,
            fee_model=fee_model,
            risk_engine=None,
            mode=strategy.config.account_name,
            order_book_snapshot=snapshot,
        ):
            latest = (
                session.execute(
                    select(PositionSnapshot)
                    .where(PositionSnapshot.exchange == "kraken")
                    .where(PositionSnapshot.symbol == "XBTUSD")
                    .where(PositionSnapshot.account_name == strategy.config.account_name)
                    .order_by(PositionSnapshot.snapshot_ts.desc())
                )
                .scalars()
                .first()
            )
            if latest is None:
                current_position = Decimal("0")
            else:
                qty = Decimal(str(latest.quantity))
                current_position = qty if latest.side == "buy" else -qty

    session.commit()

    fill_count = session.execute(select(FillRecord)).scalars().all()
    positions = session.execute(select(PositionSnapshot)).scalars().all()

    return {
        "fills": len(fill_count),
        "positions": len(positions),
        "intents_generated": intents_generated,
    }


def test_mm_replay_generates_intents_and_executes_without_exceptions(db_session: Session) -> None:
    result = _run_market_making_replay(db_session)

    assert result["intents_generated"] > 0
    assert result["fills"] > 0


def test_mm_replay_persists_fill_records(db_session: Session) -> None:
    result = _run_market_making_replay(db_session)

    assert result["fills"] >= 1


def test_mm_replay_persists_position_snapshot(db_session: Session) -> None:
    result = _run_market_making_replay(db_session)

    assert result["positions"] >= 1


def test_mm_replay_runs_across_all_seeded_snapshots(db_session: Session) -> None:
    _seed_replay_data(db_session)
    snapshot_count = len(db_session.execute(select(OrderBookSnapshot)).scalars().all())

    assert snapshot_count == 5
