from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import signal
import time

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.alerting.evaluator import AlertEvaluator
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.order_intent import OrderIntent
from core.models.quote_snapshot import QuoteSnapshot
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FeeModel
from core.paper.funding_accrual import accrue_funding_payment
from core.risk.engine import RiskEngine
from core.reporting.account import compute_paper_account_snapshot
from core.strategy.funding_capture import FundingCaptureStrategy
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy
from core.utils.logging import get_logger

_log = get_logger(__name__)
TWAP_OVERRIDE_PATH = Path(__file__).resolve().parents[2] / "data" / "twap_lookback_override.json"
ALLOWED_TWAP_HOURS = {1, 2, 4, 8, 24}
DEFAULT_SG_WINDOW = 25
DEFAULT_SG_DEGREE = 2


def _optional_decimal_env(name: str) -> Decimal | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


@dataclass(frozen=True)
class IterationSummary:
    """Result snapshot for a single loop iteration."""

    iteration: int
    funding_rate: Decimal
    mark_price: Decimal
    signal_result: str
    intents_executed: int
    funding_payment_amount: Decimal | None


StrategyType = FundingCaptureStrategy | MarketMakingStrategy


class PaperTradingLoop:
    """Orchestrates one full funding-capture paper-trading cycle per iteration.

    Each iteration:
        1. Evaluates the strategy signal
        2. Flushes pending objects so execution queries can find them
        3. Drains all pending OrderIntents created this cycle
        4. Accrues funding payment for any open perp position
        5. Commits all iteration-side effects atomically and returns an IterationSummary

    Accepts a pre-built Session for testability; does not manage the session
    lifecycle — the caller is responsible for closing it.

    execute_one_paper_market_intent does not commit; transaction ownership
    remains with this loop, which commits once per successful iteration.
    """

    def __init__(
        self,
        session: Session,
        strategy: StrategyType,
        risk_engine: RiskEngine,
        fee_model: FeeModel,
        iterations: int,
        market_data: list[tuple[Decimal, Decimal]] | None = None,
        alert_evaluator: AlertEvaluator | None = None,
        strategy_mode: str = "funding_capture",
        market_making_config: MarketMakingConfig | None = None,
    ) -> None:
        self._session = session
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._fee_model = fee_model
        self._iterations = iterations
        self._market_data: list[tuple[Decimal, Decimal]] = market_data or []
        self._alert_evaluator = alert_evaluator
        self._strategy_mode = strategy_mode
        self._market_making_config = market_making_config

    def run(self) -> list[IterationSummary]:
        """Run all iterations and return one IterationSummary per iteration."""
        summaries: list[IterationSummary] = []
        for i in range(self._iterations):
            if i < len(self._market_data):
                funding_rate, mark_price = self._market_data[i]
            elif self._market_data:
                funding_rate, mark_price = self._market_data[-1]
            else:
                funding_rate, mark_price = Decimal("0"), Decimal("0")

            summary = self._run_iteration(i + 1, funding_rate, mark_price)
            summaries.append(summary)

        return summaries

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _run_iteration(
        self, n: int, funding_rate: Decimal, mark_price: Decimal
    ) -> IterationSummary:
        _log.info(
            "iteration_start",
            iteration=n,
            funding_rate=str(funding_rate),
            mark_price=str(mark_price),
        )
        try:
            if self._strategy_mode == "market_making":
                signal_result, intents_executed, payment = self.run_one_iteration_market_making(
                    n=n,
                    funding_rate=funding_rate,
                    mark_price=mark_price,
                )
            else:
                signal_result, intents_executed, payment = self._run_iteration_funding_capture(
                    n=n,
                    funding_rate=funding_rate,
                    mark_price=mark_price,
                )

            # 5. Evaluate alerts (if configured) before committing.
            if self._alert_evaluator is not None:
                alert_results = self._alert_evaluator.evaluate(self._session)
                for result in alert_results:
                    _log.warning(
                        "alert_result",
                        iteration=n,
                        alert_type=result.alert_type,
                        severity=result.severity,
                        message=result.message,
                    )

            # 6. Commit all iteration changes atomically.
            self._session.commit()

            summary = IterationSummary(
                iteration=n,
                funding_rate=funding_rate,
                mark_price=mark_price,
                signal_result=signal_result,
                intents_executed=intents_executed,
                funding_payment_amount=(
                    payment.payment_amount if payment is not None else None
                ),
            )
            _log.info(
                "iteration_complete",
                iteration=n,
                signal=signal_result,
                intents_executed=intents_executed,
                funding_payment=str(summary.funding_payment_amount),
            )
            return summary

        except Exception as exc:
            self._session.rollback()
            _log.error("iteration_failed", iteration=n, error=str(exc))
            return IterationSummary(
                iteration=n,
                funding_rate=funding_rate,
                mark_price=mark_price,
                signal_result="error",
                intents_executed=0,
                funding_payment_amount=None,
            )

    def _run_iteration_funding_capture(
        self,
        n: int,
        funding_rate: Decimal,
        mark_price: Decimal,
    ) -> tuple[str, int, object | None]:
        strategy = self._strategy
        if not isinstance(strategy, FundingCaptureStrategy):
            raise TypeError("Funding capture mode requires FundingCaptureStrategy")

        signal_result = strategy.evaluate(self._session, funding_rate, mark_price)
        _log.info("signal_evaluated", iteration=n, signal=signal_result)

        self._session.flush()

        intents_executed = 0
        if signal_result in ("entered", "exited"):
            now = datetime.now(timezone.utc)
            while execute_one_paper_market_intent(
                session=self._session,
                fee_model=self._fee_model,
                risk_engine=self._risk_engine,
                funding_rate=funding_rate,
                latest_funding_ts=now,
                mode=strategy.config.mode,
            ):
                intents_executed += 1
                _log.info("intent_executed", iteration=n, count=intents_executed)

            if intents_executed == 0:
                _log.info("all_intents_skipped", iteration=n, signal=signal_result)

        payment = accrue_funding_payment(
            session=self._session,
            symbol=strategy.config.perp_symbol,
            exchange=strategy.config.exchange,
            account_name=strategy.config.mode,
            mark_price=mark_price,
            funding_rate=funding_rate,
        )
        if payment is not None:
            _log.info(
                "funding_accrued",
                iteration=n,
                payment_amount=str(payment.payment_amount),
            )
        else:
            _log.info("funding_skipped", iteration=n, reason="no_open_position")

        return signal_result, intents_executed, payment

    def run_one_iteration_market_making(
        self,
        n: int,
        funding_rate: Decimal,
        mark_price: Decimal,
    ) -> tuple[str, int, None]:
        strategy = self._strategy
        if not isinstance(strategy, MarketMakingStrategy):
            raise TypeError("Market making mode requires MarketMakingStrategy")
        if self._market_making_config is None:
            raise ValueError("market_making_config is required for market_making mode")

        self._apply_twap_lookback_override(strategy)

        snapshot = (
            self._session.execute(
                select(OrderBookSnapshot)
                .where(OrderBookSnapshot.exchange == strategy.config.exchange)
                .where(OrderBookSnapshot.symbol == strategy.config.symbol)
                .order_by(OrderBookSnapshot.event_ts.desc())
            )
            .scalars()
            .first()
        )
        if snapshot is None:
            _log.info("market_making_no_order_book", iteration=n)
            return "no_action", 0, None

        now = datetime.now(timezone.utc)
        pending_stmt = (
            select(OrderIntent)
            .where(OrderIntent.mode == self._market_making_config.account_name)
            .where(OrderIntent.exchange == strategy.config.exchange)
            .where(OrderIntent.symbol == strategy.config.symbol)
            .where(OrderIntent.status == "pending")
            .order_by(OrderIntent.created_ts.asc())
        )

        # 1) Re-check all existing pending intents against the current snapshot.
        pending_intents = self._session.execute(pending_stmt).scalars().all()
        intents_executed = 0
        post_fill_requotes = 0
        for intent in pending_intents:
            if execute_one_paper_market_intent(
                session=self._session,
                fee_model=self._fee_model,
                risk_engine=None,
                funding_rate=funding_rate,
                latest_funding_ts=now,
                mode=self._market_making_config.account_name,
                order_book_snapshot=snapshot,
                explicit_intent=intent,
            ):
                intents_executed += 1

                pending_counts, generated_sides = self._reconcile_market_making_quotes(
                    strategy=strategy,
                    snapshot=snapshot,
                    current_ts=now,
                    pending_stmt=pending_stmt,
                )
                if generated_sides:
                    post_fill_requotes += 1
                    quote_ctx = strategy.last_quote_context
                    _log.info(
                        "post_fill_requote",
                        bid_price=(str(quote_ctx.bid_quote) if quote_ctx is not None else None),
                        ask_price=(str(quote_ctx.ask_quote) if quote_ctx is not None else None),
                        intents_generated=len(generated_sides),
                        pending_buys=pending_counts["buy"],
                        pending_sells=pending_counts["sell"],
                    )

        pending_counts, generated_sides = self._reconcile_market_making_quotes(
            strategy=strategy,
            snapshot=snapshot,
            current_ts=now,
            pending_stmt=pending_stmt,
        )

        signal_result = self._signal_result_for_market_making(generated_sides)
        _log.info(
            "signal_evaluated",
            iteration=n,
            signal=signal_result,
            intents_generated=len(generated_sides),
            intents_executed=intents_executed,
            post_fill_requotes=post_fill_requotes,
            pending_buys=pending_counts["buy"],
            pending_sells=pending_counts["sell"],
        )
        return signal_result, intents_executed, None

    def _generate_and_persist_quotes(
        self,
        strategy: MarketMakingStrategy,
        snapshot: OrderBookSnapshot,
        current_ts: datetime,
        allowed_sides: set[str] | None = None,
    ) -> set[str]:
        if self._market_making_config is None:
            return set()

        current_position = self._current_position(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
            account_name=self._market_making_config.account_name,
        )
        avg_entry_price = self._latest_avg_entry_price(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
            account_name=self._market_making_config.account_name,
        )
        concavity = self._latest_concavity_snapshot(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
        )
        twap_slope_bps_per_min = self._compute_twap_slope(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
        )
        twap = self._latest_twap_snapshot(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
        )
        account_snapshot = compute_paper_account_snapshot(
            session=self._session,
            account_name=self._market_making_config.account_name,
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
        )
        account_value_for_limits = account_snapshot.account_value
        if snapshot.mid_price is not None:
            account_value_for_limits = (
                account_snapshot.cash_value
                + (current_position * Decimal(str(snapshot.mid_price)))
            )
        intents = strategy.evaluate(
            self._session,
            snapshot,
            current_position,
            current_ts,
            twap=twap,
            account_value=account_value_for_limits,
            avg_entry_price=avg_entry_price,
            allowed_sides=allowed_sides,
            twap_slope_bps_per_min=twap_slope_bps_per_min,
            concavity=concavity,
        )

        # Query for any already-resting pending intents BEFORE adding new ones to the
        # session.  SQLAlchemy autoflush means that once we call session.add() the new
        # intents (status="pending") would pollute a subsequent DB query.  We want to
        # capture only intents that were already sitting in the market from a prior cycle
        # so that the QuoteSnapshot reflects the actual resting order prices.
        quote_ctx = strategy.last_quote_context
        existing_pending: dict[str, OrderIntent] = {}
        if quote_ctx is not None:
            for _side in ("buy", "sell"):
                _existing = self._session.execute(
                    select(OrderIntent)
                    .where(OrderIntent.mode == self._market_making_config.account_name)
                    .where(OrderIntent.exchange == strategy.config.exchange)
                    .where(OrderIntent.symbol == strategy.config.symbol)
                    .where(OrderIntent.status == "pending")
                    .where(OrderIntent.side == _side)
                    .order_by(OrderIntent.created_ts.asc())
                    .limit(1)
                ).scalars().first()
                if _existing is not None:
                    existing_pending[_side] = _existing

        for intent in intents:
            intent.mode = self._market_making_config.account_name
            self._session.add(intent)

        if quote_ctx is not None:
            bid_intent = next((intent for intent in intents if intent.side == "buy"), None)
            ask_intent = next((intent for intent in intents if intent.side == "sell"), None)

            # Prefer the price of any already-resting pending intent over the newly
            # generated hypothetical price.  This keeps the Ask line on the chart
            # pinned to the real sell order (e.g. cost-basis priced) rather than
            # drifting with each cycle's TWAP computation.
            bid_quote = (
                existing_pending["buy"].limit_price
                if "buy" in existing_pending
                else (bid_intent.limit_price if bid_intent is not None else None)
            )
            ask_quote = (
                existing_pending["sell"].limit_price
                if "sell" in existing_pending
                else (ask_intent.limit_price if ask_intent is not None else None)
            )

            quote_snapshot = QuoteSnapshot(
                exchange=self._market_making_config.exchange,
                symbol=self._market_making_config.symbol,
                account_name=self._market_making_config.account_name,
                snapshot_ts=current_ts,
                twap=quote_ctx.twap,
                mid_price=quote_ctx.current_mid,
                bid_quote=bid_quote,
                ask_quote=ask_quote,
                twap_lookback_hours=self._market_making_config.twap_lookback_hours,
                spread_bps=self._market_making_config.spread_bps,
            )
            self._session.add(quote_snapshot)

        self._session.flush()
        return {intent.side for intent in intents}

    def _reconcile_market_making_quotes(
        self,
        strategy: MarketMakingStrategy,
        snapshot: OrderBookSnapshot,
        current_ts: datetime,
        pending_stmt,
    ) -> tuple[dict[str, int], set[str]]:
        pending_after_check = self._session.execute(pending_stmt).scalars().all()
        self._cancel_stale_market_making_intents(pending_after_check, current_ts)
        self._session.flush()

        pending_ready = self._session.execute(pending_stmt).scalars().all()
        pending_counts = self._pending_counts_by_side(pending_ready)
        allowed_sides = {
            side for side, count in pending_counts.items()
            if count == 0
        }
        if not allowed_sides:
            return pending_counts, set()

        generated_sides = self._generate_and_persist_quotes(
            strategy=strategy,
            snapshot=snapshot,
            current_ts=current_ts,
            allowed_sides=allowed_sides,
        )
        return pending_counts, generated_sides

    def _cancel_stale_market_making_intents(
        self,
        pending_intents: list[OrderIntent],
        current_ts: datetime,
    ) -> None:
        if self._market_making_config is None:
            return

        stale_cutoff = current_ts - timedelta(seconds=self._market_making_config.stale_book_seconds)
        for intent in pending_intents:
            if intent.created_ts < stale_cutoff:
                age_seconds = (current_ts - intent.created_ts).total_seconds()
                intent.status = "cancelled"
                _log.info(
                    "intent_cancelled_stale",
                    intent_id=str(intent.id),
                    side=intent.side,
                    limit_price=(
                        str(intent.limit_price) if intent.limit_price is not None else None
                    ),
                    age_seconds=age_seconds,
                )

    @staticmethod
    def _pending_counts_by_side(pending_intents: list[OrderIntent]) -> dict[str, int]:
        counts = {"buy": 0, "sell": 0}
        for intent in pending_intents:
            side = (intent.side or "").strip().lower()
            if side in counts:
                counts[side] += 1
        return counts

    @staticmethod
    def _signal_result_for_market_making(generated_sides: set[str]) -> str:
        normalized_sides = {side.strip().lower() for side in generated_sides}
        if normalized_sides == {"buy", "sell"}:
            return "quoted_both"
        if normalized_sides == {"buy"}:
            return "quoted_buy"
        if normalized_sides == {"sell"}:
            return "quoted_sell"
        return "no_action"

    def _apply_twap_lookback_override(self, strategy: MarketMakingStrategy) -> None:
        if not TWAP_OVERRIDE_PATH.exists() or self._market_making_config is None:
            return

        try:
            payload = json.loads(TWAP_OVERRIDE_PATH.read_text(encoding="utf-8"))
            new_hours = int(payload.get("hours"))
        except (ValueError, TypeError, json.JSONDecodeError):
            return

        if new_hours not in ALLOWED_TWAP_HOURS:
            return

        old_hours = self._market_making_config.twap_lookback_hours
        if new_hours == old_hours:
            return

        self._market_making_config = replace(self._market_making_config, twap_lookback_hours=new_hours)
        strategy.config = self._market_making_config
        _log.info(
            "twap_lookback_override_applied",
            old_hours=old_hours,
            new_hours=new_hours,
        )

    def _current_position(self, exchange: str, symbol: str, account_name: str) -> Decimal:
        latest = (
            self._session.execute(
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

    def _latest_avg_entry_price(
        self,
        exchange: str,
        symbol: str,
        account_name: str,
    ) -> Decimal | None:
        latest = (
            self._session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.exchange == exchange)
                .where(PositionSnapshot.symbol == symbol)
                .where(PositionSnapshot.account_name == account_name)
                .order_by(PositionSnapshot.snapshot_ts.desc())
            )
            .scalars()
            .first()
        )
        if latest is None or latest.avg_entry_price is None:
            return None
        return Decimal(str(latest.avg_entry_price))

    def _latest_concavity_snapshot(
        self,
        exchange: str,
        symbol: str,
    ) -> float | None:
        try:
            import numpy as np
            from scipy.signal import savgol_filter
        except Exception:
            return None

        lookback_hours = max(2, int(self._market_making_config.twap_lookback_hours if self._market_making_config is not None else 2))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        snapshots = (
            self._session.execute(
                select(OrderBookSnapshot)
                .where(OrderBookSnapshot.exchange == exchange)
                .where(OrderBookSnapshot.symbol == symbol)
                .where(OrderBookSnapshot.event_ts > cutoff)
                .where(OrderBookSnapshot.mid_price.is_not(None))
                .order_by(OrderBookSnapshot.event_ts.asc())
            )
            .scalars()
            .all()
        )

        mids = np.array([float(s.mid_price) for s in snapshots], dtype=float)
        if mids.size < 3:
            return None

        window = min(DEFAULT_SG_WINDOW, int(mids.size))
        if window % 2 == 0:
            window -= 1
        degree = min(DEFAULT_SG_DEGREE, window - 1)
        if window < 3 or degree < 1 or degree >= window:
            return None

        concavity_values = savgol_filter(mids, window_length=window, polyorder=degree, deriv=2)
        return float(concavity_values[-1])

    def _compute_twap_slope(
        self,
        exchange: str,
        symbol: str,
    ) -> float | None:
        snapshots = (
            self._session.execute(
                select(OrderBookSnapshot)
                .where(OrderBookSnapshot.exchange == exchange)
                .where(OrderBookSnapshot.symbol == symbol)
                .where(OrderBookSnapshot.mid_price.is_not(None))
                .order_by(OrderBookSnapshot.event_ts.desc())
                .limit(10)
            )
            .scalars()
            .all()
        )
        if len(snapshots) < 2:
            return None

        newest = snapshots[0]
        oldest = snapshots[-1]
        newest_mid = Decimal(str(newest.mid_price))
        oldest_mid = Decimal(str(oldest.mid_price))
        if oldest_mid == Decimal("0"):
            return None

        elapsed_minutes = (newest.event_ts - oldest.event_ts).total_seconds() / 60.0
        if elapsed_minutes <= 0:
            return None

        slope_bps_per_min = ((newest_mid - oldest_mid) / oldest_mid) * Decimal("10000")
        return float(slope_bps_per_min / Decimal(str(elapsed_minutes)))

    def _latest_twap_snapshot(
        self,
        exchange: str,
        symbol: str,
    ) -> Decimal | None:
        lookback_hours = max(2, int(self._market_making_config.twap_lookback_hours if self._market_making_config is not None else 2))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        snapshots = (
            self._session.execute(
                select(OrderBookSnapshot)
                .where(OrderBookSnapshot.exchange == exchange)
                .where(OrderBookSnapshot.symbol == symbol)
                .where(OrderBookSnapshot.event_ts > cutoff)
                .where(OrderBookSnapshot.mid_price.is_not(None))
                .order_by(OrderBookSnapshot.event_ts.asc())
            )
            .scalars()
            .all()
        )

        mids = [Decimal(str(s.mid_price)) for s in snapshots if s.mid_price is not None]
        if len(mids) < 2:
            return None

        return sum(mids, Decimal("0")) / Decimal(len(mids))


def main() -> None:
    """CLI entry point for the paper trading loop."""
    from core.app import bootstrap_app
    from core.db.session import get_db_session
    from core.paper.fees import FixedBpsFeeModel
    from core.risk.engine import RiskConfig
    from core.strategy.funding_capture import FundingCaptureConfig
    from core.strategy.market_making import MarketMakingConfig

    load_dotenv()

    ctx = bootstrap_app(service_name="paper_trader", check_db=True)
    session = get_db_session()
    paper_strategy = os.environ.get("PAPER_STRATEGY", "funding_capture").strip().lower()

    risk_config = RiskConfig(
        max_data_age_seconds=3600,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("1000000"),
    )

    _stale = os.environ.get("MM_STALE_BOOK_SECONDS")
    stale_book_seconds = int(_stale) if _stale is not None else None
    _spread = os.environ.get("MM_SPREAD_BPS")
    spread_bps = Decimal(_spread) if _spread is not None else None
    _quote = os.environ.get("MM_QUOTE_SIZE")
    quote_size = Decimal(_quote) if _quote is not None else None
    quote_size_pct = _optional_decimal_env("MM_QUOTE_SIZE_PCT")
    _inventory = os.environ.get("MM_MAX_INVENTORY")
    max_inventory = Decimal(_inventory) if _inventory is not None else None
    max_inventory_pct = _optional_decimal_env("MM_MAX_INVENTORY_PCT")
    min_profit_bps = _optional_decimal_env("MM_MIN_PROFIT_BPS")
    _mm_fee_bps = os.environ.get("MM_FEE_BPS")
    mm_fee_bps = float(_mm_fee_bps) if _mm_fee_bps is not None else None
    _mm_target_profit_bps = os.environ.get("MM_TARGET_PROFIT_BPS")
    mm_target_profit_bps = float(_mm_target_profit_bps) if _mm_target_profit_bps is not None else None
    _mm_bid_offset_bps = os.environ.get("MM_BID_OFFSET_BPS")
    mm_bid_offset_bps = float(_mm_bid_offset_bps) if _mm_bid_offset_bps is not None else None
    _min_spread = os.environ.get("MM_MIN_SPREAD_BPS")
    min_spread_bps = Decimal(_min_spread) if _min_spread is not None else None
    _twap = os.environ.get("MM_TWAP_LOOKBACK_HOURS")
    twap_lookback_hours = int(_twap) if _twap is not None else None
    _unified_enabled = os.environ.get("UNIFIED_SIZING_ENABLED")
    unified_sizing_enabled = _unified_enabled is not None and _unified_enabled.strip().lower() in {"1", "true", "yes", "on"}
    _ask_sg_near = os.environ.get("ASK_SG_NEAR_BPS")
    ask_sg_near_bps = float(_ask_sg_near) if _ask_sg_near is not None else None
    _ask_sg_far = os.environ.get("ASK_SG_FAR_BPS")
    ask_sg_far_bps = float(_ask_sg_far) if _ask_sg_far is not None else None
    _twap_slope_mild = os.environ.get("TWAP_SLOPE_MILD_THRESHOLD")
    twap_slope_mild_threshold = float(_twap_slope_mild) if _twap_slope_mild is not None else None
    _twap_slope_steep = os.environ.get("TWAP_SLOPE_STEEP_THRESHOLD")
    twap_slope_steep_threshold = float(_twap_slope_steep) if _twap_slope_steep is not None else None
    _twap_slope_rising = os.environ.get("TWAP_SLOPE_RISING_THRESHOLD")
    twap_slope_rising_threshold = float(_twap_slope_rising) if _twap_slope_rising is not None else None
    _twap_slope_steep_rising = os.environ.get("TWAP_SLOPE_STEEP_RISING_THRESHOLD")
    twap_slope_steep_rising_threshold = float(_twap_slope_steep_rising) if _twap_slope_steep_rising is not None else None
    _sg_concavity = os.environ.get("SG_CONCAVITY_THRESHOLD")
    sg_concavity_threshold = float(_sg_concavity) if _sg_concavity is not None else None

    mm_kwargs = {
        "account_name": os.environ.get("MM_ACCOUNT_NAME", "paper_mm"),
    }
    if spread_bps is not None:
        mm_kwargs["spread_bps"] = spread_bps
    if quote_size is not None:
        mm_kwargs["quote_size"] = quote_size
    if quote_size_pct is not None:
        mm_kwargs["quote_size_pct"] = quote_size_pct
    if max_inventory is not None:
        mm_kwargs["max_inventory"] = max_inventory
    if max_inventory_pct is not None:
        mm_kwargs["max_inventory_pct"] = max_inventory_pct
    if min_profit_bps is not None:
        mm_kwargs["min_profit_bps"] = min_profit_bps
    if mm_fee_bps is not None:
        mm_kwargs["mm_fee_bps"] = mm_fee_bps
    if mm_target_profit_bps is not None:
        mm_kwargs["mm_target_profit_bps"] = mm_target_profit_bps
    if mm_bid_offset_bps is not None:
        mm_kwargs["bid_offset_bps"] = mm_bid_offset_bps
    if min_spread_bps is not None:
        mm_kwargs["min_spread_bps"] = min_spread_bps
    if stale_book_seconds is not None:
        mm_kwargs["stale_book_seconds"] = stale_book_seconds
    if twap_lookback_hours is not None:
        mm_kwargs["twap_lookback_hours"] = twap_lookback_hours
    mm_kwargs["unified_sizing_enabled"] = unified_sizing_enabled
    if ask_sg_near_bps is not None:
        mm_kwargs["ask_sg_near_bps"] = ask_sg_near_bps
    if ask_sg_far_bps is not None:
        mm_kwargs["ask_sg_far_bps"] = ask_sg_far_bps
    if twap_slope_mild_threshold is not None:
        mm_kwargs["twap_slope_mild_threshold"] = twap_slope_mild_threshold
    if twap_slope_steep_threshold is not None:
        mm_kwargs["twap_slope_steep_threshold"] = twap_slope_steep_threshold
    if twap_slope_rising_threshold is not None:
        mm_kwargs["twap_slope_rising_threshold"] = twap_slope_rising_threshold
    if twap_slope_steep_rising_threshold is not None:
        mm_kwargs["twap_slope_steep_rising_threshold"] = twap_slope_steep_rising_threshold
    if sg_concavity_threshold is not None:
        mm_kwargs["sg_concavity_threshold"] = sg_concavity_threshold

    mm_config = MarketMakingConfig(**mm_kwargs)

    if paper_strategy == "market_making":
        strategy: StrategyType = MarketMakingStrategy(mm_config)
    else:
        strategy_config = FundingCaptureConfig(
            spot_symbol="BTC-USD",
            perp_symbol="BTC-PERP",
            exchange="binance",
            entry_funding_rate_threshold=Decimal("0.0001"),
            exit_funding_rate_threshold=Decimal("0.00005"),
            position_size=Decimal("1"),
        )
        strategy = FundingCaptureStrategy(strategy_config)

    loop = PaperTradingLoop(
        session=session,
        strategy=strategy,
        risk_engine=RiskEngine(risk_config),
        fee_model=FixedBpsFeeModel(bps=Decimal("25")),
        iterations=1,
        strategy_mode=paper_strategy,
        market_making_config=mm_config,
    )

    if paper_strategy == "market_making":
        loop_interval_seconds = int(os.environ.get("LOOP_INTERVAL_SECONDS", "60"))
        running = True
        iteration = 0

        def _handle_sigterm(signum, _frame) -> None:  # type: ignore[no-untyped-def]
            nonlocal running
            ctx.logger.info("paper_trader_signal_received", signal=signum)
            running = False

        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_sigterm)

        try:
            while running:
                iteration += 1
                try:
                    signal_result, intents_executed, _payment = loop.run_one_iteration_market_making(
                        n=iteration,
                        funding_rate=Decimal("0"),
                        mark_price=Decimal("0"),
                    )
                    session.commit()
                    ctx.logger.info(
                        "iteration_summary",
                        iteration=iteration,
                        signal=signal_result,
                        intents_executed=intents_executed,
                        funding_payment=str(None),
                    )
                except Exception as exc:
                    session.rollback()
                    ctx.logger.error("iteration_failed", iteration=iteration, error=str(exc))
                if running:
                    time.sleep(loop_interval_seconds)
        except KeyboardInterrupt:
            ctx.logger.info("paper_trader_keyboard_interrupt_received")
        finally:
            session.close()
    else:
        try:
            summaries = loop.run()
            for s in summaries:
                ctx.logger.info(
                    "iteration_summary",
                    iteration=s.iteration,
                    signal=s.signal_result,
                    intents_executed=s.intents_executed,
                    funding_payment=str(s.funding_payment_amount),
                )
        finally:
            session.close()


if __name__ == "__main__":
    main()
