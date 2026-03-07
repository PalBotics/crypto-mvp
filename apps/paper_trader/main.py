from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from core.alerting.evaluator import AlertEvaluator
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FeeModel
from core.paper.funding_accrual import accrue_funding_payment
from core.risk.engine import RiskEngine
from core.strategy.funding_capture import FundingCaptureStrategy
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
        strategy: FundingCaptureStrategy,
        risk_engine: RiskEngine,
        fee_model: FeeModel,
        iterations: int,
        market_data: list[tuple[Decimal, Decimal]] | None = None,
        alert_evaluator: AlertEvaluator | None = None,
    ) -> None:
        self._session = session
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._fee_model = fee_model
        self._iterations = iterations
        self._market_data: list[tuple[Decimal, Decimal]] = market_data or []
        self._alert_evaluator = alert_evaluator

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
            # 1. Evaluate strategy.
            signal_result = self._strategy.evaluate(
                self._session, funding_rate, mark_price
            )
            _log.info("signal_evaluated", iteration=n, signal=signal_result)

            # 2. Flush so any new pending intents are visible to queries.
            self._session.flush()

            # 3. Drain all pending intents created this cycle.
            intents_executed = 0
            if signal_result in ("entered", "exited"):
                now = datetime.now(timezone.utc)
                while execute_one_paper_market_intent(
                    session=self._session,
                    fee_model=self._fee_model,
                    risk_engine=self._risk_engine,
                    funding_rate=funding_rate,
                    latest_funding_ts=now,
                    mode=self._strategy.config.mode,
                ):
                    intents_executed += 1
                    _log.info("intent_executed", iteration=n, count=intents_executed)

                if intents_executed == 0:
                    _log.info("all_intents_skipped", iteration=n, signal=signal_result)

            # 4. Accrue funding for the open perp position (if any).
            payment = accrue_funding_payment(
                session=self._session,
                symbol=self._strategy.config.perp_symbol,
                exchange=self._strategy.config.exchange,
                account_name=self._strategy.config.mode,
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


def main() -> None:
    """CLI entry point for the paper trading loop."""
    from core.app import bootstrap_app
    from core.db.session import get_db_session
    from core.paper.fees import FixedBpsFeeModel
    from core.risk.engine import RiskConfig
    from core.strategy.funding_capture import FundingCaptureConfig

    ctx = bootstrap_app(service_name="paper_trader", check_db=True)
    session = get_db_session()

    strategy_config = FundingCaptureConfig(
        spot_symbol="BTC-USD",
        perp_symbol="BTC-PERP",
        exchange="binance",
        entry_funding_rate_threshold=Decimal("0.0001"),
        exit_funding_rate_threshold=Decimal("0.00005"),
        position_size=Decimal("1"),
    )
    risk_config = RiskConfig(
        max_data_age_seconds=3600,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("1000000"),
    )
    loop = PaperTradingLoop(
        session=session,
        strategy=FundingCaptureStrategy(strategy_config),
        risk_engine=RiskEngine(risk_config),
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
        iterations=1,
    )

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
