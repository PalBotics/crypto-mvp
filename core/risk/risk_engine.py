from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config.settings import get_settings
from core.models.market_tick import MarketTick
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent
from core.utils.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    reason: str | None = None


class RiskEngine:
    def __init__(self, account_name: str, db: Session) -> None:
        self.account_name = account_name
        self.db = db
        settings = get_settings()
        self.risk_max_notional_usd = Decimal(str(settings.risk_max_notional_usd))
        self.risk_max_symbol_notional_usd = Decimal(str(settings.risk_max_symbol_notional_usd))

    def check_data_freshness(
        self,
        exchange: str,
        symbol: str,
        max_age_seconds: int = 120,
    ) -> RiskCheckResult:
        latest_tick = (
            self.db.execute(
                select(MarketTick)
                .where(MarketTick.exchange == exchange)
                .where(MarketTick.symbol == symbol)
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )

        if latest_tick is None:
            self._fire_risk_event(
                event_type="stale_feed",
                severity="warning",
                details=f"{exchange}/{symbol} age=unknown",
            )
            _log.warning(
                "stale_feed_detected",
                account_name=self.account_name,
                exchange=exchange,
                symbol=symbol,
                age_seconds=None,
            )
            return RiskCheckResult(passed=False, reason="stale_feed")

        now_utc = datetime.now(timezone.utc)
        age_seconds = max(0, int((now_utc - latest_tick.event_ts).total_seconds()))
        if age_seconds > max_age_seconds:
            self._fire_risk_event(
                event_type="stale_feed",
                severity="warning",
                details=f"{exchange}/{symbol} age={age_seconds:.0f}s",
            )
            _log.warning(
                "stale_feed_detected",
                account_name=self.account_name,
                exchange=exchange,
                symbol=symbol,
                age_seconds=age_seconds,
            )
            return RiskCheckResult(passed=False, reason="stale_feed")

        return RiskCheckResult(passed=True)

    def check_max_notional(
        self,
        account_name: str,
        proposed_additional_usd: Decimal = Decimal("0"),
    ) -> RiskCheckResult:
        rows = (
            self.db.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .where(PositionSnapshot.quantity > 0)
            )
            .scalars()
            .all()
        )

        total = Decimal("0")
        for row in rows:
            qty = Decimal(str(row.quantity or 0))
            px = (
                Decimal(str(row.mark_price))
                if row.mark_price is not None
                else Decimal(str(row.avg_entry_price or 0))
            )
            total += qty * px

        combined = total + Decimal(str(proposed_additional_usd))
        if combined > self.risk_max_notional_usd:
            self._fire_risk_event(
                event_type="max_notional_exceeded",
                severity="warning",
                details=f"total={combined:.2f} limit={self.risk_max_notional_usd}",
            )
            _log.warning(
                "max_notional_exceeded",
                account_name=account_name,
                total=str(combined),
                limit=str(self.risk_max_notional_usd),
            )
            return RiskCheckResult(passed=False, reason="max_notional_exceeded")

        return RiskCheckResult(passed=True)

    def check_max_symbol_notional(
        self,
        symbol: str,
        proposed_additional_usd: Decimal = Decimal("0"),
    ) -> RiskCheckResult:
        rows = (
            self.db.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == self.account_name)
                .where(PositionSnapshot.symbol == symbol)
                .where(PositionSnapshot.quantity > 0)
            )
            .scalars()
            .all()
        )

        total = Decimal("0")
        for row in rows:
            qty = Decimal(str(row.quantity or 0))
            px = (
                Decimal(str(row.mark_price))
                if row.mark_price is not None
                else Decimal(str(row.avg_entry_price or 0))
            )
            total += qty * px

        combined = total + Decimal(str(proposed_additional_usd))
        if combined > self.risk_max_symbol_notional_usd:
            self._fire_risk_event(
                event_type="max_symbol_notional_exceeded",
                severity="warning",
                details=f"symbol={symbol} total={combined:.2f}",
            )
            _log.warning(
                "max_symbol_notional_exceeded",
                account_name=self.account_name,
                symbol=symbol,
                total=str(combined),
                limit=str(self.risk_max_symbol_notional_usd),
            )
            return RiskCheckResult(passed=False, reason="max_symbol_notional_exceeded")

        return RiskCheckResult(passed=True)

    def run_preflight(
        self,
        exchanges_to_check: list[tuple[str, str]],
        proposed_notional_usd: Decimal = Decimal("0"),
        proposed_symbol: str | None = None,
    ) -> RiskCheckResult:
        for exchange, symbol in exchanges_to_check:
            freshness = self.check_data_freshness(exchange=exchange, symbol=symbol)
            if not freshness.passed:
                _log.warning(
                    "risk_preflight_failed",
                    account_name=self.account_name,
                    reason=freshness.reason,
                )
                return freshness

        max_notional = self.check_max_notional(
            account_name=self.account_name,
            proposed_additional_usd=proposed_notional_usd,
        )
        if not max_notional.passed:
            _log.warning(
                "risk_preflight_failed",
                account_name=self.account_name,
                reason=max_notional.reason,
            )
            return max_notional

        if proposed_symbol:
            max_symbol = self.check_max_symbol_notional(
                symbol=proposed_symbol,
                proposed_additional_usd=proposed_notional_usd,
            )
            if not max_symbol.passed:
                _log.warning(
                    "risk_preflight_failed",
                    account_name=self.account_name,
                    reason=max_symbol.reason,
                )
                return max_symbol

        _log.info("risk_preflight_passed", account_name=self.account_name)
        return RiskCheckResult(passed=True)

    def _fire_risk_event(self, event_type: str, severity: str, details: str) -> None:
        self.db.add(
            RiskEvent(
                event_type=event_type,
                severity=severity,
                strategy_name=self.account_name,
                symbol=None,
                rule_name=event_type,
                details_json={
                    "account_name": self.account_name,
                    "details": details,
                },
                created_ts=datetime.now(timezone.utc),
            )
        )
