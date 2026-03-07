from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.reporting.kpi import KPIResult, calculate_kpis

ACCOUNT = "run_abc"
EXCHANGE = "binance"
PERP = "BTC-PERP"
BASE_TS = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def _pnl(ts: datetime, realized: Decimal) -> PnLSnapshot:
    return PnLSnapshot(
        id=uuid.uuid4(),
        portfolio_id=None,
        strategy_name=ACCOUNT,
        symbol=PERP,
        realized_pnl=realized,
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=realized,
        net_pnl=realized,
        snapshot_ts=ts,
    )


def _funding(ts: datetime, amount: Decimal) -> FundingPayment:
    return FundingPayment(
        id=uuid.uuid4(),
        exchange=EXCHANGE,
        symbol=PERP,
        account_name=ACCOUNT,
        position_quantity=Decimal("1"),
        mark_price=Decimal("50000"),
        funding_rate=Decimal("0.0001"),
        payment_amount=amount,
        accrued_ts=ts,
        created_ts=ts,
    )


def _fill_chain(ts: datetime, fee: Decimal) -> tuple[OrderIntent, OrderRecord, FillRecord]:
    intent = OrderIntent(
        id=uuid.uuid4(),
        strategy_signal_id=None,
        portfolio_id=None,
        mode=ACCOUNT,
        exchange=EXCHANGE,
        symbol=PERP,
        side="sell",
        order_type="market",
        time_in_force=None,
        quantity=Decimal("1"),
        limit_price=None,
        reduce_only=False,
        post_only=False,
        client_order_id=None,
        status="filled",
        created_ts=ts,
    )
    order_record = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange=EXCHANGE,
        symbol=PERP,
        exchange_order_id=str(uuid.uuid4()),
        client_order_id=None,
        side="sell",
        order_type="market",
        status="filled",
        submitted_price=Decimal("50000"),
        submitted_qty=Decimal("1"),
        filled_qty=Decimal("1"),
        avg_fill_price=Decimal("50000"),
        fees_paid=fee,
        fee_asset="USDT",
        created_ts=ts,
        updated_ts=ts,
        raw_exchange_payload={},
    )
    fill = FillRecord(
        id=uuid.uuid4(),
        order_record_id=order_record.id,
        exchange=EXCHANGE,
        symbol=PERP,
        exchange_trade_id=None,
        side="sell",
        fill_price=Decimal("50000"),
        fill_qty=Decimal("1"),
        fill_notional=Decimal("50000"),
        liquidity_role=None,
        fee_paid=fee,
        fee_asset="USDT",
        fill_ts=ts,
        ingested_ts=ts,
    )
    return intent, order_record, fill


def _funding_snapshot(ts: datetime, rate: Decimal) -> FundingRateSnapshot:
    return FundingRateSnapshot(
        id=uuid.uuid4(),
        exchange=EXCHANGE,
        adapter_name=EXCHANGE,
        symbol=PERP,
        exchange_symbol=PERP,
        funding_rate=rate,
        funding_interval_hours=8,
        predicted_funding_rate=None,
        mark_price=Decimal("50000"),
        index_price=Decimal("50000"),
        next_funding_ts=None,
        event_ts=ts,
        ingested_ts=ts,
    )


def _position(ts: datetime, qty: Decimal) -> PositionSnapshot:
    return PositionSnapshot(
        id=uuid.uuid4(),
        exchange=EXCHANGE,
        account_name=ACCOUNT,
        symbol=PERP,
        instrument_type="future",
        side="short",
        quantity=qty,
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=Decimal("1"),
        margin_used=Decimal("50000"),
        snapshot_ts=ts,
    )


def test_annualized_return_known_case(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(days=365, hours=6)  # ~365.25 days

    db_session.add(_pnl(start + timedelta(hours=1), Decimal("100")))
    db_session.add(_funding(start + timedelta(hours=2), Decimal("0")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert abs(result.annualized_return - Decimal("0.1")) < Decimal("0.0000001")


def test_annualized_return_zero_when_elapsed_zero(db_session) -> None:
    start = BASE_TS
    end = start

    db_session.add(_pnl(start, Decimal("100")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.annualized_return == Decimal("0")


def test_annualized_return_zero_when_initial_capital_zero(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(days=1)

    db_session.add(_pnl(start + timedelta(hours=1), Decimal("100")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("0"),
    )

    assert result.annualized_return == Decimal("0")


def test_max_drawdown_known_series(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=4)

    db_session.add(_pnl(start + timedelta(hours=1), Decimal("100")))
    db_session.add(_pnl(start + timedelta(hours=2), Decimal("-50")))
    db_session.add(_pnl(start + timedelta(hours=3), Decimal("-150")))
    db_session.add(_pnl(start + timedelta(hours=4), Decimal("200")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.max_drawdown == Decimal("200")


def test_max_drawdown_zero_for_single_snapshot(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=1)

    db_session.add(_pnl(start + timedelta(minutes=30), Decimal("100")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.max_drawdown == Decimal("0")


def test_max_drawdown_is_non_negative(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=3)

    db_session.add(_pnl(start + timedelta(hours=1), Decimal("50")))
    db_session.add(_pnl(start + timedelta(hours=2), Decimal("60")))
    db_session.add(_pnl(start + timedelta(hours=3), Decimal("70")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.max_drawdown >= Decimal("0")


def test_fee_drag_calculated_correctly(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=2)

    intent, order_record, fill = _fill_chain(start + timedelta(minutes=30), Decimal("15"))
    db_session.add(intent)
    db_session.add(order_record)
    db_session.add(fill)

    db_session.add(_funding(start + timedelta(minutes=45), Decimal("100")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.fee_drag == Decimal("0.15")


def test_fee_drag_zero_when_no_funding_income(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=2)

    intent, order_record, fill = _fill_chain(start + timedelta(minutes=30), Decimal("10"))
    db_session.add(intent)
    db_session.add(order_record)
    db_session.add(fill)

    db_session.add(_funding(start + timedelta(minutes=45), Decimal("-50")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.fee_drag == Decimal("0")


def test_missed_opportunity_count_when_position_absent_during_high_rate(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=3)

    t1 = start + timedelta(minutes=30)
    t2 = start + timedelta(minutes=60)
    t3 = start + timedelta(minutes=90)

    db_session.add(_funding_snapshot(t1, Decimal("0.0002")))
    db_session.add(_funding_snapshot(t2, Decimal("0.0002")))
    db_session.add(_funding_snapshot(t3, Decimal("0.00001")))

    db_session.add(_position(t2, Decimal("1")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.missed_opportunity_count == 1


def test_missed_opportunity_zero_when_position_always_open(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=3)

    t1 = start + timedelta(minutes=30)
    t2 = start + timedelta(minutes=60)

    db_session.add(_funding_snapshot(t1, Decimal("0.0002")))
    db_session.add(_funding_snapshot(t2, Decimal("0.0003")))

    db_session.add(_position(start + timedelta(minutes=1), Decimal("1")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert result.missed_opportunity_count == 0


def test_returned_fields_types(db_session) -> None:
    start = BASE_TS
    end = start + timedelta(hours=2)

    db_session.add(_pnl(start + timedelta(minutes=30), Decimal("10")))
    db_session.add(_funding(start + timedelta(minutes=40), Decimal("5")))
    db_session.commit()

    result = calculate_kpis(
        session=db_session,
        account_name=ACCOUNT,
        start_ts=start,
        end_ts=end,
        entry_threshold=Decimal("0.0001"),
        initial_capital=Decimal("1000"),
    )

    assert isinstance(result, KPIResult)
    assert isinstance(result.annualized_return, Decimal)
    assert isinstance(result.max_drawdown, Decimal)
    assert isinstance(result.fee_drag, Decimal)
    assert isinstance(result.funding_income_captured, Decimal)
    assert isinstance(result.missed_opportunity_count, int)
