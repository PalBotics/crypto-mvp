from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.exchange.kraken_live import KrakenLiveAdapter, LiveModeDisabledError
from scripts.validate_live_feeds import validate_price_tolerance


class _Response:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_get_eth_ticker_parses_response(monkeypatch) -> None:
    payload = {
        "error": [],
        "result": {
            "XETHZUSD": {
                "a": ["2101.10"],
                "b": ["2100.90"],
                "c": ["2101.00"],
            }
        },
    }

    monkeypatch.setattr(
        "core.exchange.kraken_live.requests.get",
        lambda *args, **kwargs: _Response(status_code=200, payload=payload),
    )

    adapter = KrakenLiveAdapter(api_key="k", api_secret="c2VjcmV0")
    ticker = adapter.get_eth_ticker()

    assert ticker["pair"] == "ETHUSD"
    assert ticker["ask"] == Decimal("2101.10")
    assert ticker["bid"] == Decimal("2100.90")
    assert ticker["last"] == Decimal("2101.00")


def test_live_mode_disabled_raises_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.exchange.kraken_live.get_settings",
        lambda: SimpleNamespace(live_mode=False),
    )

    adapter = KrakenLiveAdapter(api_key="k", api_secret="c2VjcmV0")

    with pytest.raises(LiveModeDisabledError):
        adapter.get_account_balance()


def test_credentials_never_logged(monkeypatch) -> None:
    api_key = "fake_key_123"
    api_secret = "fake_secret_456"
    events: list[tuple[str, dict]] = []

    def _capture(event, **kwargs):
        events.append((event, kwargs))

    monkeypatch.setattr("core.exchange.kraken_live._log.info", _capture)
    monkeypatch.setattr("core.exchange.kraken_live._log.error", _capture)

    adapter = KrakenLiveAdapter(api_key=api_key, api_secret=api_secret)
    monkeypatch.setattr(adapter, "get_account_balance", lambda: {"USD": Decimal("10")})

    assert adapter.validate_credentials() is True
    log_blob = " ".join(
        [
            f"{event} {kwargs}"
            for event, kwargs in events
        ]
    )
    assert api_key not in log_blob
    assert api_secret not in log_blob


def test_validate_live_feeds_passes_within_tolerance() -> None:
    result = validate_price_tolerance(
        live_price=Decimal("2100.00"),
        db_price=Decimal("2101.00"),
    )

    assert result.passed is True
    assert result.deviation_pct.quantize(Decimal("0.001")) == Decimal("0.048")


def test_validate_live_feeds_fails_outside_tolerance() -> None:
    result = validate_price_tolerance(
        live_price=Decimal("2100.00"),
        db_price=Decimal("2125.00"),
    )

    assert result.passed is False
    assert result.deviation_pct.quantize(Decimal("0.01")) == Decimal("1.18")
