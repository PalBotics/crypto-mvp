from core.exchange.factory import get_exchange_adapter
from core.exchange.mock_adapter import MockExchangeAdapter


def test_get_mock_exchange_adapter() -> None:
    adapter = get_exchange_adapter("mock")
    assert isinstance(adapter, MockExchangeAdapter)