from __future__ import annotations

import signal
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.collector.kraken_auth import KrakenAuthAdapter
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy
from core.utils.logging import get_logger

_log = get_logger(__name__)


class SignalLogger:
    """Dry-run loop that logs market-making signals from live order-book snapshots."""

    def __init__(
        self,
        config: MarketMakingConfig,
        auth_adapter: KrakenAuthAdapter,
        session_factory: Callable[[], Session],
        poll_interval_seconds: int = 60,
    ) -> None:
        self._config = config
        self._auth_adapter = auth_adapter
        self._session_factory = session_factory
        self._poll_interval_seconds = poll_interval_seconds
        self._strategy = MarketMakingStrategy(config)
        self._running = True

    def run(self) -> None:
        self._install_signal_handlers()
        _log.info(
            "signal_logger_starting",
            exchange=self._config.exchange,
            symbol=self._config.symbol,
            poll_interval_seconds=self._poll_interval_seconds,
        )

        try:
            while self._running:
                session = self._session_factory()
                try:
                    self._log_once(session)
                except Exception as exc:  # pragma: no cover - run-loop safeguard
                    _log.exception(
                        "signal_cycle_failed",
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                finally:
                    session.close()

                if self._running:
                    time.sleep(self._poll_interval_seconds)
        except KeyboardInterrupt:
            _log.info("signal_logger_keyboard_interrupt_received")
        finally:
            _log.info("signal_logger_stopped")

    def _log_once(self, session: Session) -> None:
        try:
            if not self._auth_adapter.verify_no_open_orders():
                _log.warning("unexpected_open_orders_found")
                return

            snapshot = (
                session.execute(
                    select(OrderBookSnapshot)
                    .where(OrderBookSnapshot.exchange == self._config.exchange)
                    .where(OrderBookSnapshot.symbol == self._config.symbol)
                    .order_by(OrderBookSnapshot.event_ts.desc())
                )
                .scalars()
                .first()
            )
            if snapshot is None:
                _log.info("no_order_book_available")
                return

            balances = self._auth_adapter.get_account_balance()
            xbt_balance = self._first_balance(balances, ["XXBT", "XBT"])
            usd_balance = self._first_balance(balances, ["ZUSD", "USD"])
            _log.info(
                "account_balance_snapshot",
                xbt_balance=str(xbt_balance),
                usd_balance=str(usd_balance),
            )

            current_position = self._current_position(
                session=session,
                exchange=self._config.exchange,
                symbol=self._config.symbol,
                account_name=self._config.account_name,
            )

            intents = self._strategy.evaluate(
                session,
                snapshot,
                current_position,
                datetime.now(timezone.utc),
            )

            for intent in intents:
                _log.info(
                    "signal_generated",
                    side=intent.side,
                    limit_price=(str(intent.limit_price) if intent.limit_price is not None else None),
                    quantity=str(intent.quantity),
                    mid_price=(str(snapshot.mid_price) if snapshot.mid_price is not None else None),
                    market_spread_bps=(
                        str(snapshot.spread_bps) if snapshot.spread_bps is not None else None
                    ),
                    our_spread_bps=str(self._config.spread_bps),
                    current_position=str(current_position),
                    account_balance_usd=str(usd_balance),
                )

            _log.info(
                "signal_cycle_complete",
                intents_count=len(intents),
                cycle_ts=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            _log.exception(
                "signal_cycle_exception",
                error=str(exc),
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _first_balance(balances: dict[str, Decimal], candidates: list[str]) -> Decimal:
        for key in candidates:
            if key in balances:
                return balances[key]
        return Decimal("0")

    @staticmethod
    def _current_position(
        session: Session,
        exchange: str,
        symbol: str,
        account_name: str,
    ) -> Decimal:
        latest = (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.exchange == exchange)
                .where(PositionSnapshot.symbol == symbol)
                .where(PositionSnapshot.account_name == account_name)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if latest is None:
            return Decimal("0")

        qty = Decimal(str(latest.quantity))
        side = (latest.side or "").strip().lower()
        return qty if side == "buy" else -qty

    def _install_signal_handlers(self) -> None:
        def _handle_sigterm(signum, _frame) -> None:  # type: ignore[no-untyped-def]
            _log.info("signal_logger_signal_received", signal=signum)
            self._running = False

        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_sigterm)
