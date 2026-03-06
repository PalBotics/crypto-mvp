"""Factory for exchange adapter instantiation."""

from core.exchange.binance_adapter import BinanceAdapter
from core.exchange.coinbase_adapter import CoinbaseAdapter
from core.exchange.mock_adapter import MockExchangeAdapter
from core.exchange.exceptions import ExchangeError
from core.exchange.interfaces import ExchangeAdapter


def get_exchange_adapter(exchange_name: str) -> ExchangeAdapter:
    """Get an exchange adapter instance by name.

    Args:
        exchange_name: Name of the exchange ("mock", "coinbase", or "binance", case-insensitive)

    Returns:
        Configured exchange adapter instance

    Raises:
        ExchangeError: If exchange name is not supported
    """
    normalized = exchange_name.strip().lower()

    if normalized == "mock":
        return MockExchangeAdapter()
    
    if normalized == "coinbase":
        return CoinbaseAdapter()

    if normalized == "binance":
        return BinanceAdapter()

    raise ExchangeError(f"Unsupported exchange adapter: {exchange_name}")