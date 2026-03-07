"""Alert evaluator for the crypto-mvp paper trading system.

Evaluates four system conditions on demand and returns AlertResult objects.
The caller (PaperTradingLoop) owns the transaction; this module only adds
RiskEvent rows for critical alerts and flushes — it does not commit.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent
from core.utils.logging import get_logger

_log = get_logger(__name__)


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


@dataclass(frozen=True)
class AlertConfig:
    exchange: str
    symbol: str
    account_name: str
    stale_data_threshold_seconds: int
    drawdown_threshold: Decimal  # negative value, e.g. Decimal("-500")
    no_fill_threshold_seconds: int
    min_funding_rate: Decimal
    spot_symbol: str = ""
    perp_symbol: str = ""
    mismatch_tolerance: Decimal = Decimal("0.01")


@dataclass
class AlertResult:
    alert_type: str
    severity: str  # "info", "warning", "critical"
    message: str
    risk_event: RiskEvent | None = None


class AlertEvaluator:
    """Evaluates all alert conditions for a given AlertConfig.

    Call evaluate(session) at the end of each paper trading iteration
    (before commit). Returns one AlertResult per triggered condition.
    Does not commit — the caller owns the transaction.
    """

    def __init__(self, config: AlertConfig) -> None:
        self._config = config

    def evaluate(self, session: Session, now: datetime | None = None) -> list[AlertResult]:
        if now is None:
            now = datetime.now(timezone.utc)
        results: list[AlertResult] = []

        alert = self._check_stale_funding_data(session, now)
        if alert:
            results.append(alert)

        alert = self._check_position_pnl_drawdown(session, now)
        if alert:
            results.append(alert)

        alert = self._check_open_position_no_recent_fill(session, now)
        if alert:
            results.append(alert)

        alert = self._check_no_funding_edge(session)
        if alert:
            results.append(alert)

        alert = self._check_exchange_disconnected(session, now)
        if alert:
            results.append(alert)

        alert = self._check_order_rejected(session, now)
        if alert:
            results.append(alert)

        alert = self._check_strategy_disabled(session)
        if alert:
            results.append(alert)

        alert = self._check_position_mismatch(session, now)
        if alert:
            results.append(alert)

        alert = self._check_daily_loss_threshold_hit(session, now)
        if alert:
            results.append(alert)

        for result in results:
            _log.warning(
                "alert_triggered",
                alert_type=result.alert_type,
                severity=result.severity,
                message=result.message,
                account_name=self._config.account_name,
            )

        return results

    # ------------------------------------------------------------------
    # Individual alert checks
    # ------------------------------------------------------------------

    def _check_stale_funding_data(
        self, session: Session, now: datetime
    ) -> AlertResult | None:
        """Trigger if latest FundingRateSnapshot for exchange+symbol is too old."""
        latest_ts = session.execute(
            select(func.max(FundingRateSnapshot.event_ts))
            .where(FundingRateSnapshot.exchange == self._config.exchange)
            .where(FundingRateSnapshot.symbol == self._config.symbol)
        ).scalar_one()

        if latest_ts is None:
            message = (
                f"No funding rate data found for "
                f"{self._config.exchange}/{self._config.symbol}"
            )
            return AlertResult(
                alert_type="stale_funding_data",
                severity="warning",
                message=message,
            )

        # Ensure timezone-aware comparison
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        age_seconds = (now - latest_ts).total_seconds()
        if age_seconds > self._config.stale_data_threshold_seconds:
            message = (
                f"Funding rate data for {self._config.exchange}/{self._config.symbol} "
                f"is {int(age_seconds)}s old "
                f"(threshold: {self._config.stale_data_threshold_seconds}s)"
            )
            return AlertResult(
                alert_type="stale_funding_data",
                severity="warning",
                message=message,
            )
        return None

    def _check_position_pnl_drawdown(
        self, session: Session, now: datetime
    ) -> AlertResult | None:
        """Trigger if realized_pnl + funding_paid falls below drawdown_threshold.

        Uses the same aggregate queries as get_pnl_summary in
        core/reporting/queries.py to avoid duplicating logic.
        """
        realized_pnl = _to_decimal(
            session.execute(
                select(func.sum(PnLSnapshot.realized_pnl)).where(
                    PnLSnapshot.strategy_name == self._config.account_name
                )
            ).scalar_one()
        )
        funding_paid = _to_decimal(
            session.execute(
                select(func.sum(FundingPayment.payment_amount)).where(
                    FundingPayment.account_name == self._config.account_name
                )
            ).scalar_one()
        )
        net = realized_pnl + funding_paid

        if net < self._config.drawdown_threshold:
            message = (
                f"PnL drawdown for {self._config.account_name}: "
                f"realized={realized_pnl}, funding_paid={funding_paid}, "
                f"net={net} < threshold={self._config.drawdown_threshold}"
            )
            risk_event = RiskEvent(
                id=uuid.uuid4(),
                event_type="alert",
                severity="critical",
                strategy_name=self._config.account_name,
                symbol=self._config.symbol,
                rule_name="position_pnl_drawdown",
                details_json={
                    "account_name": self._config.account_name,
                    "realized_pnl": str(realized_pnl),
                    "funding_paid": str(funding_paid),
                    "net_pnl": str(net),
                    "drawdown_threshold": str(self._config.drawdown_threshold),
                },
                created_ts=now,
            )
            session.add(risk_event)
            session.flush()
            return AlertResult(
                alert_type="position_pnl_drawdown",
                severity="critical",
                message=message,
                risk_event=risk_event,
            )
        return None

    def _check_open_position_no_recent_fill(
        self, session: Session, now: datetime
    ) -> AlertResult | None:
        """Trigger if there is an open position but no fill in the last N seconds."""
        # Check for any open position (quantity > 0)
        has_open_position = session.execute(
            select(func.count(PositionSnapshot.id))
            .where(PositionSnapshot.account_name == self._config.account_name)
            .where(PositionSnapshot.quantity > 0)
        ).scalar_one()

        if not has_open_position:
            return None

        # Find the most recent fill for this account
        cutoff = now.timestamp() - self._config.no_fill_threshold_seconds
        latest_fill_ts = session.execute(
            select(func.max(FillRecord.fill_ts))
            .select_from(FillRecord)
            .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
            .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
            .where(OrderIntent.mode == self._config.account_name)
        ).scalar_one()

        if latest_fill_ts is None:
            message = (
                f"Account {self._config.account_name} has open position "
                f"but no fills recorded"
            )
            return AlertResult(
                alert_type="open_position_no_recent_fill",
                severity="warning",
                message=message,
            )

        if latest_fill_ts.tzinfo is None:
            latest_fill_ts = latest_fill_ts.replace(tzinfo=timezone.utc)

        fill_age_seconds = (now - latest_fill_ts).total_seconds()
        if fill_age_seconds > self._config.no_fill_threshold_seconds:
            message = (
                f"Account {self._config.account_name} has open position "
                f"but last fill was {int(fill_age_seconds)}s ago "
                f"(threshold: {self._config.no_fill_threshold_seconds}s)"
            )
            return AlertResult(
                alert_type="open_position_no_recent_fill",
                severity="warning",
                message=message,
            )
        return None

    def _check_no_funding_edge(self, session: Session) -> AlertResult | None:
        """Trigger if latest funding rate is below min_funding_rate threshold."""
        latest_snapshot = session.execute(
            select(FundingRateSnapshot)
            .where(FundingRateSnapshot.exchange == self._config.exchange)
            .where(FundingRateSnapshot.symbol == self._config.symbol)
            .order_by(FundingRateSnapshot.event_ts.desc())
            .limit(1)
        ).scalars().first()

        if latest_snapshot is None:
            return None

        current_rate = _to_decimal(latest_snapshot.funding_rate)
        if current_rate < self._config.min_funding_rate:
            message = (
                f"Funding rate for {self._config.exchange}/{self._config.symbol} "
                f"is {current_rate} < min threshold {self._config.min_funding_rate}"
            )
            return AlertResult(
                alert_type="no_funding_edge",
                severity="info",
                message=message,
            )
        return None

    def _check_exchange_disconnected(
        self, session: Session, now: datetime
    ) -> AlertResult | None:
        """Trigger critical alert when funding data is very stale (2x threshold)."""
        latest_ts = session.execute(
            select(func.max(FundingRateSnapshot.event_ts))
            .where(FundingRateSnapshot.exchange == self._config.exchange)
            .where(FundingRateSnapshot.symbol == self._config.symbol)
        ).scalar_one()

        # Keep this condition focused on "very stale" streams.
        # If there is no data at all, stale_funding_data already emits a warning.
        if latest_ts is None:
            return None

        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        age_seconds = (now - latest_ts).total_seconds()
        critical_threshold = self._config.stale_data_threshold_seconds * 2
        if age_seconds <= critical_threshold:
            return None

        message = (
            f"Exchange feed appears disconnected for "
            f"{self._config.exchange}/{self._config.symbol}: "
            f"latest funding snapshot is {int(age_seconds)}s old "
            f"(critical threshold: {critical_threshold}s)"
        )
        risk_event = RiskEvent(
            id=uuid.uuid4(),
            event_type="alert",
            severity="critical",
            strategy_name=self._config.account_name,
            symbol=self._config.symbol,
            rule_name="exchange_disconnected",
            details_json={
                "exchange": self._config.exchange,
                "symbol": self._config.symbol,
                "age_seconds": int(age_seconds),
                "critical_threshold_seconds": critical_threshold,
            },
            created_ts=now,
        )
        session.add(risk_event)
        session.flush()
        return AlertResult(
            alert_type="exchange_disconnected",
            severity="critical",
            message=message,
            risk_event=risk_event,
        )

    def _check_order_rejected(self, session: Session, now: datetime) -> AlertResult | None:
        """Trigger warning when recent rejected order intents exist."""
        window_start = now - timedelta(seconds=self._config.no_fill_threshold_seconds)
        reject_count = int(
            session.execute(
                select(func.count(OrderIntent.id))
                .where(OrderIntent.mode == self._config.account_name)
                .where(OrderIntent.status == "rejected")
                .where(OrderIntent.created_ts >= window_start)
                .where(OrderIntent.created_ts <= now)
            ).scalar_one()
        )
        if reject_count == 0:
            return None

        message = (
            f"Account {self._config.account_name} has {reject_count} rejected order(s) "
            f"within the last {self._config.no_fill_threshold_seconds}s"
        )
        return AlertResult(
            alert_type="order_rejected",
            severity="warning",
            message=message,
        )

    def _check_strategy_disabled(self, session: Session) -> AlertResult | None:
        """Trigger warning when kill switch fired and no successful fill happened after."""
        latest_kill_switch_ts = session.execute(
            select(func.max(RiskEvent.created_ts))
            .where(RiskEvent.strategy_name == self._config.account_name)
            .where(RiskEvent.rule_name == "kill_switch_active")
        ).scalar_one()
        if latest_kill_switch_ts is None:
            return None

        latest_filled_intent_ts = session.execute(
            select(func.max(OrderIntent.created_ts))
            .where(OrderIntent.mode == self._config.account_name)
            .where(OrderIntent.status == "filled")
        ).scalar_one()

        if latest_filled_intent_ts is None or latest_kill_switch_ts > latest_filled_intent_ts:
            message = (
                f"Strategy appears disabled for {self._config.account_name}: "
                f"kill switch has fired and no filled order intent exists after it"
            )
            return AlertResult(
                alert_type="strategy_disabled",
                severity="warning",
                message=message,
            )
        return None

    def _check_position_mismatch(self, session: Session, now: datetime) -> AlertResult | None:
        """Trigger critical alert when spot/perp legs are unmatched beyond tolerance."""
        if not self._config.spot_symbol or not self._config.perp_symbol:
            return None

        spot_qty = _to_decimal(
            session.execute(
                select(PositionSnapshot.quantity)
                .where(PositionSnapshot.account_name == self._config.account_name)
                .where(PositionSnapshot.exchange == self._config.exchange)
                .where(PositionSnapshot.symbol == self._config.spot_symbol)
                .order_by(PositionSnapshot.snapshot_ts.desc())
                .limit(1)
            ).scalar_one_or_none()
        )
        perp_qty = _to_decimal(
            session.execute(
                select(PositionSnapshot.quantity)
                .where(PositionSnapshot.account_name == self._config.account_name)
                .where(PositionSnapshot.exchange == self._config.exchange)
                .where(PositionSnapshot.symbol == self._config.perp_symbol)
                .order_by(PositionSnapshot.snapshot_ts.desc())
                .limit(1)
            ).scalar_one_or_none()
        )

        one_leg_zero = (
            (spot_qty == Decimal("0") and perp_qty > Decimal("0"))
            or (perp_qty == Decimal("0") and spot_qty > Decimal("0"))
        )
        qty_diff = abs(spot_qty - perp_qty)
        beyond_tolerance = qty_diff > self._config.mismatch_tolerance

        if not one_leg_zero and not beyond_tolerance:
            return None

        message = (
            f"Position mismatch for {self._config.account_name}: "
            f"spot_qty={spot_qty}, perp_qty={perp_qty}, "
            f"difference={qty_diff}, tolerance={self._config.mismatch_tolerance}"
        )
        risk_event = RiskEvent(
            id=uuid.uuid4(),
            event_type="alert",
            severity="critical",
            strategy_name=self._config.account_name,
            symbol=self._config.symbol,
            rule_name="position_mismatch",
            details_json={
                "exchange": self._config.exchange,
                "account_name": self._config.account_name,
                "spot_symbol": self._config.spot_symbol,
                "perp_symbol": self._config.perp_symbol,
                "spot_quantity": str(spot_qty),
                "perp_quantity": str(perp_qty),
                "difference": str(qty_diff),
                "mismatch_tolerance": str(self._config.mismatch_tolerance),
            },
            created_ts=now,
        )
        session.add(risk_event)
        session.flush()
        return AlertResult(
            alert_type="position_mismatch",
            severity="critical",
            message=message,
            risk_event=risk_event,
        )

    def _check_daily_loss_threshold_hit(
        self, session: Session, now: datetime
    ) -> AlertResult | None:
        """Trigger critical alert if current UTC-day realized+funding drops below threshold."""
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        day_realized = _to_decimal(
            session.execute(
                select(func.sum(PnLSnapshot.realized_pnl))
                .where(PnLSnapshot.strategy_name == self._config.account_name)
                .where(PnLSnapshot.snapshot_ts >= day_start)
                .where(PnLSnapshot.snapshot_ts < day_end)
            ).scalar_one()
        )
        day_funding = _to_decimal(
            session.execute(
                select(func.sum(FundingPayment.payment_amount))
                .where(FundingPayment.account_name == self._config.account_name)
                .where(FundingPayment.accrued_ts >= day_start)
                .where(FundingPayment.accrued_ts < day_end)
            ).scalar_one()
        )
        day_net = day_realized + day_funding

        # Avoid duplicate critical events when cumulative drawdown condition already captures
        # the same breach in this exact evaluator pass.
        cumulative_net = _to_decimal(
            session.execute(
                select(func.sum(PnLSnapshot.realized_pnl))
                .where(PnLSnapshot.strategy_name == self._config.account_name)
            ).scalar_one()
        ) + _to_decimal(
            session.execute(
                select(func.sum(FundingPayment.payment_amount))
                .where(FundingPayment.account_name == self._config.account_name)
            ).scalar_one()
        )

        if day_net >= self._config.drawdown_threshold or cumulative_net < self._config.drawdown_threshold:
            return None

        message = (
            f"Daily loss threshold hit for {self._config.account_name}: "
            f"daily_realized={day_realized}, daily_funding={day_funding}, "
            f"daily_net={day_net} < threshold={self._config.drawdown_threshold}"
        )
        risk_event = RiskEvent(
            id=uuid.uuid4(),
            event_type="alert",
            severity="critical",
            strategy_name=self._config.account_name,
            symbol=self._config.symbol,
            rule_name="daily_loss_threshold_hit",
            details_json={
                "account_name": self._config.account_name,
                "daily_realized_pnl": str(day_realized),
                "daily_funding_paid": str(day_funding),
                "daily_net_pnl": str(day_net),
                "drawdown_threshold": str(self._config.drawdown_threshold),
                "day_start": day_start.isoformat(),
            },
            created_ts=now,
        )
        session.add(risk_event)
        session.flush()
        return AlertResult(
            alert_type="daily_loss_threshold_hit",
            severity="critical",
            message=message,
            risk_event=risk_event,
        )
