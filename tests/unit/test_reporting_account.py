from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models.fill_record import FillRecord
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.reporting.account import compute_paper_account_snapshot


def _book(ts: datetime) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange="kraken",
        adapter_name="kraken_rest",
        symbol="XBTUSD",
        exchange_symbol="XXBTZUSD",
        bid_price_1=Decimal("70490"),
        bid_size_1=Decimal("1"),
        ask_price_1=Decimal("70510"),
        ask_size_1=Decimal("1"),
        bid_price_2=None,
        bid_size_2=None,
        ask_price_2=None,
        ask_size_2=None,
        bid_price_3=None,
        bid_size_3=None,
        ask_price_3=None,
        ask_size_3=None,
        spread=Decimal("20"),
        spread_bps=Decimal("2.84"),
        mid_price=Decimal("70500"),
        event_ts=ts,
        ingested_ts=ts,
    )


def test_compute_account_uses_latest_position_for_account(db_session) -> None:
    now = datetime(2026, 3, 10, 10, 0, tzinfo=timezone.utc)

    db_session.add(
        PnLSnapshot(
            id=uuid.uuid4(),
            strategy_name="paper_mm",
            symbol="XBTUSD",
            realized_pnl=Decimal("1.23"),
            unrealized_pnl=Decimal("0"),
            funding_pnl=Decimal("0"),
            fee_pnl=Decimal("0"),
            gross_pnl=Decimal("1.23"),
            net_pnl=Decimal("1.23"),
            snapshot_ts=now,
        )
    )

    intent = OrderIntent(
        id=uuid.uuid4(),
        mode="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.0010"),
        limit_price=Decimal("70330"),
        reduce_only=False,
        post_only=False,
        status="filled",
        created_ts=now,
    )
    order = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange="kraken",
        symbol="XBTUSD",
        exchange_order_id=str(uuid.uuid4()),
        side="buy",
        order_type="limit",
        status="filled",
        submitted_price=Decimal("70330"),
        submitted_qty=Decimal("0.0010"),
        filled_qty=Decimal("0.0010"),
        avg_fill_price=Decimal("70330"),
        fees_paid=Decimal("0.90"),
        raw_exchange_payload={},
        created_ts=now,
        updated_ts=now,
    )
    fill = FillRecord(
        id=uuid.uuid4(),
        order_record_id=order.id,
        exchange="kraken",
        symbol="XBTUSD",
        side="buy",
        fill_price=Decimal("70330"),
        fill_qty=Decimal("0.0010"),
        fill_notional=Decimal("70.33"),
        fee_paid=Decimal("0.90"),
        fill_ts=now,
        ingested_ts=now,
    )
    db_session.add(intent)
    db_session.add(order)
    db_session.add(fill)

    # Latest snapshot for account has a different symbol; query must still pick it.
    db_session.add(
        PositionSnapshot(
            id=uuid.uuid4(),
            exchange="kraken",
            account_name="paper_mm",
            symbol="BTC-USD",
            instrument_type="spot",
            side="buy",
            quantity=Decimal("0.0050"),
            avg_entry_price=Decimal("70000"),
            mark_price=Decimal("70500"),
            unrealized_pnl=Decimal("6.75"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=None,
            snapshot_ts=now,
        )
    )
    db_session.add(
        PositionSnapshot(
            id=uuid.uuid4(),
            exchange="kraken",
            account_name="paper_mm",
            symbol="XBTUSD",
            instrument_type="spot",
            side="buy",
            quantity=Decimal("0.0040"),
            avg_entry_price=Decimal("69000"),
            mark_price=Decimal("70000"),
            unrealized_pnl=Decimal("2.00"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=None,
            snapshot_ts=now - timedelta(minutes=5),
        )
    )
    db_session.add(_book(now))
    db_session.commit()

    snapshot = compute_paper_account_snapshot(
        session=db_session,
        account_name="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
        starting_capital=Decimal("1000.00"),
    )

    assert snapshot.unrealized_pnl == Decimal("6.75")
    assert snapshot.btc_held == Decimal("0.0050")
    assert snapshot.btc_value_usd == Decimal("352.5000")
    assert snapshot.account_value == Decimal("1007.08")
