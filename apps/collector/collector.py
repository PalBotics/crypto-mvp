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
    def __init__(self, settings: Settings, logger=None) -> None:
        self.settings = settings
        self.logger = logger
        self.adapter = get_exchange_adapter(settings.collect_exchange)
        self.symbol = settings.collect_symbol
        self.interval_seconds = settings.collect_interval_seconds

    def collect_once(self, session: Session) -> None:
        ticker = self.adapter.fetch_ticker(self.symbol)

        tick = MarketTick(
            exchange=self.settings.collect_exchange,
            adapter_name=self.adapter.name,
            symbol=ticker["symbol"],
            exchange_symbol=ticker["symbol"],
            bid_price=Decimal(str(ticker["bid"])),
            ask_price=Decimal(str(ticker["ask"])),
            mid_price=Decimal(str((ticker["bid"] + ticker["ask"]) / 2)),
            last_price=Decimal(str(ticker["last"])),
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
                exchange=self.settings.collect_exchange,
                symbol=tick.symbol,
                bid=str(tick.bid_price),
                ask=str(tick.ask_price),
                event_ts=tick.event_ts.isoformat(),
            )

    def run(self) -> None:
        session = get_db_session()

        if self.logger:
            self.logger.info(
                "collector_configured",
                exchange=self.settings.collect_exchange,
                symbol=self.symbol,
                interval_seconds=self.interval_seconds,
            )

        while True:
            try:
                self.collect_once(session)
            except Exception as exc:
                session.rollback()
                if self.logger:
                    self.logger.exception(
                        "collector_iteration_failed",
                        error=str(exc),
                        exchange=self.settings.collect_exchange,
                        symbol=self.symbol,
                    )
            time.sleep(self.interval_seconds)