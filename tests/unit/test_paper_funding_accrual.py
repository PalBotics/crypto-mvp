from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.funding_payment import FundingPayment
from core.models.position_snapshot import PositionSnapshot
from core.paper.funding_accrual import accrue_funding_payment


def _open_long(*, qty: str, avg_entry: str = "50000") -> PositionSnapshot:
    return PositionSnapshot(
        exchange="binance",
        account_name="paper",
        symbol="BTC-PERP",
        instrument_type="perpetual",
        side="buy",
        quantity=Decimal(qty),
        avg_entry_price=Decimal(avg_entry),
        mark_price=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=datetime(2026, 3, 7, 8, 0, tzinfo=timezone.utc),
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


def test_open_long_positive_rate_payment_is_negative() -> None:
    """Long position + positive funding rate -> trader pays -> payment_amount < 0."""
    session = Mock()
    session.execute.return_value = _ScalarResult(_open_long(qty="2"))

    payment = accrue_funding_payment(
        session=session,
        symbol="BTC-PERP",
        exchange="binance",
        account_name="paper",
        mark_price=Decimal("50000"),
        funding_rate=Decimal("0.0001"),
    )

    # -1 * 2 * 50000 * 0.0001 = -10
    assert payment is not None
    assert isinstance(payment, FundingPayment)
    assert payment.payment_amount == Decimal("-10")
    assert payment.payment_amount < 0
    assert payment.symbol == "BTC-PERP"
    assert payment.exchange == "binance"
    assert payment.account_name == "paper"
    session.add.assert_called_once_with(payment)


def test_open_long_negative_rate_payment_is_positive() -> None:
    """Long position + negative funding rate -> trader receives -> payment_amount > 0."""
    session = Mock()
    session.execute.return_value = _ScalarResult(_open_long(qty="2"))

    payment = accrue_funding_payment(
        session=session,
        symbol="BTC-PERP",
        exchange="binance",
        account_name="paper",
        mark_price=Decimal("50000"),
        funding_rate=Decimal("-0.0001"),
    )

    # -1 * 2 * 50000 * -0.0001 = 10
    assert payment is not None
    assert payment.payment_amount == Decimal("10")
    assert payment.payment_amount > 0
    session.add.assert_called_once_with(payment)


def test_no_open_position_writes_nothing() -> None:
    """When no open position exists, no FundingPayment is written."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    result = accrue_funding_payment(
        session=session,
        symbol="BTC-PERP",
        exchange="binance",
        account_name="paper",
        mark_price=Decimal("50000"),
        funding_rate=Decimal("0.0001"),
    )

    assert result is None
    session.add.assert_not_called()


def test_payment_amount_decimal_precision() -> None:
    """payment_amount matches exact Decimal arithmetic with fractional quantities."""
    session = Mock()
    session.execute.return_value = _ScalarResult(
        _open_long(qty="0.12345678", avg_entry="49999.99")
    )

    payment = accrue_funding_payment(
        session=session,
        symbol="BTC-PERP",
        exchange="binance",
        account_name="paper",
        mark_price=Decimal("49999.99"),
        funding_rate=Decimal("0.0001"),
    )

    expected = Decimal("-1") * Decimal("0.12345678") * Decimal("49999.99") * Decimal("0.0001")
    assert payment is not None
    assert payment.payment_amount == expected


def test_no_float_values_in_calculation() -> None:
    """All computed fields on FundingPayment are Decimal, never float."""
    session = Mock()
    session.execute.return_value = _ScalarResult(_open_long(qty="3"))

    payment = accrue_funding_payment(
        session=session,
        symbol="BTC-PERP",
        exchange="binance",
        account_name="paper",
        mark_price=Decimal("48000"),
        funding_rate=Decimal("0.00015"),
    )

    assert payment is not None
    assert isinstance(payment.payment_amount, Decimal)
    assert isinstance(payment.position_quantity, Decimal)
    assert isinstance(payment.mark_price, Decimal)
    assert isinstance(payment.funding_rate, Decimal)
    assert not isinstance(payment.payment_amount, float)
