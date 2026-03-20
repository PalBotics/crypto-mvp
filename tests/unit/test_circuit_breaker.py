from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.risk_event import RiskEvent
from core.risk.risk_engine import RiskEngine


def _engine() -> RiskEngine:
    session = Mock()
    engine = RiskEngine(account_name="paper_dn", db=session)
    engine.risk_max_consecutive_failures = 5
    engine._breakers.clear()
    return engine


def _persisted_events(session: Mock) -> list[RiskEvent]:
    return [
        call.args[0]
        for call in session.add.call_args_list
        if call.args and isinstance(call.args[0], RiskEvent)
    ]


def test_breaker_opens_after_n_failures(monkeypatch) -> None:
    engine = _engine()
    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("core.risk.risk_engine._log.warning", _capture)

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    breaker = engine._breakers["kraken"]
    assert breaker.state == "open"
    assert "exchange_circuit_breaker_opened" in events
    assert any(evt.event_type == "circuit_breaker_opened" for evt in _persisted_events(engine.db))


def test_breaker_does_not_open_before_threshold() -> None:
    engine = _engine()

    for _ in range(4):
        engine.record_exchange_failure("kraken")

    breaker = engine._breakers["kraken"]
    assert breaker.state == "closed"


def test_breaker_closes_on_success(monkeypatch) -> None:
    engine = _engine()
    events: list[str] = []

    def _capture(event, **_kwargs):
        events.append(event)

    monkeypatch.setattr("core.risk.risk_engine._log.info", _capture)

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    engine.record_exchange_success("kraken")

    breaker = engine._breakers["kraken"]
    assert breaker.state == "closed"
    assert breaker.failure_count == 0
    assert "exchange_circuit_breaker_closed" in events


def test_breaker_blocks_when_open() -> None:
    engine = _engine()

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    assert engine.is_exchange_available("kraken") is False


def test_canary_allowed_after_60s() -> None:
    engine = _engine()

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    breaker = engine._breakers["kraken"]
    breaker.opened_at = datetime.now(timezone.utc) - timedelta(seconds=61)

    assert engine.is_exchange_available("kraken") is True
    assert breaker.state == "half_open"


def test_canary_blocked_before_60s() -> None:
    engine = _engine()

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    breaker = engine._breakers["kraken"]
    breaker.opened_at = datetime.now(timezone.utc)

    assert engine.is_exchange_available("kraken") is False


def test_independent_breakers_per_exchange() -> None:
    engine = _engine()

    for _ in range(5):
        engine.record_exchange_failure("kraken")

    assert engine.is_exchange_available("kraken") is False
    assert engine.is_exchange_available("coinbase_advanced") is True
