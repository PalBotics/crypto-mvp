from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def to_decimal(value) -> Decimal:
    """Convert a numeric-like value to Decimal.

    Uses string conversion for stable float handling.
    """
    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Cannot convert to Decimal: {value!r}") from exc


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware and normalized to UTC."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")

    return dt.astimezone(timezone.utc)


def normalize_symbol(exchange: str, symbol: str) -> tuple[str, str]:
    """Return (symbol, exchange_symbol) with minimal exchange-aware normalization.

    This keeps current behavior stable while providing an exchange-native symbol
    value for known adapters.
    """
    exchange_name = exchange.strip().lower()
    base_symbol = symbol.strip().upper()

    if exchange_name == "binance":
        exchange_symbol = base_symbol.replace("-", "").replace("/", "")
    elif exchange_name in {"coinbase", "mock"}:
        exchange_symbol = base_symbol.replace("/", "-")
    else:
        exchange_symbol = base_symbol

    return base_symbol, exchange_symbol
