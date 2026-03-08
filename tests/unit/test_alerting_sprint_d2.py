from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core.alerting.evaluator import AlertConfig, AlertEvaluator
from core.models.order_book_snapshot import OrderBookSnapshot

NOW = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)


def _config() -> AlertConfig:
    return AlertConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        stale_data_threshold_seconds=10,
        drawdown_threshold=Decimal("-500"),
        no_fill_threshold_seconds=3600,
        min_funding_rate=Decimal("0.0001"),
        ob_exchange="kraken",
        ob_symbol="XBTUSD",
        mm_min_spread_bps=Decimal("5"),
    )


def _add_order_book(db_session, *, ts: datetime, spread_bps: Decimal) -> None:
    mid = Decimal("60000")
    spread = mid * spread_bps / Decimal("10000")
    db_session.add(
        OrderBookSnapshot(
            exchange="kraken",
            adapter_name="kraken_rest",
            symbol="XBTUSD",
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


def test_stale_order_book_alert_fires(db_session) -> None:
    _add_order_book(db_session, ts=NOW - timedelta(seconds=60), spread_bps=Decimal("8"))
    db_session.commit()

    results = AlertEvaluator(_config()).evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "stale_order_book"]
    assert len(alerts) == 1
    assert alerts[0].message == "order_book_stale"


def test_stale_order_book_alert_does_not_fire_when_fresh(db_session) -> None:
    _add_order_book(db_session, ts=NOW - timedelta(seconds=2), spread_bps=Decimal("8"))
    db_session.commit()

    results = AlertEvaluator(_config()).evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "stale_order_book"]
    assert alerts == []


def test_spread_too_tight_alert_fires(db_session) -> None:
    _add_order_book(db_session, ts=NOW - timedelta(seconds=1), spread_bps=Decimal("2"))
    db_session.commit()

    results = AlertEvaluator(_config()).evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "spread_too_tight"]
    assert len(alerts) == 1
    assert alerts[0].message == "spread_too_tight"


def test_spread_too_tight_alert_does_not_fire_when_wide(db_session) -> None:
    _add_order_book(db_session, ts=NOW - timedelta(seconds=1), spread_bps=Decimal("12"))
    db_session.commit()

    results = AlertEvaluator(_config()).evaluate(db_session, now=NOW)

    alerts = [r for r in results if r.alert_type == "spread_too_tight"]
    assert alerts == []
