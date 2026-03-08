from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.models.fill_record import FillRecord
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.reporting.kpi import MMKPIResult, calculate_mm_kpis

ACCOUNT = "paper_mm"
EXCHANGE = "kraken"
SYMBOL = "XBTUSD"
START = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)
END = START + timedelta(minutes=10)


def _add_intent_chain(db_session, *, ts: datetime, price: Decimal, qty: Decimal, fee: Decimal) -> None:
    intent = OrderIntent(
        id=uuid.uuid4(),
        strategy_signal_id=None,
        portfolio_id=None,
        mode=ACCOUNT,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        time_in_force=None,
        quantity=qty,
        limit_price=price,
        reduce_only=False,
        post_only=False,
        client_order_id=None,
        status="filled",
        created_ts=ts,
    )
    order = OrderRecord(
        id=uuid.uuid4(),
        order_intent_id=intent.id,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        exchange_order_id=str(uuid.uuid4()),
        client_order_id=None,
        side="buy",
        order_type="market",
        status="filled",
        submitted_price=price,
        submitted_qty=qty,
        filled_qty=qty,
        avg_fill_price=price,
        fees_paid=fee,
        fee_asset="USD",
        created_ts=ts,
        updated_ts=ts,
        raw_exchange_payload={},
    )
    fill = FillRecord(
        id=uuid.uuid4(),
        order_record_id=order.id,
        exchange=EXCHANGE,
        symbol=SYMBOL,
        exchange_trade_id=None,
        side="buy",
        fill_price=price,
        fill_qty=qty,
        fill_notional=price * qty,
        liquidity_role="maker",
        fee_paid=fee,
        fee_asset="USD",
        fill_ts=ts,
        ingested_ts=ts,
    )
    db_session.add(intent)
    db_session.add(order)
    db_session.add(fill)


def _add_order_book(db_session, *, ts: datetime, mid: Decimal, spread_bps: Decimal) -> None:
    spread = mid * spread_bps / Decimal("10000")
    db_session.add(
        OrderBookSnapshot(
            exchange=EXCHANGE,
            adapter_name="kraken_rest",
            symbol=SYMBOL,
            exchange_symbol="XXBTZUSD",
            bid_price_1=mid - spread / Decimal("2"),
            bid_size_1=Decimal("1"),
            ask_price_1=mid + spread / Decimal("2"),
            ask_size_1=Decimal("1"),
            bid_price_2=None,
            bid_size_2=None,
            ask_price_2=None,
            ask_size_2=None,
            bid_price_3=None,
            bid_size_3=None,
            ask_price_3=None,
            ask_size_3=None,
            spread=spread,
            spread_bps=spread_bps,
            mid_price=mid,
            event_ts=ts,
            ingested_ts=ts,
        )
    )


def _add_pnl(db_session, *, ts: datetime, realized: Decimal) -> None:
    db_session.add(
        PnLSnapshot(
            id=uuid.uuid4(),
            portfolio_id=None,
            strategy_name=ACCOUNT,
            symbol=SYMBOL,
            realized_pnl=realized,
            unrealized_pnl=Decimal("0"),
            funding_pnl=Decimal("0"),
            fee_pnl=Decimal("0"),
            gross_pnl=realized,
            net_pnl=realized,
            snapshot_ts=ts,
        )
    )


def test_mm_kpis_total_fills_counted_correctly(db_session) -> None:
    _add_intent_chain(db_session, ts=START + timedelta(minutes=1), price=Decimal("60000"), qty=Decimal("0.001"), fee=Decimal("0.05"))
    _add_intent_chain(db_session, ts=START + timedelta(minutes=2), price=Decimal("60010"), qty=Decimal("0.001"), fee=Decimal("0.05"))
    db_session.commit()

    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("1000"))

    assert result.total_fills == 2


def test_mm_kpis_total_fees_summed_correctly(db_session) -> None:
    _add_intent_chain(db_session, ts=START + timedelta(minutes=1), price=Decimal("60000"), qty=Decimal("0.001"), fee=Decimal("0.03"))
    _add_intent_chain(db_session, ts=START + timedelta(minutes=2), price=Decimal("60010"), qty=Decimal("0.001"), fee=Decimal("0.07"))
    db_session.commit()

    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("1000"))

    assert result.total_fees == Decimal("0.10")


def test_mm_kpis_fill_rate_zero_when_no_intents(db_session) -> None:
    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("1000"))

    assert result.fill_rate == Decimal("0")


def test_mm_kpis_net_spread_capture_equals_gross_minus_fees(db_session) -> None:
    fill_ts = START + timedelta(minutes=1)
    _add_intent_chain(db_session, ts=fill_ts, price=Decimal("60001"), qty=Decimal("0.001"), fee=Decimal("0.02"))
    _add_order_book(db_session, ts=fill_ts + timedelta(seconds=2), mid=Decimal("60000"), spread_bps=Decimal("8"))
    db_session.commit()

    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("1000"))

    assert result.net_spread_capture == result.gross_spread_capture - result.total_fees


def test_mm_kpis_inventory_turnover_zero_when_no_capital(db_session) -> None:
    _add_intent_chain(db_session, ts=START + timedelta(minutes=1), price=Decimal("60000"), qty=Decimal("0.002"), fee=Decimal("0.01"))
    db_session.commit()

    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("0"))

    assert result.inventory_turnover == Decimal("0")


def test_mm_kpis_all_fields_are_decimal_or_int(db_session) -> None:
    fill_ts = START + timedelta(minutes=1)
    _add_intent_chain(db_session, ts=fill_ts, price=Decimal("60001"), qty=Decimal("0.001"), fee=Decimal("0.02"))
    _add_order_book(db_session, ts=fill_ts, mid=Decimal("60000"), spread_bps=Decimal("8"))
    _add_pnl(db_session, ts=fill_ts, realized=Decimal("1"))
    db_session.commit()

    result = calculate_mm_kpis(db_session, ACCOUNT, START, END, Decimal("1000"))

    assert isinstance(result, MMKPIResult)
    assert isinstance(result.total_fills, int)
    assert isinstance(result.total_volume, Decimal)
    assert isinstance(result.total_fees, Decimal)
    assert isinstance(result.realized_pnl, Decimal)
    assert isinstance(result.gross_spread_capture, Decimal)
    assert isinstance(result.net_spread_capture, Decimal)
    assert isinstance(result.fill_rate, Decimal)
    assert isinstance(result.avg_spread_captured_bps, Decimal)
    assert isinstance(result.inventory_turnover, Decimal)
