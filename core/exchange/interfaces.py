from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ExchangeAdapter(ABC):
    """
    Base interface for exchange integrations.
    """

    name: str

    @abstractmethod
    def get_server_time(self) -> datetime:
        pass

    @abstractmethod
    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        pass

    @abstractmethod
    def fetch_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        pass

    @abstractmethod
    def place_order(self, order: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        pass