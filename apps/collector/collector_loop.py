from __future__ import annotations

import signal
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.collector.kraken_rest import CollectorConfig, CollectorError, KrakenRestAdapter
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.utils.logging import get_logger

_log = get_logger(__name__)


class CollectorLoop:
    """REST polling loop that ingests Kraken spot and Kraken futures data."""

    def __init__(
        self,
        config: CollectorConfig,
        adapter: KrakenRestAdapter,
        session_factory: Callable[[], Session],
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._session_factory = session_factory
        self._running = True

    def run(self) -> None:
        self._install_signal_handlers()
        _log.info(
            "collector_loop_starting",
            spot_exchange=self._config.spot_exchange,
            perp_exchange=self._config.perp_exchange,
            spot_symbol=self._config.spot_symbol,
            perp_symbol=self._config.perp_symbol,
            poll_interval_seconds=self._config.poll_interval_seconds,
        )

        try:
            while self._running:
                session = self._session_factory()
                try:
                    self._poll_once(session)
                finally:
                    session.close()

                if self._running:
                    time.sleep(self._config.poll_interval_seconds)
        except KeyboardInterrupt:
            _log.info("collector_keyboard_interrupt_received")
        finally:
            _log.info("collector_loop_stopped")

    def _poll_once(self, session: Session) -> None:
        try:
            spot_raw = self._adapter.fetch_spot_ticker()
            futures_tickers = self._adapter.fetch_futures_tickers()

            perp_raw = next(
                (
                    ticker
                    for ticker in futures_tickers
                    if str(ticker.get("symbol")) == self._config.perp_exchange_symbol
                ),
                None,
            )
            if perp_raw is None:
                raise CollectorError(
                    f"Kraken futures ticker {self._config.perp_exchange_symbol} not found"
                )

            spot_tick = self._adapter.parse_spot_tick(spot_raw)
            perp_tick = self._adapter.parse_perp_tick(perp_raw)
            funding_snapshot = self._adapter.parse_funding_snapshot(perp_raw)

            inserted_ticks = 0
            inserted_funding = 0

            for tick in (spot_tick, perp_tick):
                exists = session.execute(
                    select(MarketTick).where(
                        MarketTick.exchange == tick.exchange,
                        MarketTick.symbol == tick.symbol,
                        MarketTick.event_ts == tick.event_ts,
                    )
                ).first()
                if exists is None:
                    session.add(tick)
                    inserted_ticks += 1

            funding_exists = session.execute(
                select(FundingRateSnapshot).where(
                    FundingRateSnapshot.exchange == funding_snapshot.exchange,
                    FundingRateSnapshot.symbol == funding_snapshot.symbol,
                    FundingRateSnapshot.event_ts == funding_snapshot.event_ts,
                )
            ).first()
            if funding_exists is None:
                session.add(funding_snapshot)
                inserted_funding += 1

            session.commit()

            _log.info(
                "collector_poll_cycle_succeeded",
                spot_symbol=self._config.spot_symbol,
                perp_symbol=self._config.perp_symbol,
                spot_bid=str(spot_tick.bid_price),
                spot_ask=str(spot_tick.ask_price),
                perp_bid=str(perp_tick.bid_price),
                perp_ask=str(perp_tick.ask_price),
                funding_rate=str(funding_snapshot.funding_rate),
                inserted_market_ticks=inserted_ticks,
                inserted_funding_snapshots=inserted_funding,
                cycle_ts=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            session.rollback()
            _log.exception(
                "collector_poll_cycle_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                spot_symbol=self._config.spot_symbol,
                perp_symbol=self._config.perp_symbol,
            )

    def _install_signal_handlers(self) -> None:
        def _handle_sigterm(signum, _frame) -> None:  # type: ignore[no-untyped-def]
            _log.info("collector_signal_received", signal=signum)
            self._running = False

        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_sigterm)
