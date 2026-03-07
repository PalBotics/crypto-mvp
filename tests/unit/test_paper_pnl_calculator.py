from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from sqlalchemy.orm.attributes import set_committed_value

from core.models.fill_record import FillRecord
from core.models.position_snapshot import PositionSnapshot
from core.paper.pnl_calculator import create_pnl_snapshot_from_fill


def _fill(*, side: str, qty: str, price: str) -> FillRecord:
    ts = datetime(2026, 3, 7, 13, 0, tzinfo=timezone.utc)
    return FillRecord(
        order_record_id=None,
        exchange="coinbase",
        symbol="BTC-USD",
        exchange_trade_id="trade-1",
        side=side,
        fill_price=Decimal(price),
        fill_qty=Decimal(qty),
        fill_notional=Decimal(qty) * Decimal(price),
        liquidity_role="taker",
        fee_paid=Decimal("0"),
        fee_asset="USD",
        fill_ts=ts,
        ingested_ts=ts,
    )


def _position(*, side: str, qty: str, avg_entry: str | None) -> PositionSnapshot:
    return PositionSnapshot(
        exchange="coinbase",
        account_name="paper",
        symbol="BTC-USD",
        instrument_type="spot",
        side=side,
        quantity=Decimal(qty),
        avg_entry_price=Decimal(avg_entry) if avg_entry is not None else None,
        mark_price=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime(2026, 3, 7, 12, 59, tzinfo=timezone.utc),
    )


def test_opening_fill_creates_snapshot_with_zero_realized() -> None:
    session = Mock()
    fill = _fill(side="buy", qty="2", price="50010")
    position = _position(side="buy", qty="2", avg_entry="50010")

    snapshot = create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill,
        position_snapshot=position,
        mark_price=Decimal("50010"),
    )

    assert snapshot.realized_pnl == Decimal("0")
    assert snapshot.unrealized_pnl == Decimal("0")
    assert snapshot.strategy_name == "paper"
    assert snapshot.symbol == "BTC-USD"
    session.add.assert_called_once_with(snapshot)


def test_closing_long_fill_has_positive_realized() -> None:
    session = Mock()
    fill = _fill(side="sell", qty="2", price="52000")
    position = _position(side="buy", qty="0", avg_entry=None)

    # Seed committed pre-fill values, then mutate to post-fill closed values.
    set_committed_value(position, "side", "buy")
    set_committed_value(position, "quantity", Decimal("2"))
    set_committed_value(position, "avg_entry_price", Decimal("50000"))

    position.side = "buy"
    position.quantity = Decimal("0")
    position.avg_entry_price = None

    snapshot = create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill,
        position_snapshot=position,
        mark_price=Decimal("52000"),
    )

    assert snapshot.realized_pnl == Decimal("4000")


def test_unrealized_for_open_long_is_correct() -> None:
    session = Mock()
    fill = _fill(side="buy", qty="1", price="50000")
    position = _position(side="buy", qty="3", avg_entry="50000")

    snapshot = create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill,
        position_snapshot=position,
        mark_price=Decimal("50500"),
    )

    assert snapshot.unrealized_pnl == Decimal("1500")


def test_unrealized_for_closed_position_is_zero() -> None:
    session = Mock()
    fill = _fill(side="sell", qty="1", price="50000")
    position = _position(side="buy", qty="0", avg_entry=None)

    snapshot = create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill,
        position_snapshot=position,
        mark_price=Decimal("50000"),
    )

    assert snapshot.unrealized_pnl == Decimal("0")


def test_decimal_precision_and_no_float_types() -> None:
    session = Mock()
    fill = _fill(side="buy", qty="0.20000000", price="50010.87654321")
    position = _position(side="buy", qty="0.30000000", avg_entry="50007.29218106666666666666667")

    snapshot = create_pnl_snapshot_from_fill(
        session=session,
        fill_record=fill,
        position_snapshot=position,
        mark_price=Decimal("50011.11111111"),
    )

    assert snapshot.realized_pnl == Decimal("0")
    assert snapshot.unrealized_pnl == Decimal("1.14567901299999999999999900")
    assert isinstance(snapshot.realized_pnl, Decimal)
    assert isinstance(snapshot.unrealized_pnl, Decimal)
    assert isinstance(snapshot.gross_pnl, Decimal)
    assert isinstance(snapshot.net_pnl, Decimal)
