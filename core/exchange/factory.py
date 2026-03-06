from core.exchange.mock_adapter import MockExchangeAdapter
from core.exchange.exceptions import ExchangeError


def get_exchange_adapter(exchange_name: str):
    normalized = exchange_name.strip().lower()

    if normalized == "mock":
        return MockExchangeAdapter()

    raise ExchangeError(f"Unsupported exchange adapter: {exchange_name}")