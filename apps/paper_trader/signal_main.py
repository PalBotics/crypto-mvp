from __future__ import annotations

import os
from decimal import Decimal

from dotenv import load_dotenv

from apps.collector.kraken_auth import KrakenAuthAdapter
from apps.paper_trader.signal_logger import SignalLogger
from core.app import bootstrap_app
from core.db.session import SessionLocal
from core.strategy.market_making import MarketMakingConfig


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def main() -> None:
    load_dotenv()

    bootstrap_app(service_name="paper_signal_logger", check_db=True)

    api_key = _required_env("KRAKEN_API_KEY")
    api_secret = _required_env("KRAKEN_API_SECRET")

    _stale = os.environ.get("MM_STALE_BOOK_SECONDS")
    stale_book_seconds = int(_stale) if _stale is not None else None
    _spread = os.environ.get("MM_SPREAD_BPS")
    spread_bps = Decimal(_spread) if _spread is not None else None
    _quote = os.environ.get("MM_QUOTE_SIZE")
    quote_size = Decimal(_quote) if _quote is not None else None
    _inventory = os.environ.get("MM_MAX_INVENTORY")
    max_inventory = Decimal(_inventory) if _inventory is not None else None
    _min_spread = os.environ.get("MM_MIN_SPREAD_BPS")
    min_spread_bps = Decimal(_min_spread) if _min_spread is not None else None

    mm_kwargs = {
        "account_name": os.environ.get("MM_ACCOUNT_NAME", "paper_mm"),
    }
    if spread_bps is not None:
        mm_kwargs["spread_bps"] = spread_bps
    if quote_size is not None:
        mm_kwargs["quote_size"] = quote_size
    if max_inventory is not None:
        mm_kwargs["max_inventory"] = max_inventory
    if min_spread_bps is not None:
        mm_kwargs["min_spread_bps"] = min_spread_bps
    if stale_book_seconds is not None:
        mm_kwargs["stale_book_seconds"] = stale_book_seconds

    mm_config = MarketMakingConfig(**mm_kwargs)

    poll_interval_seconds = int(os.environ.get("SIGNAL_POLL_INTERVAL", "60"))

    auth_adapter = KrakenAuthAdapter(
        api_key=api_key,
        api_secret=api_secret,
    )

    signal_logger = SignalLogger(
        config=mm_config,
        auth_adapter=auth_adapter,
        session_factory=SessionLocal,
        poll_interval_seconds=poll_interval_seconds,
    )
    signal_logger.run()


if __name__ == "__main__":
    main()
