"""Factory for exchange adapter instantiation."""

from core.exchange.interfaces import ExchangeAdapter
from core.exchange.mock_adapter import MockExchangeAdapter


def get_exchange_adapter(exchange_name: str) -> ExchangeAdapter:
    """Get an exchange adapter instance by name.

    Args:
        exchange_name: Name of the exchange ("mock", case-insensitive)

    Returns:
        Configured exchange adapter instance

    Raises:
        ValueError: If exchange name is not supported
    """
    normalized = exchange_name.strip().lower()

    if normalized == "mock":
        return MockExchangeAdapter()

    raise ValueError(
        f"Unsupported exchange adapter: {exchange_name}. Only 'mock' is available."
    )