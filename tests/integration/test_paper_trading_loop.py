"""Integration test for the paper trading loop.

Runs three iterations against an in-memory SQLite database:
    Iteration 1: funding_rate above entry threshold, no open position -> "entered"
    Iteration 2: funding_rate still elevated, position already open   -> "no_action"
    Iteration 3: funding_rate below exit threshold, position open     -> "exited"

Verifies that all expected DB records (PositionSnapshot, FillRecord,
PnLSnapshot, FundingPayment) are present after the loop completes.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.paper_trader.main import IterationSummary, PaperTradingLoop
from core.models.fill_record import FillRecord
from core.models.funding_payment import FundingPayment
from core.models.market_tick import MarketTick
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.paper.fees import FixedBpsFeeModel
from core.risk.engine import RiskConfig, RiskEngine
from core.strategy.funding_capture import FundingCaptureConfig, FundingCaptureStrategy

# ------------------------------------------------------------------
# Test constants
# ------------------------------------------------------------------

EXCHANGE = "binance"
SPOT_SYMBOL = "BTC-USD"
PERP_SYMBOL = "BTC-PERP"
MARK_PRICE = Decimal("50000")

# Three synthetic funding periods:
#   period 1: rate well above entry threshold (0.0001) -> enter
#   period 2: rate still elevated, position open        -> no_action
#   period 3: rate below exit threshold (0.00005)       -> exit
MARKET_DATA = [
    (Decimal("0.0005"), MARK_PRICE),
    (Decimal("0.0003"), MARK_PRICE),
    (Decimal("0.00002"), MARK_PRICE),
]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _seed_market_ticks(session: Session) -> None:
    """Seed one MarketTick per symbol so execute_one_paper_market_intent can fill."""
    now = datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc)
    for symbol in (SPOT_SYMBOL, PERP_SYMBOL):
        session.add(
            MarketTick(
                exchange=EXCHANGE,
                adapter_name=EXCHANGE,
                symbol=symbol,
                exchange_symbol=symbol,
                bid_price=Decimal("49990"),
                ask_price=Decimal("50010"),
                mid_price=Decimal("50000"),
                last_price=Decimal("50000"),
                bid_size=None,
                ask_size=None,
                event_ts=now,
                ingested_ts=now,
                sequence_id=None,
            )
        )
    session.commit()


def _make_loop(session: Session) -> PaperTradingLoop:
    strategy_config = FundingCaptureConfig(
        spot_symbol=SPOT_SYMBOL,
        perp_symbol=PERP_SYMBOL,
        exchange=EXCHANGE,
        entry_funding_rate_threshold=Decimal("0.0001"),
        exit_funding_rate_threshold=Decimal("0.00005"),
        position_size=Decimal("1"),
    )
    risk_config = RiskConfig(
        max_data_age_seconds=3600,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("1000000"),
    )
    return PaperTradingLoop(
        session=session,
        strategy=FundingCaptureStrategy(strategy_config),
        risk_engine=RiskEngine(risk_config),
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
        iterations=3,
        market_data=MARKET_DATA,
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------

def test_paper_trading_loop_three_iterations(db_session: Session) -> None:
    """Full 3-iteration loop: enter -> hold -> exit, with record count assertions."""
    _seed_market_ticks(db_session)
    loop = _make_loop(db_session)

    summaries = loop.run()

    # ------------------------------------------------------------------
    # Iteration-level assertions
    # ------------------------------------------------------------------

    assert len(summaries) == 3
    assert all(isinstance(s, IterationSummary) for s in summaries)
    assert all(s.signal_result != "error" for s in summaries), (
        f"Unexpected error in iteration: {[s for s in summaries if s.signal_result == 'error']}"
    )

    iter1, iter2, iter3 = summaries

    # Iteration 1: entry
    assert iter1.signal_result == "entered"
    assert iter1.intents_executed == 2          # spot buy + perp sell
    assert iter1.funding_payment_amount is not None
    assert iter1.funding_payment_amount < 0     # long rate positive -> trader paid

    # Iteration 2: hold (no new signal, funding still accrues)
    assert iter2.signal_result == "no_action"
    assert iter2.intents_executed == 0
    assert iter2.funding_payment_amount is not None
    assert iter2.funding_payment_amount < 0

    # Iteration 3: exit
    assert iter3.signal_result == "exited"
    assert iter3.intents_executed == 2          # spot sell + perp buy
    assert iter3.funding_payment_amount is None  # position closed before accrual

    # ------------------------------------------------------------------
    # Database record count assertions
    # ------------------------------------------------------------------

    # Two legs -> two PositionSnapshot rows (spot + perp, both quantity=0 after exit)
    positions = db_session.execute(select(PositionSnapshot)).scalars().all()
    assert len(positions) == 2

    # 2 fills from entry + 2 fills from exit = 4
    fills = db_session.execute(select(FillRecord)).scalars().all()
    assert len(fills) == 4

    # One PnLSnapshot per fill = 4
    pnls = db_session.execute(select(PnLSnapshot)).scalars().all()
    assert len(pnls) == 4

    # FundingPayment: iter1 (perp open after entry) + iter2 (perp still open)
    # iter3 finds quantity=0, returns None -> no payment
    payments = db_session.execute(select(FundingPayment)).scalars().all()
    assert len(payments) == 2

    # ------------------------------------------------------------------
    # Spot-check a few field values
    # ------------------------------------------------------------------

    for fill in fills:
        assert fill.exchange == EXCHANGE
        assert fill.symbol in (SPOT_SYMBOL, PERP_SYMBOL)

    for payment in payments:
        assert payment.symbol == PERP_SYMBOL
        assert payment.account_name == "paper"
        assert isinstance(payment.payment_amount, Decimal)
        assert payment.payment_amount < 0   # positive rate -> trader paid

    # All positions closed after the exit cycle
    for pos in positions:
        assert Decimal(str(pos.quantity)) == Decimal("0")
