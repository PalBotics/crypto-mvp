"""Market data collector for crypto exchanges.

Continuously fetches ticker data from configured exchange and persists to database.
Sprint 2 implementation supports mock and Coinbase adapters.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from core.config.settings import Settings
from core.db.session import get_db_session
from core.exchange import get_exchange_adapter
from core.models.market_tick import MarketTick


class MarketDataCollector:
    """Market data collector that fetches and persists ticker data.

    Fetches ticker data from an exchange adapter at regular intervals and
    stores normalized MarketTick records in the database. Handles errors
    gracefully to maintain continuous operation.

    Attributes:
        settings: Application configuration
        logger: Structured logger instance
        exchange: Exchange name (cached from settings)
        adapter: Exchange adapter instance
        symbol: Trading pair symbol to collect
        interval_seconds: Polling interval in seconds
    """

    def __init__(self, settings: Settings, logger=None) -> None:
        """Initialize collector with settings and exchange adapter.

        Args:
            settings: Application configuration
            logger: Optional structured logger instance
        """
        self.settings = settings
        self.logger = logger
        self.exchange = settings.collect_exchange
        self.adapter = get_exchange_adapter(self.exchange)
        self.symbol = settings.collect_symbol
        self.interval_seconds = settings.collect_interval_seconds

    def collect_once(self, session: Session) -> None:
        """Collect a single market tick and persist to database.

        Args:
            session: SQLAlchemy database session

        Raises:
            Various exchange exceptions on failure (logged and re-raised)
        """
        ticker = self.adapter.fetch_ticker(self.symbol)

        # Safely convert to Decimal with validation
        try:
            bid_price = Decimal(str(ticker["bid"]))
            ask_price = Decimal(str(ticker["ask"]))
            last_price = Decimal(str(ticker["last"]))
            mid_price = Decimal(str((ticker["bid"] + ticker["ask"]) / 2))
        except (ValueError, KeyError, TypeError) as exc:
            if self.logger:
                self.logger.error(
                    "invalid_ticker_data",
                    exchange=self.settings.collect_exchange,
                    symbol=self.symbol,
                    error=str(exc),
                    ticker=str(ticker),
                )
            raise

        tick = MarketTick(
            exchange=self.exchange,
            adapter_name=self.adapter.name,
            symbol=ticker["symbol"],
            exchange_symbol=ticker["symbol"],
            bid_price=bid_price,
            ask_price=ask_price,
            mid_price=mid_price,
            last_price=last_price,
            bid_size=None,
            ask_size=None,
            event_ts=ticker["timestamp"],
            ingested_ts=datetime.now(timezone.utc),
            sequence_id=None,
        )

        session.add(tick)
        session.commit()

        if self.logger:
            self.logger.info(
                "market_tick_collected",
                exchange=self.exchange,
                symbol=tick.symbol,
                bid=str(tick.bid_price),
                ask=str(tick.ask_price),
                last=str(tick.last_price),
                event_ts=tick.event_ts.isoformat(),
            )

    def run(self) -> None:
        """Run the collector in an infinite loop.

        Handles failures gracefully - a failed collection cycle will not crash
        the process. Session rollback is performed on any error.
        """
        session = get_db_session()

        if self.logger:
            self.logger.info(
                "collector_configured",
                exchange=self.exchange,
                symbol=self.symbol,
                interval_seconds=self.interval_seconds,
            )

        while True:
            try:
                self.collect_once(session)
            except Exception as exc:
                # Always rollback on error to prevent partial commits
                session.rollback()

                # Log with full context including exception type
                if self.logger:
                    self.logger.exception(
                        "collector_iteration_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                        exchange=self.exchange,
                        symbol=self.symbol,
                    )

            # Sleep regardless of success/failure to maintain interval
            time.sleep(self.interval_seconds)