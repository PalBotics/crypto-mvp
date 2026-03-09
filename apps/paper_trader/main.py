from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import os
import signal
import time

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.alerting.evaluator import AlertEvaluator
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.order_intent import OrderIntent
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FeeModel
from core.paper.funding_accrual import accrue_funding_payment
from core.risk.engine import RiskEngine
from core.strategy.funding_capture import FundingCaptureStrategy
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy
from core.utils.logging import get_logger

_log = get_logger(__name__)


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

        current_position = self._current_position(
            exchange=strategy.config.exchange,
            symbol=strategy.config.symbol,
            account_name=self._market_making_config.account_name,
        )
        now = datetime.now(timezone.utc)
        intents = strategy.evaluate(
            self._session,
            snapshot,
            current_position,
            now,
        )

        for intent in intents:
            intent.mode = self._market_making_config.account_name
            self._session.add(intent)

        self._session.flush()

        intents_executed = 0
        for intent in intents:
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

        signal_result = "quoted" if intents else "no_action"
        _log.info(
            "signal_evaluated",
            iteration=n,
            signal=signal_result,
            intents_generated=len(intents),
            intents_executed=intents_executed,
        )
        return signal_result, intents_executed, None

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
    _inventory = os.environ.get("MM_MAX_INVENTORY")
    max_inventory = Decimal(_inventory) if _inventory is not None else None
    _min_spread = os.environ.get("MM_MIN_SPREAD_BPS")
    min_spread_bps = Decimal(_min_spread) if _min_spread is not None else None

    mm_kwargs = {
        "account_name": os.environ.get("MM_ACCOUNT_NAME", "paper_mm"),
    }
    if spread_bps is not None:
        mm_kwargs["spread_bps"] = spread_bps
    if quote_size is not None:
        mm_kwargs["quote_size"] = quote_size
    if max_inventory is not None:
        mm_kwargs["max_inventory"] = max_inventory
    if min_spread_bps is not None:
        mm_kwargs["min_spread_bps"] = min_spread_bps
    if stale_book_seconds is not None:
        mm_kwargs["stale_book_seconds"] = stale_book_seconds

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
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
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
