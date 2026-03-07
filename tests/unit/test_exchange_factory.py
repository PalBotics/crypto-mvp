from core.exchange.factory import get_exchange_adapter
from core.exchange.mock_adapter import MockExchangeAdapter
import pytest


def test_get_mock_exchange_adapter() -> None:
    adapter = get_exchange_adapter("mock")
    assert isinstance(adapter, MockExchangeAdapter)


def test_factory_is_case_insensitive() -> None:
    assert isinstance(get_exchange_adapter("MOCK"), MockExchangeAdapter)


def test_get_unsupported_exchange_raises_error() -> None:
    with pytest.raises(ValueError, match="Unsupported exchange adapter"):
        get_exchange_adapter("kraken")