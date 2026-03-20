from __future__ import annotations

import signal
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.collector.kraken_rest import CollectorConfig, CollectorError, KrakenRestAdapter
from core.exchange.coinbase_advanced import CoinbaseAdvancedAdapter
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot
from core.utils.logging import get_logger

_log = get_logger(__name__)


class CollectorLoop:
    """REST polling loop that ingests Kraken spot and Kraken futures data."""

    def __init__(
        self,
        config: CollectorConfig,
        adapter: KrakenRestAdapter,
        coinbase_adapter: CoinbaseAdvancedAdapter | None,
        session_factory: Callable[[], Session],
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._coinbase_adapter = coinbase_adapter
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
            eth_spot_adapter = KrakenRestAdapter(
                CollectorConfig(
                    spot_exchange=self._config.spot_exchange,
                    perp_exchange=self._config.perp_exchange,
                    spot_symbol="ETHUSD",
                    perp_symbol=self._config.perp_symbol,
                    spot_exchange_symbol="ETHUSD",
                    perp_exchange_symbol=self._config.perp_exchange_symbol,
                    adapter_name=self._config.adapter_name,
                    poll_interval_seconds=self._config.poll_interval_seconds,
                    spot_base_url=self._config.spot_base_url,
                    futures_base_url=self._config.futures_base_url,
                    request_timeout_seconds=self._config.request_timeout_seconds,
                )
            )
            eth_spot_raw = eth_spot_adapter.fetch_spot_ticker()
            order_book_raw = self._adapter.fetch_order_book()
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
            eth_spot_tick = eth_spot_adapter.parse_spot_tick(eth_spot_raw)
            order_book_snapshot = self._adapter.parse_order_book_snapshot(order_book_raw)
            perp_tick = self._adapter.parse_perp_tick(perp_raw)
            funding_snapshot = self._adapter.parse_funding_snapshot(perp_raw)

            inserted_ticks = 0
            inserted_funding = 0
            inserted_order_book = 0

            for tick in (spot_tick, eth_spot_tick, perp_tick):
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

            order_book_exists = session.execute(
                select(OrderBookSnapshot).where(
                    OrderBookSnapshot.exchange == order_book_snapshot.exchange,
                    OrderBookSnapshot.symbol == order_book_snapshot.symbol,
                    OrderBookSnapshot.event_ts == order_book_snapshot.event_ts,
                )
            ).first()
            if order_book_exists is None:
                session.add(order_book_snapshot)
                inserted_order_book += 1

            coinbase_tick: MarketTick | None = None
            coinbase_funding_snapshot: FundingRateSnapshot | None = None
            inserted_coinbase_ticks = 0
            inserted_coinbase_funding = 0

            if self._coinbase_adapter is not None and self._coinbase_adapter.is_enabled:
                coinbase_tick = self._coinbase_adapter.get_ticker(symbol="ETH-PERP")
                coinbase_funding_snapshot = self._coinbase_adapter.get_funding_rate(
                    symbol="ETH-PERP"
                )

                if coinbase_tick is None or coinbase_funding_snapshot is None:
                    _log.warning(
                        "coinbase_data_missing",
                        exchange="coinbase_advanced",
                        symbol="ETH-PERP",
                        has_tick=coinbase_tick is not None,
                        has_funding=coinbase_funding_snapshot is not None,
                    )

                if coinbase_tick is not None:
                    exists_coinbase_tick = session.execute(
                        select(MarketTick).where(
                            MarketTick.exchange == coinbase_tick.exchange,
                            MarketTick.symbol == coinbase_tick.symbol,
                            MarketTick.event_ts == coinbase_tick.event_ts,
                        )
                    ).first()
                    if exists_coinbase_tick is None:
                        session.add(coinbase_tick)
                        inserted_coinbase_ticks += 1

                if coinbase_funding_snapshot is not None:
                    exists_coinbase_funding = session.execute(
                        select(FundingRateSnapshot).where(
                            FundingRateSnapshot.exchange == coinbase_funding_snapshot.exchange,
                            FundingRateSnapshot.symbol == coinbase_funding_snapshot.symbol,
                            FundingRateSnapshot.event_ts == coinbase_funding_snapshot.event_ts,
                        )
                    ).first()
                    if exists_coinbase_funding is None:
                        session.add(coinbase_funding_snapshot)
                        inserted_coinbase_funding += 1

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
                spread=str(order_book_snapshot.spread),
                inserted_market_ticks=inserted_ticks,
                inserted_funding_snapshots=inserted_funding,
                inserted_order_book_snapshots=inserted_order_book,
                inserted_coinbase_market_ticks=inserted_coinbase_ticks,
                inserted_coinbase_funding_snapshots=inserted_coinbase_funding,
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
