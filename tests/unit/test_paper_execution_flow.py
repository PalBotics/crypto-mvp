from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from unittest.mock import Mock

from core.models.market_tick import MarketTick
from core.models.order_intent import OrderIntent
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.paper.execution_flow import execute_one_paper_market_intent
from core.paper.fees import FixedBpsFeeModel


def _intent() -> OrderIntent:
    return OrderIntent(
        id=uuid4(),
        strategy_signal_id=None,
        portfolio_id=None,
        mode="paper",
        exchange="coinbase",
        symbol="BTC-USD",
        side="buy",
        order_type="market",
        time_in_force=None,
        quantity=Decimal("2"),
        limit_price=None,
        reduce_only=False,
        post_only=False,
        client_order_id="cid-flow-1",
        status="pending",
        created_ts=datetime(2026, 3, 6, 11, 59, tzinfo=timezone.utc),
    )


def _tick() -> MarketTick:
    return MarketTick(
        exchange="coinbase",
        adapter_name="coinbase",
        symbol="BTC-USD",
        exchange_symbol="BTC-USD",
        bid_price=Decimal("50000"),
        ask_price=Decimal("50010"),
        mid_price=Decimal("50005"),
        last_price=Decimal("50006"),
        bid_size=None,
        ask_size=None,
        event_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        ingested_ts=datetime(2026, 3, 6, 12, 0, tzinfo=timezone.utc),
        sequence_id=None,
    )


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


def test_execution_flow_success_persists_records_and_updates_intent() -> None:
    session = Mock()
    intent = _intent()
    tick = _tick()

    session.execute.side_effect = [_ScalarResult(intent), _ScalarResult(tick), _ScalarResult(None)]

    executed = execute_one_paper_market_intent(
        session=session,
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
    )

    assert executed is True
    assert session.execute.call_count == 3

    added = [call.args[0] for call in session.add.call_args_list]
    assert len(added) == 4

    order_record = added[0]
    fill_record = added[1]
    position_snapshot = added[2]
    pnl_snapshot = added[3]

    assert order_record.id is not None
    assert order_record.order_intent_id == intent.id
    assert order_record.status == "filled"
    assert order_record.filled_qty == Decimal("2")
    assert order_record.avg_fill_price == Decimal("50010")

    assert fill_record.order_record_id is not None
    assert fill_record.order_record_id == order_record.id
    assert fill_record.fill_price == Decimal("50010")
    assert fill_record.fill_qty == Decimal("2")

    assert isinstance(position_snapshot, PositionSnapshot)
    assert position_snapshot.exchange == "coinbase"
    assert position_snapshot.symbol == "BTC-USD"
    assert position_snapshot.account_name == "paper"
    assert position_snapshot.quantity == Decimal("2")
    assert position_snapshot.avg_entry_price == Decimal("50010")

    assert isinstance(pnl_snapshot, PnLSnapshot)
    assert pnl_snapshot.symbol == "BTC-USD"
    assert pnl_snapshot.strategy_name == "paper"
    assert pnl_snapshot.realized_pnl == Decimal("0")

    assert intent.status == "filled"
    session.commit.assert_called_once()


def test_execution_flow_noop_when_no_eligible_intent() -> None:
    session = Mock()
    session.execute.return_value = _ScalarResult(None)

    executed = execute_one_paper_market_intent(
        session=session,
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
    )

    assert executed is False
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_execution_flow_noop_when_no_matching_market_tick() -> None:
    session = Mock()
    session.execute.side_effect = [_ScalarResult(_intent()), _ScalarResult(None)]

    executed = execute_one_paper_market_intent(
        session=session,
        fee_model=FixedBpsFeeModel(bps=Decimal("10")),
    )

    assert executed is False
    session.add.assert_not_called()
    session.commit.assert_not_called()
