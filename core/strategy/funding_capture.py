from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.order_intent import OrderIntent
from core.models.position_snapshot import PositionSnapshot
from core.models.strategy_signal import StrategySignal


@dataclass(frozen=True)
class FundingCaptureConfig:
    """Configuration for the funding-rate capture strategy.

    spot_symbol and perp_symbol are separate because OrderIntent has no
    instrument_type field — the two legs are distinguished by symbol alone.
    """

    spot_symbol: str
    perp_symbol: str
    exchange: str
    entry_funding_rate_threshold: Decimal
    exit_funding_rate_threshold: Decimal
    position_size: Decimal
    mode: str = "paper"


class FundingCaptureStrategy:
    """Funding-rate capture strategy: spot long + perp short delta-neutral pair.

    evaluate() inspects the current funding rate and open position state,
    then writes StrategySignals and OrderIntents as needed.
    It does not commit; transaction ownership remains with the caller.
    """

    def __init__(self, config: FundingCaptureConfig) -> None:
        self.config = config

    def evaluate(
        self,
        session: Session,
        funding_rate: Decimal,
        mark_price: Decimal,
    ) -> Literal["entered", "exited", "no_action"]:
        """Evaluate current market conditions and emit signals + intents if warranted.

        Returns:
            "entered"   -- entry signal and two opening OrderIntents were created.
            "exited"    -- exit signal and two closing OrderIntents were created.
            "no_action" -- conditions not met; nothing was written.
        """
        open_position = self._open_perp_position(session)

        if open_position is None and funding_rate >= self.config.entry_funding_rate_threshold:
            self._enter(session, funding_rate, mark_price)
            return "entered"

        if open_position is not None and funding_rate <= self.config.exit_funding_rate_threshold:
            self._exit(session, funding_rate, mark_price)
            return "exited"

        return "no_action"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_perp_position(self, session: Session) -> PositionSnapshot | None:
        """Return the most recent open perp position, or None if flat."""
        return (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.exchange == self.config.exchange)
                .where(PositionSnapshot.symbol == self.config.perp_symbol)
                .where(PositionSnapshot.account_name == self.config.mode)
                .where(PositionSnapshot.quantity > 0)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )

    def _persist_signal(
        self,
        session: Session,
        signal_type: str,
        funding_rate: Decimal,
        mark_price: Decimal,
    ) -> StrategySignal:
        signal = StrategySignal(
            strategy_name="funding_capture",
            strategy_version="1.0",
            symbol=self.config.perp_symbol,
            signal_type=signal_type,
            signal_strength=funding_rate,
            decision_json={
                "funding_rate": str(funding_rate),
                "mark_price": str(mark_price),
                "position_size": str(self.config.position_size),
            },
            reason_code=signal_type,
            created_ts=datetime.now(timezone.utc),
        )
        session.add(signal)
        return signal

    def _make_intent(
        self,
        signal: StrategySignal,
        symbol: str,
        side: str,
        reduce_only: bool,
    ) -> OrderIntent:
        return OrderIntent(
            strategy_signal_id=signal.id,
            portfolio_id=None,
            mode=self.config.mode,
            exchange=self.config.exchange,
            symbol=symbol,
            side=side,
            order_type="market",
            time_in_force=None,
            quantity=self.config.position_size,
            limit_price=None,
            reduce_only=reduce_only,
            post_only=False,
            client_order_id=None,
            status="pending",
            created_ts=datetime.now(timezone.utc),
        )

    def _enter(
        self, session: Session, funding_rate: Decimal, mark_price: Decimal
    ) -> None:
        signal = self._persist_signal(session, "enter_funding_capture", funding_rate, mark_price)
        spot_intent = self._make_intent(signal, self.config.spot_symbol, "buy", reduce_only=False)
        perp_intent = self._make_intent(signal, self.config.perp_symbol, "sell", reduce_only=False)
        session.add(spot_intent)
        session.add(perp_intent)

    def _exit(
        self, session: Session, funding_rate: Decimal, mark_price: Decimal
    ) -> None:
        signal = self._persist_signal(session, "exit_funding_capture", funding_rate, mark_price)
        spot_intent = self._make_intent(signal, self.config.spot_symbol, "sell", reduce_only=True)
        perp_intent = self._make_intent(signal, self.config.perp_symbol, "buy", reduce_only=True)
        session.add(spot_intent)
        session.add(perp_intent)
