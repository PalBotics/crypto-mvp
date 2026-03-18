from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.position_snapshot import PositionSnapshot
from core.models.strategy_signal import StrategySignal
from core.utils.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class DeltaNeutralConfig:
    entry_threshold_apr: Decimal = Decimal("5.0")
    exit_threshold_apr: Decimal = Decimal("2.0")
    force_entry: bool = False
    run_mode: str = "paper"


class DeltaNeutralStrategy:
    """Decision engine for paper delta-neutral ETH strategy."""

    def __init__(self, config: DeltaNeutralConfig) -> None:
        self._config = config
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def evaluate(
        self,
        account_name: str,
        eth_mark_price: Decimal,
        funding_rate_apr: Decimal,
        current_position: dict | None,
        hedge_status: dict,
        db: Session,
    ) -> StrategySignal:
        if self._paused:
            if self._is_flat(account_name=account_name, db=db):
                self._paused = False
                _log.info("dn_strategy_resumed", account_name=account_name)
            else:
                _log.warning("dn_strategy_paused", account_name=account_name)
                return self._persist_signal(
                    signal_type="BLOCKED",
                    account_name=account_name,
                    funding_rate_apr=funding_rate_apr,
                    mark_price=eth_mark_price,
                    reason_code="paused",
                    db=db,
                )

        in_position = bool(current_position)

        if not in_position:
            if self._config.force_entry and self._config.run_mode == "paper":
                _log.warning(
                    "force_entry_override_active",
                    account_name=account_name,
                    funding_rate_apr=str(funding_rate_apr),
                )
                return self._persist_signal(
                    signal_type="ENTER",
                    account_name=account_name,
                    funding_rate_apr=funding_rate_apr,
                    mark_price=eth_mark_price,
                    reason_code="force_entry_override",
                    db=db,
                )

            if funding_rate_apr >= self._config.entry_threshold_apr:
                return self._persist_signal(
                    signal_type="ENTER",
                    account_name=account_name,
                    funding_rate_apr=funding_rate_apr,
                    mark_price=eth_mark_price,
                    reason_code="entry_threshold_met",
                    db=db,
                )

            _log.info(
                "entry_blocked_funding_below_threshold",
                account_name=account_name,
                funding_rate_apr=str(funding_rate_apr),
                entry_threshold_apr=str(self._config.entry_threshold_apr),
            )
            return self._persist_signal(
                signal_type="BLOCKED",
                account_name=account_name,
                funding_rate_apr=funding_rate_apr,
                mark_price=eth_mark_price,
                reason_code="funding_below_entry_threshold",
                db=db,
            )

        if funding_rate_apr < self._config.exit_threshold_apr:
            _log.info(
                "exit_triggered_low_funding",
                account_name=account_name,
                funding_rate_apr=str(funding_rate_apr),
                exit_threshold_apr=str(self._config.exit_threshold_apr),
            )
            return self._persist_signal(
                signal_type="EXIT",
                account_name=account_name,
                funding_rate_apr=funding_rate_apr,
                mark_price=eth_mark_price,
                reason_code="funding_below_exit_threshold",
                db=db,
            )

        if not bool(hedge_status.get("is_balanced", False)):
            return self._persist_signal(
                signal_type="REBALANCE",
                account_name=account_name,
                funding_rate_apr=funding_rate_apr,
                mark_price=eth_mark_price,
                reason_code="hedge_ratio_drift",
                db=db,
            )

        return self._persist_signal(
            signal_type="HOLD",
            account_name=account_name,
            funding_rate_apr=funding_rate_apr,
            mark_price=eth_mark_price,
            reason_code="hold_balanced",
            db=db,
        )

    def _is_flat(self, account_name: str, db: Session) -> bool:
        rows = (
            db.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .all()
        )
        if not rows:
            return True

        spot_open = any(
            r.exchange == "kraken"
            and r.symbol == "ETHUSD"
            and Decimal(str(r.quantity)) > 0
            for r in rows
        )
        perp_open = any(
            r.exchange == "coinbase_advanced"
            and r.symbol == "ETH-PERP"
            and Decimal(str(r.quantity)) > 0
            and (r.position_type or "") == "perp"
            for r in rows
        )
        return not spot_open and not perp_open

    def _persist_signal(
        self,
        *,
        signal_type: str,
        account_name: str,
        funding_rate_apr: Decimal,
        mark_price: Decimal,
        reason_code: str,
        db: Session,
    ) -> StrategySignal:
        signal = StrategySignal(
            strategy_name="delta_neutral",
            strategy_version="1.0",
            symbol="ETH-PERP",
            signal_type=signal_type,
            signal_strength=funding_rate_apr,
            decision_json={
                "account_name": account_name,
                "funding_rate_apr": str(funding_rate_apr),
                "mark_price": str(mark_price),
            },
            reason_code=reason_code,
            created_ts=datetime.now(timezone.utc),
        )
        db.add(signal)
        return signal
