from datetime import datetime, timezone
from random import random

from core.exchange.interfaces import ExchangeAdapter


class MockExchangeAdapter(ExchangeAdapter):

    name = "mock"

    def get_server_time(self) -> datetime:
        return datetime.now(timezone.utc)

    def fetch_ticker(self, symbol: str) -> dict:
        price = 50000 + random() * 1000

        return {
            "symbol": symbol,
            "bid": price - 1,
            "ask": price + 1,
            "last": price,
            "timestamp": datetime.now(timezone.utc),
        }

    def fetch_order_book(self, symbol: str) -> dict:
        price = 50000 + random() * 1000

        return {
            "bids": [[price - 1, 1]],
            "asks": [[price + 1, 1]],
        }

    def fetch_funding_rate(self, symbol: str):
        return None

    def place_order(self, order: dict) -> dict:
        return {
            "order_id": "mock-order-1",
            "status": "filled",
        }

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True