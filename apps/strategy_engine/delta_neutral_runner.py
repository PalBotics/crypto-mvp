from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import Settings
from core.models.dn_runner_command import DnRunnerCommand
from core.models.fill_record import FillRecord
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent
from core.paper.funding_accrual import FundingAccrualEngine
from core.paper.hedge_ratio import compute_hedge_ratio
from core.paper.perp_execution import close_perp_short, open_perp_short
from core.paper.pnl_calculator import create_pnl_snapshot_from_fill
from core.paper.position_tracker import update_position_from_fill
from core.strategy.delta_neutral import DeltaNeutralConfig, DeltaNeutralStrategy
from core.utils.logging import get_logger

_log = get_logger(__name__)


class DeltaNeutralRunner:
    """Delta-neutral paper strategy runner for ETH spot/perp pairing."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        settings: Settings,
        account_name: str = "paper_dn",
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._account_name = account_name
        self._strategy = DeltaNeutralStrategy(
            DeltaNeutralConfig(
                entry_threshold_apr=Decimal(str(settings.dn_funding_entry_threshold_apr)),
                exit_threshold_apr=Decimal(str(settings.dn_funding_exit_threshold_apr)),
                force_entry=bool(settings.dn_force_entry),
                block_on_ratio_violation=bool(settings.dn_block_on_ratio_violation),
                run_mode=settings.run_mode,
            )
        )
        self._last_accrual_ts: datetime | None = None
        self._flattened = False

    def close(self) -> None:
        return None

    def run_forever(self, stop_event: threading.Event) -> None:
        interval_seconds = int(self._settings.dn_iteration_seconds)
        account_name = self._account_name
        _log.info(
            "service_starting",
            strategy="delta_neutral",
            account=account_name,
            interval_seconds=interval_seconds,
        )

        try:
            while not stop_event.is_set():
                with self._session_factory() as session:
                    try:
                        self._run_iteration(session=session, account_name=account_name)
                        session.commit()
                    except Exception as exc:
                        session.rollback()
                        _log.error("dn_iteration_failed", error=str(exc))

                stop_event.wait(interval_seconds)
        finally:
            self.close()

    def _run_iteration(self, *, session: Session, account_name: str) -> None:
        command_row = (
            session.execute(
                select(DnRunnerCommand).where(DnRunnerCommand.account_name == account_name)
            )
            .scalars()
            .first()
        )
        if command_row is not None and bool(command_row.flatten_requested):
            reason = command_row.reason or "manual_flatten_api"
            _log.warning(
                "dn_flatten_requested_by_api",
                account_name=account_name,
                reason=reason,
            )
            asyncio.run(self.emergency_flatten(reason=reason))
            command_row.flatten_requested = False
            command_row.requested_at = None
            command_row.reason = None
            return

        latest_tick = self._latest_perp_tick(session)
        if latest_tick is None:
            _log.info("dn_iteration_skipped", reason="missing_mark_price")
            return

        now_utc = datetime.now(timezone.utc)
        data_age_seconds = max(0, int((now_utc - latest_tick.event_ts).total_seconds()))
        if data_age_seconds > 120:
            _log.warning("coinbase_feed_stale", data_age_seconds=data_age_seconds)
            session.add(
                RiskEvent(
                    event_type="stale_feed",
                    severity="warning",
                    strategy_name="delta_neutral",
                    symbol=self._settings.dn_perp_symbol,
                    rule_name="dn_stale_feed_guard",
                    details_json={
                        "account_name": account_name,
                        "details": "coinbase_advanced/ETH-PERP",
                        "data_age_seconds": data_age_seconds,
                    },
                    created_ts=now_utc,
                )
            )
            return

        mark_price = Decimal(str(latest_tick.mid_price))

        if self._flattened:
            self._strategy.set_flattened(True)
            return

        if self._check_daily_loss(session):
            return

        latest_funding = self._latest_funding(session)
        if latest_funding is None:
            _log.info("dn_iteration_skipped", reason="missing_funding")
            return

        funding_rate_apr = self._funding_apr_pct(latest_funding)
        position_state = self._current_position_state(session=session, account_name=account_name)

        if self._strategy.is_paused:
            if not position_state["has_spot"] and not position_state["has_perp"]:
                _log.info("dn_strategy_resumed_flat")
            else:
                _log.warning("dn_strategy_paused", account_name=account_name)

        hedge = compute_hedge_ratio(account_name, session)
        hedge_status = {
            "spot_notional": hedge.spot_notional,
            "perp_notional": hedge.perp_notional,
            "hedge_ratio": hedge.hedge_ratio,
            "spot_qty": hedge.spot_qty,
            "perp_qty": hedge.perp_qty,
            "mark_price": hedge.mark_price,
            "is_balanced": hedge.is_balanced,
        }

        current_position = position_state if (position_state["has_spot"] or position_state["has_perp"]) else None

        signal = self._strategy.evaluate(
            account_name=account_name,
            eth_mark_price=mark_price,
            funding_rate_apr=funding_rate_apr,
            current_position=current_position,
            hedge_status=hedge_status,
            db=session,
        )

        signal_type = (signal.signal_type or "").upper()

        if signal_type == "ENTER":
            self._handle_enter(
                session=session,
                account_name=account_name,
                mark_price=mark_price,
                funding_rate_apr=funding_rate_apr,
            )
        elif signal_type == "EXIT":
            self._handle_exit(session=session, account_name=account_name, mark_price=mark_price)
        elif signal_type == "REBALANCE":
            self._handle_rebalance(session=session, account_name=account_name, mark_price=mark_price, hedge_status=hedge_status)
        elif signal_type == "HOLD":
            self._handle_hold(session=session, account_name=account_name, funding_rate_apr=funding_rate_apr, hedge_status=hedge_status)
        else:
            _log.info("dn_blocked", funding_rate_apr=str(funding_rate_apr))

    def _handle_enter(
        self,
        *,
        session: Session,
        account_name: str,
        mark_price: Decimal,
        funding_rate_apr: Decimal,
    ) -> None:
        contract_qty = int(self._settings.dn_contract_qty)
        quantity = Decimal(contract_qty) * Decimal("0.10")

        perp_ok = False
        spot_ok = False

        try:
            open_perp_short(
                session=session,
                account_name=account_name,
                exchange=self._settings.dn_perp_exchange,
                symbol=self._settings.dn_perp_symbol,
                contract_qty=contract_qty,
                mark_price=mark_price,
                margin_rate=Decimal("0.10"),
            )
            perp_ok = True

            self._simulate_spot_fill(
                session=session,
                account_name=account_name,
                exchange=self._settings.dn_spot_exchange,
                symbol=self._settings.dn_spot_symbol,
                side="buy",
                qty=quantity,
                price=mark_price,
            )
            spot_ok = True
        except Exception as exc:
            _log.error("dn_enter_failed", error=str(exc))

        if not (perp_ok and spot_ok):
            self._record_hedge_imbalance(session=session, account_name=account_name, reason="partial_fill_enter")
            self._strategy.pause()
            _log.warning(
                "partial_fill_detected",
                perp_filled=perp_ok,
                spot_filled=spot_ok,
            )
            return

        _log.info(
            "dn_position_entered",
            contract_qty=contract_qty,
            eth_mark=str(mark_price),
            funding_rate_apr=str(funding_rate_apr),
        )

    def _handle_exit(self, *, session: Session, account_name: str, mark_price: Decimal) -> None:
        perp_realized = close_perp_short(
            session=session,
            account_name=account_name,
            exchange=self._settings.dn_perp_exchange,
            symbol=self._settings.dn_perp_symbol,
            mark_price=mark_price,
        )

        spot_qty = self._latest_spot_qty(session=session, account_name=account_name)
        if spot_qty > 0:
            self._simulate_spot_fill(
                session=session,
                account_name=account_name,
                exchange=self._settings.dn_spot_exchange,
                symbol=self._settings.dn_spot_symbol,
                side="sell",
                qty=spot_qty,
                price=mark_price,
            )

        _log.info(
            "dn_position_exited",
            realized_pnl=str(perp_realized),
            exit_reason="funding_below_exit_threshold",
        )

    def _handle_rebalance(
        self,
        *,
        session: Session,
        account_name: str,
        mark_price: Decimal,
        hedge_status: dict,
    ) -> None:
        spot_notional = Decimal(str(hedge_status.get("spot_notional", 0)))
        perp_notional = Decimal(str(hedge_status.get("perp_notional", 0)))
        old_ratio = Decimal(str(hedge_status.get("hedge_ratio", 0)))

        action = "none"
        if spot_notional > perp_notional:
            open_perp_short(
                session=session,
                account_name=account_name,
                exchange=self._settings.dn_perp_exchange,
                symbol=self._settings.dn_perp_symbol,
                contract_qty=1,
                mark_price=mark_price,
                margin_rate=Decimal("0.10"),
            )
            action = "add_perp_short_1_contract"
        elif perp_notional > spot_notional:
            close_perp_short(
                session=session,
                account_name=account_name,
                exchange=self._settings.dn_perp_exchange,
                symbol=self._settings.dn_perp_symbol,
                mark_price=mark_price,
                contract_qty=1,
            )
            action = "reduce_perp_short_1_contract"

        new_hedge = compute_hedge_ratio(account_name, session)
        _log.info(
            "rebalance_executed",
            old_ratio=str(old_ratio),
            new_ratio=str(new_hedge.hedge_ratio),
            action=action,
        )

    def _handle_hold(
        self,
        *,
        session: Session,
        account_name: str,
        funding_rate_apr: Decimal,
        hedge_status: dict,
    ) -> None:
        now = datetime.now(timezone.utc)
        if self._last_accrual_ts is None or (now - self._last_accrual_ts) >= timedelta(hours=1):
            FundingAccrualEngine.accrue_hourly(account_name=account_name, db=session)
            self._last_accrual_ts = now

        settled = Decimal("0")
        if FundingAccrualEngine.should_settle(now):
            settled = FundingAccrualEngine.settle(account_name=account_name, db=session)

        _log.info(
            "dn_hold",
            hedge_ratio=str(hedge_status.get("hedge_ratio")),
            funding_rate_apr=str(funding_rate_apr),
            accrued_today=str(settled),
        )

    async def emergency_flatten(self, reason: str) -> None:
        spot_qty = Decimal("0")
        perp_qty = Decimal("0")
        perp_closed_successfully = True

        with self._session_factory() as session:
            try:
                mark_price = self._latest_mark_price(session) or Decimal("0")
                perp_qty = self._latest_perp_qty(session=session, account_name=self._account_name)
                spot_qty = self._latest_spot_qty(session=session, account_name=self._account_name)

                if perp_qty > 0:
                    try:
                        close_perp_short(
                            session=session,
                            account_name=self._account_name,
                            exchange=self._settings.dn_perp_exchange,
                            symbol=self._settings.dn_perp_symbol,
                            mark_price=mark_price,
                        )
                    except Exception as exc:
                        perp_closed_successfully = False
                        _log.error("dn_emergency_flatten_perp_failed", reason=reason, error=str(exc))

                if perp_closed_successfully and spot_qty > 0:
                    self._simulate_spot_fill(
                        session=session,
                        account_name=self._account_name,
                        exchange=self._settings.dn_spot_exchange,
                        symbol=self._settings.dn_spot_symbol,
                        side="sell",
                        qty=spot_qty,
                        price=mark_price,
                    )

                session.add(
                    RiskEvent(
                        event_type="emergency_flatten",
                        severity="critical",
                        strategy_name="delta_neutral",
                        symbol=self._settings.dn_perp_symbol,
                        rule_name="dn_emergency_flatten",
                        details_json={
                            "account_name": self._account_name,
                            "reason": reason,
                            "spot_qty": str(spot_qty),
                            "perp_qty": str(perp_qty),
                        },
                        created_ts=datetime.now(timezone.utc),
                    )
                )

                self._flattened = True
                self._strategy.set_flattened(True)

                _log.critical(
                    "dn_emergency_flatten_executed",
                    reason=reason,
                    spot_qty=str(spot_qty),
                    perp_qty=str(perp_qty),
                )
                session.commit()
            except Exception as exc:
                session.rollback()
                self._flattened = True
                self._strategy.set_flattened(True)
                _log.error("dn_emergency_flatten_failed", reason=reason, error=str(exc))

    def _check_daily_loss(self, db: Session) -> bool:
        now_utc = datetime.now(timezone.utc)
        day_start = datetime(
            year=now_utc.year,
            month=now_utc.month,
            day=now_utc.day,
            tzinfo=timezone.utc,
        )

        realized_today = Decimal(
            str(
                db.execute(
                    select(func.coalesce(func.sum(PnLSnapshot.realized_pnl), 0))
                    .where(PnLSnapshot.strategy_name == self._account_name)
                    .where(PnLSnapshot.snapshot_ts >= day_start)
                ).scalar_one()
            )
        )

        mark_price = self._latest_mark_price(db)
        unrealized = Decimal("0")
        if mark_price is not None:
            positions = (
                db.execute(
                    select(PositionSnapshot)
                    .where(PositionSnapshot.account_name == self._account_name)
                    .where(PositionSnapshot.quantity > 0)
                    .order_by(PositionSnapshot.snapshot_ts.desc())
                )
                .scalars()
                .all()
            )

            for pos in positions:
                qty = Decimal(str(pos.quantity or 0))
                entry_price = Decimal(str(pos.avg_entry_price or 0))
                side = (pos.side or "").strip().lower()

                if (
                    pos.exchange == self._settings.dn_spot_exchange
                    and pos.symbol == self._settings.dn_spot_symbol
                    and side in {"long", "buy"}
                ):
                    unrealized += (mark_price - entry_price) * qty
                elif (
                    pos.exchange == self._settings.dn_perp_exchange
                    and pos.symbol == self._settings.dn_perp_symbol
                    and side in {"short", "sell"}
                ):
                    unrealized += (entry_price - mark_price) * qty

        combined_pnl = realized_today + unrealized
        max_daily_loss = Decimal(str(self._settings.dn_max_daily_loss_usd))
        if combined_pnl < (Decimal("-1") * max_daily_loss):
            _log.error(
                "dn_max_daily_loss_breached",
                loss_usd=str(abs(combined_pnl)),
                max_daily_loss_usd=str(max_daily_loss),
            )
            asyncio.run(self.emergency_flatten(reason="max_daily_loss_breached"))
            return True

        return False

    def _latest_perp_tick(self, session: Session) -> MarketTick | None:
        return (
            session.execute(
                select(MarketTick)
                .where(MarketTick.exchange == self._settings.dn_perp_exchange)
                .where(MarketTick.symbol == self._settings.dn_perp_symbol)
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )

    def _latest_mark_price(self, session: Session) -> Decimal | None:
        tick = self._latest_perp_tick(session)
        if tick is None:
            return None
        return Decimal(str(tick.mid_price))

    def _latest_funding(self, session: Session) -> FundingRateSnapshot | None:
        return (
            session.execute(
                select(FundingRateSnapshot)
                .where(FundingRateSnapshot.exchange == self._settings.dn_perp_exchange)
                .where(FundingRateSnapshot.symbol == self._settings.dn_perp_symbol)
                .order_by(FundingRateSnapshot.event_ts.desc())
            )
            .scalars()
            .first()
        )

    def _funding_apr_pct(self, funding: FundingRateSnapshot) -> Decimal:
        rate = Decimal(str(funding.funding_rate))
        interval_hours = int(funding.funding_interval_hours or 1)
        periods_per_year = Decimal(str((24 / interval_hours) * 365))
        return rate * periods_per_year * Decimal("100")

    def _current_position_state(self, *, session: Session, account_name: str) -> dict:
        latest_rows = (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .all()
        )

        has_spot = any(
            r.exchange == self._settings.dn_spot_exchange
            and r.symbol == self._settings.dn_spot_symbol
            and Decimal(str(r.quantity)) > 0
            for r in latest_rows
        )
        has_perp = any(
            r.exchange == self._settings.dn_perp_exchange
            and r.symbol == self._settings.dn_perp_symbol
            and (r.position_type or "") == "perp"
            and Decimal(str(r.quantity)) > 0
            for r in latest_rows
        )

        return {
            "has_spot": has_spot,
            "has_perp": has_perp,
        }

    def _simulate_spot_fill(
        self,
        *,
        session: Session,
        account_name: str,
        exchange: str,
        symbol: str,
        side: str,
        qty: Decimal,
        price: Decimal,
    ) -> None:
        now = datetime.now(timezone.utc)
        fill = FillRecord(
            order_record_id=None,
            exchange=exchange,
            symbol=symbol,
            exchange_trade_id=None,
            side=side,
            fill_price=price,
            fill_qty=qty,
            fill_notional=qty * price,
            liquidity_role="paper_fill",
            fee_paid=Decimal("0"),
            fee_asset=None,
            fill_ts=now,
            ingested_ts=now,
        )
        session.add(fill)
        session.flush()

        pos = update_position_from_fill(session=session, fill_record=fill, mode=account_name)
        # Position snapshots store directional exposure as long/short, while
        # fill records store execution direction as buy/sell.
        side_normalized = side.strip().lower()
        if side_normalized == "buy":
            pos.side = "long"
        elif side_normalized == "sell":
            pos.side = "short"
        create_pnl_snapshot_from_fill(
            session=session,
            fill_record=fill,
            position_snapshot=pos,
            mark_price=price,
        )

    def _latest_spot_qty(self, *, session: Session, account_name: str) -> Decimal:
        row = (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .where(PositionSnapshot.exchange == self._settings.dn_spot_exchange)
                .where(PositionSnapshot.symbol == self._settings.dn_spot_symbol)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if row is None:
            return Decimal("0")
        return Decimal(str(row.quantity or 0))

    def _latest_perp_qty(self, *, session: Session, account_name: str) -> Decimal:
        row = (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name == account_name)
                .where(PositionSnapshot.exchange == self._settings.dn_perp_exchange)
                .where(PositionSnapshot.symbol == self._settings.dn_perp_symbol)
                .where(PositionSnapshot.position_type == "perp")
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if row is None:
            return Decimal("0")
        return Decimal(str(row.quantity or 0))

    def _record_hedge_imbalance(self, *, session: Session, account_name: str, reason: str) -> None:
        session.add(
            RiskEvent(
                event_type="hedge_imbalance",
                severity="high",
                strategy_name="delta_neutral",
                symbol=self._settings.dn_perp_symbol,
                rule_name="paired_leg_consistency",
                details_json={
                    "account_name": account_name,
                    "reason": reason,
                },
                created_ts=datetime.now(timezone.utc),
            )
        )
