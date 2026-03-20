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
from core.models.system_control import SystemControl
from core.utils.logging import get_logger

_log = get_logger(__name__)

_DEFAULT_SYSTEM_CONTROLS: dict[str, str] = {
    "kill_switch_active": "false",
    "mm_enabled": "true",
    "dn_enabled": "true",
}


def ensure_system_controls_defaults(db: Session) -> None:
    now_utc = datetime.now(timezone.utc)
    for key, default_value in _DEFAULT_SYSTEM_CONTROLS.items():
        row = (
            db.execute(
                select(SystemControl).where(SystemControl.key == key)
            )
            .scalars()
            .first()
        )
        if row is None:
            db.add(
                SystemControl(
                    key=key,
                    value=default_value,
                    updated_at=now_utc,
                    reason="auto_seed_default",
                )
            )
    db.flush()


def _read_control_value(db: Session, key: str) -> str | None:
    try:
        ensure_system_controls_defaults(db)
        row = (
            db.execute(
                select(SystemControl).where(SystemControl.key == key)
            )
            .scalars()
            .first()
        )
        return row.value if row is not None else None
    except Exception:
        return None


def is_kill_switch_active(db: Session) -> bool:
    value = _read_control_value(db, "kill_switch_active")
    if value is None:
        return False
    return str(value).strip().lower() == "true"


def is_strategy_enabled(db: Session, strategy: str) -> bool:
    key = f"{strategy}_enabled"
    value = _read_control_value(db, key)
    if value is None:
        return True
    return str(value).strip().lower() == "true"


@dataclass(frozen=True)
class RiskCheckResult:
    passed: bool
    reason: str | None = None


@dataclass
class CircuitBreaker:
    exchange: str
    failure_count: int = 0
    state: str = "closed"
    opened_at: datetime | None = None
    last_canary_at: datetime | None = None


class RiskEngine:
    _breakers: dict[str, CircuitBreaker] = {}

    def __init__(self, account_name: str, db: Session) -> None:
        self.account_name = account_name
        self.db = db
        settings = get_settings()
        self.risk_max_notional_usd = Decimal(str(settings.risk_max_notional_usd))
        self.risk_max_symbol_notional_usd = Decimal(str(settings.risk_max_symbol_notional_usd))
        self.risk_max_consecutive_failures = int(settings.risk_max_consecutive_failures)

    def _get_or_create_breaker(self, exchange: str) -> CircuitBreaker:
        breaker = self._breakers.get(exchange)
        if breaker is None:
            breaker = CircuitBreaker(exchange=exchange)
            self._breakers[exchange] = breaker
        return breaker

    def record_exchange_success(self, exchange: str) -> None:
        breaker = self._get_or_create_breaker(exchange)
        was_state = breaker.state
        breaker.failure_count = 0
        breaker.opened_at = None
        breaker.last_canary_at = None
        breaker.state = "closed"

        if was_state in {"open", "half_open"}:
            _log.info("exchange_circuit_breaker_closed", exchange=exchange)
            self._fire_risk_event(
                event_type="circuit_breaker_closed",
                severity="info",
                details=f"{exchange} recovered",
            )

    def record_exchange_failure(self, exchange: str) -> None:
        breaker = self._get_or_create_breaker(exchange)
        breaker.failure_count += 1

        if (
            breaker.failure_count >= self.risk_max_consecutive_failures
            and breaker.state in {"closed", "half_open"}
        ):
            now_utc = datetime.now(timezone.utc)
            breaker.state = "open"
            breaker.opened_at = now_utc
            breaker.last_canary_at = None
            _log.warning(
                "exchange_circuit_breaker_opened",
                exchange=exchange,
                failure_count=breaker.failure_count,
            )
            self._fire_risk_event(
                event_type="circuit_breaker_opened",
                severity="warning",
                details=f"{exchange} {breaker.failure_count} consecutive failures",
            )

    def is_exchange_available(self, exchange: str) -> bool:
        breaker = self._breakers.get(exchange)
        if breaker is None:
            return True

        if breaker.state == "closed":
            return True

        now_utc = datetime.now(timezone.utc)
        if breaker.state == "open":
            last_attempt_ts = breaker.last_canary_at or breaker.opened_at
            if last_attempt_ts is None:
                return False
            elapsed_seconds = (now_utc - last_attempt_ts).total_seconds()
            if elapsed_seconds >= 60:
                breaker.state = "half_open"
                breaker.last_canary_at = now_utc
                return True
            return False

        if breaker.state == "half_open":
            return False

        return False

    def get_breaker_states(self, exchanges: list[str] | None = None) -> list[dict[str, object]]:
        targets = exchanges or sorted(self._breakers.keys())
        states: list[dict[str, object]] = []
        for exchange in targets:
            breaker = self._breakers.get(exchange)
            if breaker is None:
                states.append(
                    {
                        "exchange": exchange,
                        "state": "closed",
                        "failure_count": 0,
                    }
                )
                continue
            states.append(
                {
                    "exchange": exchange,
                    "state": breaker.state,
                    "failure_count": breaker.failure_count,
                }
            )
        return states

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


def notify_exchange_success(risk_engine: RiskEngine, exchange: str) -> None:
    risk_engine.record_exchange_success(exchange)


def notify_exchange_failure(risk_engine: RiskEngine, exchange: str) -> None:
    risk_engine.record_exchange_failure(exchange)
