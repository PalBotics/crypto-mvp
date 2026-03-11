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
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.paper.fees import FixedBpsFeeModel
from core.risk.engine import RiskConfig, RiskEngine
from core.strategy.funding_capture import FundingCaptureConfig, FundingCaptureStrategy
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy

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


def _seed_mm_snapshot(session: Session, now: datetime) -> None:
    session.add(
        OrderBookSnapshot(
            exchange="kraken",
            adapter_name="kraken_rest",
            symbol="XBTUSD",
            exchange_symbol="XXBTZUSD",
            bid_price_1=Decimal("59970"),
            bid_size_1=Decimal("1"),
            ask_price_1=Decimal("60030"),
            ask_size_1=Decimal("1"),
            bid_price_2=Decimal("59969"),
            bid_size_2=Decimal("1"),
            ask_price_2=Decimal("60031"),
            ask_size_2=Decimal("1"),
            bid_price_3=Decimal("59968"),
            bid_size_3=Decimal("1"),
            ask_price_3=Decimal("60032"),
            ask_size_3=Decimal("1"),
            spread=Decimal("60"),
            spread_bps=Decimal("10"),
            mid_price=Decimal("60000"),
            event_ts=now,
            ingested_ts=now,
        )
    )
    session.add(
        MarketTick(
            exchange="kraken",
            adapter_name="kraken_rest",
            symbol="XBTUSD",
            exchange_symbol="XXBTZUSD",
            bid_price=Decimal("59970"),
            ask_price=Decimal("60030"),
            mid_price=Decimal("60000"),
            last_price=Decimal("60000"),
            bid_size=None,
            ask_size=None,
            event_ts=now,
            ingested_ts=now,
            sequence_id=None,
        )
    )
    session.commit()


def _make_mm_loop(session: Session) -> PaperTradingLoop:
    strategy_config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )
    risk_config = RiskConfig(
        max_data_age_seconds=3600,
        min_entry_funding_rate=Decimal("0.0001"),
        max_notional_per_symbol=Decimal("1000000"),
    )
    return PaperTradingLoop(
        session=session,
        strategy=MarketMakingStrategy(strategy_config),
        risk_engine=RiskEngine(risk_config),
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
        iterations=1,
        strategy_mode="market_making",
        market_making_config=strategy_config,
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


def test_market_making_requotes_buy_when_sell_is_already_resting(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    _seed_mm_snapshot(db_session, now)
    loop = _make_mm_loop(db_session)

    db_session.add(
        PositionSnapshot(
            exchange="kraken",
            account_name="paper_mm",
            symbol="XBTUSD",
            instrument_type="spot",
            side="buy",
            quantity=Decimal("0.001"),
            avg_entry_price=Decimal("59000"),
            mark_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=None,
            snapshot_ts=now,
        )
    )
    resting_sell = OrderIntent(
        strategy_signal_id=None,
        portfolio_id=None,
        mode="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
        side="sell",
        order_type="limit",
        time_in_force=None,
        quantity=Decimal("0.001"),
        limit_price=Decimal("61000"),
        reduce_only=False,
        post_only=False,
        client_order_id=None,
        status="pending",
        created_ts=now,
    )
    db_session.add(resting_sell)
    db_session.commit()

    signal_result, intents_executed, payment = loop.run_one_iteration_market_making(
        n=1,
        funding_rate=Decimal("0"),
        mark_price=Decimal("60000"),
    )

    pending = db_session.execute(
        select(OrderIntent)
        .where(OrderIntent.mode == "paper_mm")
        .where(OrderIntent.status == "pending")
        .order_by(OrderIntent.created_ts.asc())
    ).scalars().all()

    assert payment is None
    assert intents_executed == 0
    assert signal_result == "quoted_buy"
    assert len(pending) == 2
    assert sorted(intent.side for intent in pending) == ["buy", "sell"]
    assert next(intent for intent in pending if intent.side == "sell").id == resting_sell.id


def test_market_making_reports_no_action_when_both_sides_resting(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    _seed_mm_snapshot(db_session, now)
    loop = _make_mm_loop(db_session)

    db_session.add(
        PositionSnapshot(
            exchange="kraken",
            account_name="paper_mm",
            symbol="XBTUSD",
            instrument_type="spot",
            side="buy",
            quantity=Decimal("0.001"),
            avg_entry_price=Decimal("59000"),
            mark_price=Decimal("60000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            leverage=None,
            margin_used=None,
            snapshot_ts=now,
        )
    )
    db_session.add_all(
        [
            OrderIntent(
                strategy_signal_id=None,
                portfolio_id=None,
                mode="paper_mm",
                exchange="kraken",
                symbol="XBTUSD",
                side="buy",
                order_type="limit",
                time_in_force=None,
                quantity=Decimal("0.001"),
                limit_price=Decimal("59000"),
                reduce_only=False,
                post_only=False,
                client_order_id=None,
                status="pending",
                created_ts=now,
            ),
            OrderIntent(
                strategy_signal_id=None,
                portfolio_id=None,
                mode="paper_mm",
                exchange="kraken",
                symbol="XBTUSD",
                side="sell",
                order_type="limit",
                time_in_force=None,
                quantity=Decimal("0.001"),
                limit_price=Decimal("61000"),
                reduce_only=False,
                post_only=False,
                client_order_id=None,
                status="pending",
                created_ts=now,
            ),
        ]
    )
    db_session.commit()

    signal_result, intents_executed, payment = loop.run_one_iteration_market_making(
        n=1,
        funding_rate=Decimal("0"),
        mark_price=Decimal("60000"),
    )

    pending = db_session.execute(
        select(OrderIntent)
        .where(OrderIntent.mode == "paper_mm")
        .where(OrderIntent.status == "pending")
    ).scalars().all()

    assert payment is None
    assert intents_executed == 0
    assert signal_result == "no_action"
    assert len(pending) == 2
