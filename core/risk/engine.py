from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from core.models.order_intent import OrderIntent
from core.models.risk_event import RiskEvent


@dataclass(frozen=True)
class RiskConfig:
    """Configuration for pre-trade risk checks."""

    max_data_age_seconds: int
    min_entry_funding_rate: Decimal
    max_notional_per_symbol: Decimal
    kill_switch_active: bool = False


@dataclass(frozen=True)
class RiskCheckResult:
    """Result of a single risk engine evaluation."""

    passed: bool
    reason: str | None
    risk_event: RiskEvent | None


class RiskEngine:
    """Pre-trade risk gate: runs hard-limit checks before order execution.

    Checks are evaluated in strict order; the first failure short-circuits
    and returns immediately. Nothing is committed here — the caller owns
    the transaction.

    Check order:
        1. Kill switch
        2. Stale funding data
        3. Funding edge (entry intents only — reduce_only=False)
        4. Max notional per symbol
    """

    def __init__(self, config: RiskConfig) -> None:
        self.config = config

    def check(
        self,
        session: Session,
        order_intent: OrderIntent,
        funding_rate: Decimal,
        mark_price: Decimal,
        latest_funding_ts: datetime,
    ) -> RiskCheckResult:
        """Run all pre-trade checks in order. Returns on the first failure."""

        # 1. Kill switch — unconditional block.
        if self.config.kill_switch_active:
            return self._block(
                session, order_intent, funding_rate, mark_price, "kill_switch_active"
            )

        # 2. Stale funding data.
        age_seconds = (datetime.now(timezone.utc) - latest_funding_ts).total_seconds()
        if age_seconds > self.config.max_data_age_seconds:
            return self._block(
                session, order_intent, funding_rate, mark_price, "stale_funding_data"
            )

        # 3. Funding edge — only applies to entry intents (reduce_only=False).
        if not order_intent.reduce_only:
            if funding_rate < self.config.min_entry_funding_rate:
                return self._block(
                    session, order_intent, funding_rate, mark_price, "funding_below_threshold"
                )

        # 4. Max notional per symbol.
        notional = Decimal(str(order_intent.quantity)) * mark_price
        if notional > self.config.max_notional_per_symbol:
            return self._block(
                session, order_intent, funding_rate, mark_price, "max_notional_exceeded"
            )

        return RiskCheckResult(passed=True, reason=None, risk_event=None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _block(
        self,
        session: Session,
        order_intent: OrderIntent,
        funding_rate: Decimal,
        mark_price: Decimal,
        reason: str,
    ) -> RiskCheckResult:
        event = RiskEvent(
            event_type="risk_block",
            severity="high",
            strategy_name=order_intent.mode,
            symbol=order_intent.symbol,
            rule_name=reason,
            details_json={
                "exchange": order_intent.exchange,
                "account_name": order_intent.mode,
                "funding_rate": str(funding_rate),
                "mark_price": str(mark_price),
                "order_intent_id": (
                    str(order_intent.id) if order_intent.id is not None else None
                ),
            },
            created_ts=datetime.now(timezone.utc),
        )
        session.add(event)
        return RiskCheckResult(passed=False, reason=reason, risk_event=event)
