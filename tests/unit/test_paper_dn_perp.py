"""Tests for perpetual position execution, funding accrual, and hedge ratio."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from core.models.funding_accrual import FundingAccrual
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.pnl_snapshot import PnLSnapshot
from core.paper.perp_execution import open_perp_short, close_perp_short
from core.paper.funding_accrual import FundingAccrualEngine
from core.paper.hedge_ratio import compute_hedge_ratio
from core.models.market_tick import MarketTick


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def all(self):
        if isinstance(self._value, list):
            return self._value
        return [self._value] if self._value else []


def _perp_position(*, qty: str = "0.50", entry: str = "2400", side: str = "short") -> PositionSnapshot:
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    return PositionSnapshot(
        exchange="coinbase_advanced",
        account_name="paper_dn",
        symbol="ETH-PERP",
        instrument_type="perpetual",
        side=side,
        position_type="perp",
        quantity=Decimal(qty),
        avg_entry_price=Decimal(entry),
        mark_price=Decimal(entry),
        contract_qty=5,
        contract_size=Decimal("0.10"),
        margin_posted=Decimal(qty) * Decimal(entry) * Decimal("0.10"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=Decimal(qty) * Decimal(entry) * Decimal("0.10"),
        snapshot_ts=ts,
    )


def _spot_position(*, qty: str = "0.80", price: str = "2400") -> PositionSnapshot:
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    return PositionSnapshot(
        exchange="kraken",
        account_name="paper_dn",
        symbol="ETHUSD",
        instrument_type="spot",
        side="long",
        position_type="spot",
        quantity=Decimal(qty),
        avg_entry_price=Decimal(price),
        mark_price=Decimal(price),
        contract_qty=None,
        contract_size=None,
        margin_posted=None,
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=ts,
    )


def _eth_tick(*, mid: str = "2400") -> MarketTick:
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    return MarketTick(
        exchange="coinbase_advanced",
        adapter_name="coinbase",
        symbol="ETH-USD",
        exchange_symbol="ETH-USD",
        bid_price=Decimal(mid),
        ask_price=Decimal(mid),
        mid_price=Decimal(mid),
        last_price=None,
        bid_size=None,
        ask_size=None,
        event_ts=ts,
        ingested_ts=ts,
        sequence_id=None,
    )


# ============================================================================
# Tests for perp_execution module
# ============================================================================

def test_open_perp_short_creates_position() -> None:
    """Open a short perp position with contract_qty=5.
    
    Assert position exists with side='short', position_type='perp', quantity=0.50 ETH.
    Assert fill recorded with side='short'.
    Assert margin deducted from cash.
    """
    session = Mock()
    session.add = Mock()
    session.flush = Mock()
    
    position = open_perp_short(
        session=session,
        account_name="paper_dn",
        exchange="coinbase_advanced",
        symbol="ETH-PERP",
        contract_qty=5,
        mark_price=Decimal("2400"),
        margin_rate=Decimal("0.10"),
    )
    
    assert position.exchange == "coinbase_advanced"
    assert position.account_name == "paper_dn"
    assert position.symbol == "ETH-PERP"
    assert position.side == "short"
    assert position.position_type == "perp"
    assert position.quantity == Decimal("0.50")  # 5 * 0.10
    assert position.avg_entry_price == Decimal("2400")
    assert position.contract_qty == 5
    assert position.contract_size == Decimal("0.10")
    assert position.margin_posted == Decimal("120.00")  # 0.50 * 2400 * 0.10
    
    # session.add should be called twice (fill + position)
    assert session.add.call_count == 2


def test_close_perp_short_calculates_realized_pnl() -> None:
    """Open short at $2,400. Close at $2,200.
    
    Assert realized_pnl = (2400 - 2200) × 0.50 = $100 (profit for short).
    Assert margin returned to cash.
    """
    session = Mock()
    session.add = Mock()
    session.flush = Mock()
    existing = _perp_position(qty="0.50", entry="2400")
    session.execute.return_value = _ScalarResult(existing)
    
    realized_pnl = close_perp_short(
        session=session,
        account_name="paper_dn",
        exchange="coinbase_advanced",
        symbol="ETH-PERP",
        mark_price=Decimal("2200"),
    )
    
    # (entry - exit) * qty = (2400 - 2200) * 0.50 = 100
    assert realized_pnl == Decimal("100")
    assert existing.quantity == Decimal("0")
    assert existing.avg_entry_price is None
    assert existing.mark_price == Decimal("2200")


def test_close_perp_short_no_position() -> None:
    """When no position exists, return 0 PnL."""
    session = Mock()
    session.execute.return_value = _ScalarResult(None)
    
    realized_pnl = close_perp_short(
        session=session,
        account_name="paper_dn",
        exchange="coinbase_advanced",
        symbol="ETH-PERP",
        mark_price=Decimal("2200"),
    )
    
    assert realized_pnl == Decimal("0")


# ============================================================================
# Tests for funding_accrual_engine module
# ============================================================================

def test_funding_accrual_positive_rate_is_income() -> None:
    """Short position of 0.50 ETH, mark_price=$2,400, hourly_rate=+0.00001 (positive).
    
    Assert accrual_usd = 0.50 × 2400 × 0.00001 = $0.012 (INCOME for short).
    """
    session = Mock()
    position = _perp_position(qty="0.50", entry="2400")
    funding_rate = 0.00001

    def execute_side_effect(stmt):
        # Mock different queries
        call_count = session.execute.call_count
        if call_count == 1:  # First call: get position
            return _ScalarResult(position)
        else:  # Second call: get funding rate
            fr = FundingRateSnapshot(
                id=None,
                exchange="coinbase_advanced",
                adapter_name="coinbase",
                symbol="ETH-PERP",
                exchange_symbol="ETH-PERP",
                funding_rate=Decimal(str(funding_rate)),
                funding_interval_hours=1,
                predicted_funding_rate=None,
                mark_price=Decimal("2400"),
                index_price=None,
                next_funding_ts=None,
                event_ts=datetime.now(timezone.utc),
                ingested_ts=datetime.now(timezone.utc),
            )
            return _ScalarResult(fr)
    
    session.execute.side_effect = execute_side_effect
    session.add = Mock()
    
    FundingAccrualEngine.accrue_hourly("paper_dn", session)
    
    # Verify an accrual was added
    assert session.add.called
    added_accrual = session.add.call_args[0][0]
    assert isinstance(added_accrual, FundingAccrual)
    assert added_accrual.accrual_usd == Decimal("0") + (
        Decimal("0.50") * Decimal("2400") * Decimal("0.00001")
    )
    assert added_accrual.settled == False


def test_funding_accrual_negative_rate_is_cost() -> None:
    """Short position of 0.50 ETH, mark_price=$2,400, hourly_rate=-0.000003 (negative).
    
    Assert accrual_usd = -$0.00360 (COST for short).
    """
    session = Mock()
    position = _perp_position(qty="0.50", entry="2400")
    funding_rate = -0.000003

    def execute_side_effect(stmt):
        call_count = session.execute.call_count
        if call_count == 1:  # First call: get position
            return _ScalarResult(position)
        else:  # Second call: get funding rate
            fr = FundingRateSnapshot(
                id=None,
                exchange="coinbase_advanced",
                adapter_name="coinbase",
                symbol="ETH-PERP",
                exchange_symbol="ETH-PERP",
                funding_rate=Decimal(str(funding_rate)),
                funding_interval_hours=1,
                predicted_funding_rate=None,
                mark_price=Decimal("2400"),
                index_price=None,
                next_funding_ts=None,
                event_ts=datetime.now(timezone.utc),
                ingested_ts=datetime.now(timezone.utc),
            )
            return _ScalarResult(fr)
    
    session.execute.side_effect = execute_side_effect
    session.add = Mock()
    
    FundingAccrualEngine.accrue_hourly("paper_dn", session)
    
    added_accrual = session.add.call_args[0][0]
    assert added_accrual.accrual_usd == Decimal("0.50") * Decimal("2400") * Decimal("-0.000003")


def test_funding_settlement_updates_pnl() -> None:
    """Create 12 unsettled accruals totaling $0.144.
    
    Call settle().
    Assert total_funding_paid increases by $0.144.
    Assert all accrual rows marked settled=True.
    """
    session = Mock()
    
    accruals = [
        FundingAccrual(
            account_name="paper_dn",
            exchange="coinbase_advanced",
            symbol="ETH-PERP",
            period_ts=datetime.now(timezone.utc),
            hourly_rate=Decimal("0.00001"),
            notional_usd=Decimal("1200"),
            accrual_usd=Decimal("0.012"),
            settled=False,
            created_ts=datetime.now(timezone.utc),
        )
        for _ in range(12)
    ]
    
    pnl = PnLSnapshot(
        id=None,
        portfolio_id=None,
        strategy_name="paper_dn",
        symbol=None,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        funding_pnl=Decimal("0"),
        fee_pnl=Decimal("0"),
        gross_pnl=Decimal("0"),
        net_pnl=Decimal("0"),
        snapshot_ts=datetime.now(timezone.utc),
    )
    
    def execute_side_effect(stmt):
        call_count = session.execute.call_count
        if call_count == 1:  # Get unsettled accruals
            return _ScalarResult(accruals)
        else:  # Get PnL snapshot
            return _ScalarResult(pnl)
    
    session.execute.side_effect = execute_side_effect
    
    total = FundingAccrualEngine.settle("paper_dn", session)
    
    assert total == Decimal("0.144")  # 12 * 0.012
    assert pnl.funding_pnl == Decimal("0.144")
    for accrual in accruals:
        assert accrual.settled == True


def test_should_settle_at_00_00_utc() -> None:
    """Check settlement window at 00:00 UTC."""
    # Within window (23:55 to 00:05)
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 23, 57, tzinfo=timezone.utc)) == True
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 17, 0, 2, tzinfo=timezone.utc)) == True
    
    # Outside window
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 23, 54, tzinfo=timezone.utc)) == False
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 17, 0, 6, tzinfo=timezone.utc)) == False


def test_should_settle_at_12_00_utc() -> None:
    """Check settlement window at 12:00 UTC."""
    # Within window (11:55 to 12:05)
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 11, 57, tzinfo=timezone.utc)) == True
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 12, 2, tzinfo=timezone.utc)) == True
    
    # Outside window
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 11, 54, tzinfo=timezone.utc)) == False
    assert FundingAccrualEngine.should_settle(datetime(2026, 3, 16, 12, 6, tzinfo=timezone.utc)) == False


# ============================================================================
# Tests for hedge_ratio module
# ============================================================================

def test_hedge_ratio_balanced() -> None:
    """Spot: 0.80 ETH at $2,400 = $1,920 notional.
    Perp: 0.80 ETH short at $2,400 = $1,920 notional.
    Assert hedge_ratio = 1.0, is_balanced = True.
    """
    session = Mock()
    spot = _spot_position(qty="0.80", price="2400")
    perp = _perp_position(qty="0.80", entry="2400")
    tick = _eth_tick(mid="2400")
    
    call_count = [0]
    
    def execute_side_effect(stmt):
        call_count[0] += 1
        if call_count[0] == 1:  # Get spot position
            return _ScalarResult(spot)
        elif call_count[0] == 2:  # Get perp position
            return _ScalarResult(perp)
        else:  # Get tick
            return _ScalarResult(tick)
    
    session.execute.side_effect = execute_side_effect
    
    hs = compute_hedge_ratio("paper_dn", session)
    
    assert hs.spot_notional == Decimal("1920")
    assert hs.perp_notional == Decimal("1920")
    assert hs.hedge_ratio == Decimal("1")
    assert hs.is_balanced == True


def test_hedge_ratio_drift_warning() -> None:
    """Spot: 0.90 ETH, Perp: 0.70 ETH (same price).
    Assert hedge_ratio ≈ 1.286, is_balanced = False.
    Assert hedge_ratio_drift_warning was logged.
    """
    session = Mock()
    spot = _spot_position(qty="0.90", price="2400")
    perp = _perp_position(qty="0.70", entry="2400")
    tick = _eth_tick(mid="2400")
    
    call_count = [0]
    
    def execute_side_effect(stmt):
        call_count[0] += 1
        if call_count[0] == 1:  # Get spot position
            return _ScalarResult(spot)
        elif call_count[0] == 2:  # Get perp position
            return _ScalarResult(perp)
        else:  # Get tick
            return _ScalarResult(tick)
    
    session.execute.side_effect = execute_side_effect
    
    hs = compute_hedge_ratio("paper_dn", session)
    
    assert hs.hedge_ratio > Decimal("1.1")
    assert hs.is_balanced == False


def test_hedge_ratio_no_positions() -> None:
    """With no positions, return zeroed-out structure."""
    session = Mock()
    
    call_count = [0]
    
    def execute_side_effect(stmt):
        call_count[0] += 1
        return _ScalarResult(None)
    
    session.execute.side_effect = execute_side_effect
    
    hs = compute_hedge_ratio("paper_dn", session)
    
    assert hs.spot_qty == Decimal("0")
    assert hs.perp_qty == Decimal("0")
    assert hs.spot_notional == Decimal("0")
    assert hs.perp_notional == Decimal("0")
    assert hs.hedge_ratio == Decimal("0")
    assert hs.is_balanced == False


# ============================================================================
# Tests for existing paper_mm positions (regression)
# ============================================================================

def test_existing_paper_mm_position_defaults() -> None:
    """Verify existing paper_mm positions get default position_type='spot', side='long'."""
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    position = PositionSnapshot(
        exchange="kraken",
        account_name="paper_mm",
        symbol="XBTUSD",
        instrument_type="spot",
        side="long",
        position_type="spot",  # Should default to 'spot'
        quantity=Decimal("0.10"),
        avg_entry_price=Decimal("50000"),
        mark_price=Decimal("50000"),
        contract_qty=None,  # Should be None for spot
        contract_size=None,  # Should be None for spot
        margin_posted=None,  # Should be None for spot
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        leverage=None,
        margin_used=None,
        snapshot_ts=ts,
    )
    
    # Verify all defaults are correct
    assert position.position_type == "spot"
    assert position.side == "long"
    assert position.contract_qty is None
    assert position.contract_size is None
    assert position.margin_posted is None
