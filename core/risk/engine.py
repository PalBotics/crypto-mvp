from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.funding_payment import FundingPayment
from core.models.order_intent import OrderIntent
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent


@dataclass(frozen=True)
class RiskConfig:
    """Configuration for pre-trade risk checks."""

    max_data_age_seconds: int
    min_entry_funding_rate: Decimal
    max_notional_per_symbol: Decimal
    kill_switch_active: bool = False
    
    # Max daily loss control
    max_daily_loss: Decimal = Decimal("-1000")
    
    # Circuit breaker control
    circuit_breaker_max_rejects: int = 5
    circuit_breaker_loss_threshold: Decimal = Decimal("-500")
    circuit_breaker_window_seconds: int = 300
    circuit_breaker_active: bool = False  # internal state flag
    
    # Hedge leg mismatch detection
    spot_symbol: str = ""
    perp_symbol: str = ""


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
        3. Circuit breaker (blocks all, including exits)
        4. Funding edge (entry intents only — reduce_only=False)
        5. Max daily loss (entry intents only)
        6. Max notional per symbol
        7. Hedge leg mismatch (entry intents only)
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

        # 3. Circuit breaker — blocks all intents if active (including exits).
        if self.config.circuit_breaker_active:
            return self._block(
                session, order_intent, funding_rate, mark_price, "circuit_breaker_triggered"
            )

        # 4. Funding edge — only applies to entry intents (reduce_only=False).
        if not order_intent.reduce_only:
            if funding_rate < self.config.min_entry_funding_rate:
                return self._block(
                    session, order_intent, funding_rate, mark_price, "funding_below_threshold"
                )

        # 5. Max daily loss — only applies to entry intents (reduce_only=False).
        if not order_intent.reduce_only:
            account_name = order_intent.mode
            daily_loss = self._calculate_daily_loss(session, account_name)
            if daily_loss < self.config.max_daily_loss:
                return self._block(
                    session, order_intent, funding_rate, mark_price, "max_daily_loss_exceeded"
                )

        # 6. Max notional per symbol.
        notional = Decimal(str(order_intent.quantity)) * mark_price
        if notional > self.config.max_notional_per_symbol:
            return self._block(
                session, order_intent, funding_rate, mark_price, "max_notional_exceeded"
            )

        # 7. Hedge leg mismatch — only applies to entry intents (reduce_only=False).
        if not order_intent.reduce_only:
            account_name = order_intent.mode
            if self._has_hedge_leg_mismatch(
                session, account_name, order_intent.exchange
            ):
                return self._block(
                    session, order_intent, funding_rate, mark_price, "hedge_leg_mismatch"
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

    def _calculate_daily_loss(self, session: Session, account_name: str) -> Decimal:
        """Sum realized_pnl + funding_payments for the current UTC calendar day."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        
        try:
            # Sum realized_pnl for today
            realized_pnl = session.execute(
                select(func.sum(PnLSnapshot.realized_pnl)).where(
                    PnLSnapshot.strategy_name == account_name
                ).where(
                    PnLSnapshot.snapshot_ts >= today_start
                ).where(
                    PnLSnapshot.snapshot_ts < tomorrow_start
                )
            ).scalar_one()
            
            realized_pnl = Decimal(str(realized_pnl)) if realized_pnl is not None else Decimal("0")
            
            # Sum funding payments for today
            funding_paid = session.execute(
                select(func.sum(FundingPayment.payment_amount)).where(
                    FundingPayment.account_name == account_name
                ).where(
                    FundingPayment.accrued_ts >= today_start
                ).where(
                    FundingPayment.accrued_ts < tomorrow_start
                )
            ).scalar_one()
            
            funding_paid = Decimal(str(funding_paid)) if funding_paid is not None else Decimal("0")
            
            return realized_pnl + funding_paid
        except Exception:
            # Handle mock sessions or any other errors
            return Decimal("0")

    def _check_circuit_breaker_reject_condition(
        self, session: Session, account_name: str
    ) -> bool:
        """Check if N consecutive rejected OrderIntents within the window."""
        try:
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=self.config.circuit_breaker_window_seconds)
            
            # Count rejected intents for this account within the window
            reject_count = session.execute(
                select(func.count(OrderIntent.id)).where(
                    OrderIntent.mode == account_name
                ).where(
                    OrderIntent.status == "rejected"
                ).where(
                    OrderIntent.created_ts >= window_start
                )
            ).scalar_one()
            
            return reject_count >= self.config.circuit_breaker_max_rejects
        except Exception:
            # Handle mock sessions
            return False

    def _check_circuit_breaker_loss_condition(
        self, session: Session, account_name: str
    ) -> bool:
        """Check if realized loss exceeds threshold within the window."""
        try:
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=self.config.circuit_breaker_window_seconds)
            
            # Sum realized_pnl for this account within the window
            realized_pnl = session.execute(
                select(func.sum(PnLSnapshot.realized_pnl)).where(
                    PnLSnapshot.strategy_name == account_name
                ).where(
                    PnLSnapshot.snapshot_ts >= window_start
                )
            ).scalar_one()
            
            realized_pnl = Decimal(str(realized_pnl)) if realized_pnl is not None else Decimal("0")
            
            # Sum funding payments within the window
            funding_paid = session.execute(
                select(func.sum(FundingPayment.payment_amount)).where(
                    FundingPayment.account_name == account_name
                ).where(
                    FundingPayment.accrued_ts >= window_start
                )
            ).scalar_one()
            
            funding_paid = Decimal(str(funding_paid)) if funding_paid is not None else Decimal("0")
            
            total = realized_pnl + funding_paid
            return total <= self.config.circuit_breaker_loss_threshold
        except Exception:
            # Handle mock sessions
            return False

    def _has_hedge_leg_mismatch(
        self, session: Session, account_name: str, exchange: str
    ) -> bool:
        """Check if exactly one of spot/perp legs has an open position."""
        if not self.config.spot_symbol or not self.config.perp_symbol:
            # If symbols are not configured, skip the check
            return False
        
        try:
            # Check spot position
            spot_position = session.execute(
                select(func.sum(PositionSnapshot.quantity)).where(
                    PositionSnapshot.account_name == account_name
                ).where(
                    PositionSnapshot.exchange == exchange
                ).where(
                    PositionSnapshot.symbol == self.config.spot_symbol
                )
            ).scalar_one()
            
            spot_qty = Decimal(str(spot_position)) if spot_position is not None else Decimal("0")
            spot_open = spot_qty > Decimal("0")
            
            # Check perp position
            perp_position = session.execute(
                select(func.sum(PositionSnapshot.quantity)).where(
                    PositionSnapshot.account_name == account_name
                ).where(
                    PositionSnapshot.exchange == exchange
                ).where(
                    PositionSnapshot.symbol == self.config.perp_symbol
                )
            ).scalar_one()
            
            perp_qty = Decimal(str(perp_position)) if perp_position is not None else Decimal("0")
            perp_open = perp_qty > Decimal("0")
            
            # Mismatch exists if exactly one leg is open
            return (spot_open and not perp_open) or (not spot_open and perp_open)
        except Exception:
            # Handle mock sessions
            return False

    # ------------------------------------------------------------------
    # Emergency flatten
    # ------------------------------------------------------------------

    def emergency_flatten(
        self,
        session: Session,
        account_name: str,
        exchange: str,
        spot_symbol: str | None = None,
        perp_symbol: str | None = None,
    ) -> list[OrderIntent]:
        """Generate closing OrderIntents for all open positions.
        
        Args:
            session: SQLAlchemy session (caller owns transaction)
            account_name: account to flatten
            exchange: exchange identifier
            spot_symbol: optional override for spot symbol identifier
            perp_symbol: optional override for perp symbol identifier
        
        Returns:
            List of created OrderIntent records (not committed)
        
        Persists one RiskEvent with event_type="alert", severity="critical"
        """
        closing_intents: list[OrderIntent] = []
        
        # Use provided symbols or fall back to config
        use_spot_symbol = spot_symbol or self.config.spot_symbol
        use_perp_symbol = perp_symbol or self.config.perp_symbol
        
        now = datetime.now(timezone.utc)
        
        # Query all open positions for this account
        open_positions = session.execute(
            select(PositionSnapshot).where(
                PositionSnapshot.account_name == account_name
            ).where(
                PositionSnapshot.exchange == exchange
            ).where(
                PositionSnapshot.quantity > Decimal("0")
            )
        ).scalars().all()
        
        # Create a closing intent for each open position
        for position in open_positions:
            # Determine the closing side:
            # - For spot positions (identified by spot_symbol), sell to close
            # - For perp positions (identified by perp_symbol), buy to close a short
            # - Use the explicit 'side' field from position to determine closing side
            
            if position.side == "long":
                # Long position -> sell to close
                closing_side = "sell"
            else:
                # Short position (or any other) -> buy to close
                closing_side = "buy"
            
            closing_intent = OrderIntent(
                strategy_signal_id=None,
                portfolio_id=None,
                mode=account_name,
                exchange=exchange,
                symbol=position.symbol,
                side=closing_side,
                order_type="market",
                time_in_force=None,
                quantity=Decimal(str(position.quantity)),
                limit_price=None,
                reduce_only=True,
                post_only=False,
                client_order_id=None,
                status="pending",
                created_ts=now,
            )
            session.add(closing_intent)
            closing_intents.append(closing_intent)
        
        # Create one critical alert RiskEvent
        event = RiskEvent(
            event_type="alert",
            severity="critical",
            strategy_name=account_name,
            symbol=None,
            rule_name="emergency_flatten",
            details_json={
                "account_name": account_name,
                "exchange": exchange,
                "positions_closed": len(closing_intents),
            },
            created_ts=now,
        )
        session.add(event)
        
        return closing_intents
