from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.fill_record import FillRecord
from core.models.position_snapshot import PositionSnapshot
from core.paper.position_tracker import update_position_from_fill


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


def _fill(*, side: str, qty: str, price: str) -> FillRecord:
    ts = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    return FillRecord(
        order_record_id=None,
        exchange="coinbase",
        symbol="BTC-USD",
        exchange_trade_id="t-1",
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


def _position(*, side: str, qty: str, avg_price: str) -> PositionSnapshot:
    ts = datetime(2026, 3, 7, 11, 59, tzinfo=timezone.utc)
    return PositionSnapshot(
        exchange="coinbase",
        account_name="paper",
        symbol="BTC-USD",
        instrument_type="spot",
        side=side,
        quantity=Decimal(qty),
        avg_entry_price=Decimal(avg_price),
        mark_price=Decimal(avg_price),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=ts,
    )


def test_creates_new_position_from_first_fill() -> None:
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    created = update_position_from_fill(session, _fill(side="buy", qty="2", price="50010"))

    assert created.exchange == "coinbase"
    assert created.account_name == "paper"
    assert created.symbol == "BTC-USD"
    assert created.side == "buy"
    assert created.quantity == Decimal("2")
    assert created.avg_entry_price == Decimal("50010")
    assert created.snapshot_ts == datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    session.add.assert_called_once_with(created)


def test_updates_existing_position_with_second_fill() -> None:
    session = Mock()
    existing = _position(side="buy", qty="2", avg_price="50000")
    session.execute.return_value = _ScalarResult(existing)

    updated = update_position_from_fill(session, _fill(side="buy", qty="1", price="51000"))

    assert updated is existing
    assert updated.quantity == Decimal("3")
    assert updated.side == "buy"
    assert updated.mark_price == Decimal("51000")


def test_weighted_average_entry_is_correct_after_add() -> None:
    session = Mock()
    existing = _position(side="buy", qty="2", avg_price="50000")
    session.execute.return_value = _ScalarResult(existing)

    update_position_from_fill(session, _fill(side="buy", qty="1", price="51000"))

    assert existing.avg_entry_price == Decimal("50333.33333333333333333333333")


def test_position_is_closed_when_quantity_reaches_zero() -> None:
    session = Mock()
    existing = _position(side="buy", qty="2", avg_price="50000")
    session.execute.return_value = _ScalarResult(existing)

    closed = update_position_from_fill(session, _fill(side="sell", qty="2", price="52000"))

    assert closed is existing
    assert closed.quantity == Decimal("0")
    assert closed.avg_entry_price is None
    assert closed.mark_price == Decimal("52000")


def test_decimal_precision_is_preserved() -> None:
    session = Mock()
    existing = _position(side="buy", qty="0.10000000", avg_price="50000.12345678")
    session.execute.return_value = _ScalarResult(existing)

    update_position_from_fill(
        session,
        _fill(side="buy", qty="0.20000000", price="50010.87654321"),
    )

    assert existing.quantity == Decimal("0.30000000")
    assert existing.avg_entry_price == Decimal("50007.29218106666666666666667")
