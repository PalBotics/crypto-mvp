from __future__ import annotations

from decimal import Decimal

import pytest

from apps.collector.kraken_auth import KrakenAuthAdapter, KrakenAuthError


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _adapter() -> KrakenAuthAdapter:
    return KrakenAuthAdapter(api_key="key", api_secret="YWJj")


def test_get_account_balance_returns_decimal_values(monkeypatch) -> None:
    payload = {
        "error": [],
        "result": {
            "ZUSD": "1000.00",
            "XXBT": "0.125",
        },
    }

    def _fake_post(*_args, **_kwargs):
        return _FakeResponse(status_code=200, payload=payload)

    monkeypatch.setattr("apps.collector.kraken_auth.httpx.post", _fake_post)

    balances = _adapter().get_account_balance()

    assert isinstance(balances["ZUSD"], Decimal)
    assert isinstance(balances["XXBT"], Decimal)
    assert not isinstance(balances["ZUSD"], float)
    assert not isinstance(balances["XXBT"], float)


def test_get_account_balance_raises_on_http_error(monkeypatch) -> None:
    def _fake_post(*_args, **_kwargs):
        return _FakeResponse(status_code=500, payload={})

    monkeypatch.setattr("apps.collector.kraken_auth.httpx.post", _fake_post)

    with pytest.raises(KrakenAuthError):
        _adapter().get_account_balance()


def test_get_account_balance_raises_on_kraken_error_field(monkeypatch) -> None:
    payload = {
        "error": ["EGeneral:Invalid key"],
    }

    def _fake_post(*_args, **_kwargs):
        return _FakeResponse(status_code=200, payload=payload)

    monkeypatch.setattr("apps.collector.kraken_auth.httpx.post", _fake_post)

    with pytest.raises(KrakenAuthError):
        _adapter().get_account_balance()


def test_verify_no_open_orders_returns_true_when_empty(monkeypatch) -> None:
    adapter = _adapter()

    def _fake_open_orders() -> list[dict]:
        return []

    monkeypatch.setattr(adapter, "get_open_orders", _fake_open_orders)

    assert adapter.verify_no_open_orders() is True


def test_verify_no_open_orders_returns_false_when_orders_exist(monkeypatch) -> None:
    adapter = _adapter()

    def _fake_open_orders() -> list[dict]:
        return [{"id": "ORDER1"}]

    monkeypatch.setattr(adapter, "get_open_orders", _fake_open_orders)

    assert adapter.verify_no_open_orders() is False
