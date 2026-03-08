from __future__ import annotations

import os
from decimal import Decimal

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
    bootstrap_app(service_name="paper_signal_logger", check_db=True)

    api_key = _required_env("KRAKEN_API_KEY")
    api_secret = _required_env("KRAKEN_API_SECRET")

    mm_config = MarketMakingConfig(
        spread_bps=Decimal(os.environ.get("MM_SPREAD_BPS", "20")),
        quote_size=Decimal(os.environ.get("MM_QUOTE_SIZE", "0.001")),
        max_inventory=Decimal(os.environ.get("MM_MAX_INVENTORY", "0.01")),
        min_spread_bps=Decimal(os.environ.get("MM_MIN_SPREAD_BPS", "5")),
        stale_book_seconds=int(os.environ.get("MM_STALE_BOOK_SECONDS", "10")),
        account_name=os.environ.get("MM_ACCOUNT_NAME", "paper_mm"),
    )

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
