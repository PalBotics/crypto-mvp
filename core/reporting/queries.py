from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.funding_accrual import FundingAccrual
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.funding_payment import FundingPayment
from core.models.market_tick import MarketTick
from core.models.order_intent import OrderIntent
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.risk_event import RiskEvent


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Row types (plain dataclasses — no SQLAlchemy internals exposed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionRow:
    exchange: str
    symbol: str
    account_name: str
    quantity: Decimal
    avg_entry_price: Decimal
    snapshot_ts: datetime
    side: str | None = None
    position_type: str | None = None
    contract_qty: int | None = None
    contract_size: Decimal | None = None
    mark_price: Decimal | None = None
    margin_posted: Decimal | None = None


@dataclass(frozen=True)
class PnLSummaryRow:
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal
    total_funding_paid: Decimal
    total_accrued_not_yet_settled: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class FillRow:
    fill_ts: datetime
    exchange: str
    symbol: str
    side: str
    fill_price: Decimal
    fill_qty: Decimal
    fee_amount: Decimal  # sourced from FillRecord.fee_paid


@dataclass(frozen=True)
class RiskEventRow:
    created_ts: datetime
    rule_name: str
    event_type: str
    severity: str
    details: dict  # sourced from RiskEvent.details_json


@dataclass(frozen=True)
class RunSummaryRow:
    account_name: str
    open_position_count: int
    total_fills: int
    total_risk_events: int
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    funding_paid: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class MarketTickRow:
    exchange: str
    symbol: str
    bid_price: Decimal
    ask_price: Decimal
    mid_price: Decimal
    last_price: Decimal | None
    event_ts: datetime


@dataclass(frozen=True)
class OrderBookRow:
    exchange: str
    symbol: str
    bid_price_1: Decimal
    bid_size_1: Decimal
    ask_price_1: Decimal
    ask_size_1: Decimal
    spread: Decimal | None
    spread_bps: Decimal | None
    mid_price: Decimal | None
    event_ts: datetime


@dataclass(frozen=True)
class FundingRateRow:
    exchange: str
    symbol: str
    funding_rate: Decimal
    predicted_funding_rate: Decimal | None
    mark_price: Decimal | None
    next_funding_ts: datetime | None
    event_ts: datetime


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def get_open_positions(session: Session, account_name: str) -> list[PositionRow]:
    """Return all PositionSnapshots with quantity > 0 for the given account_name."""
    stmt = (
        select(PositionSnapshot)
        .where(PositionSnapshot.account_name == account_name)
        .where(PositionSnapshot.quantity > 0)
        .order_by(PositionSnapshot.snapshot_ts.desc())
    )
    rows = session.execute(stmt).scalars().all()
    return [
        PositionRow(
            exchange=row.exchange,
            symbol=row.symbol,
            account_name=row.account_name,
            quantity=_to_decimal(row.quantity),
            avg_entry_price=_to_decimal(row.avg_entry_price),
            snapshot_ts=row.snapshot_ts,
            side=row.side,
            position_type=row.position_type,
            contract_qty=row.contract_qty,
            contract_size=_to_decimal(row.contract_size) if row.contract_size else None,
            mark_price=_to_decimal(row.mark_price) if row.mark_price else None,
            margin_posted=_to_decimal(row.margin_posted) if row.margin_posted else None,
        )
        for row in rows
    ]


def get_pnl_summary(session: Session, account_name: str) -> PnLSummaryRow:
    """Aggregate realized PnL, unrealized PnL, funding paid, and unsettled accruals.

    PnLSnapshot is keyed by strategy_name (== account_name / run_id).
    FundingPayment is keyed by account_name.
    FundingAccrual is keyed by account_name.
    """
    realized = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.realized_pnl)).where(
                PnLSnapshot.strategy_name == account_name
            )
        ).scalar_one()
    )
    unrealized = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.unrealized_pnl)).where(
                PnLSnapshot.strategy_name == account_name
            )
        ).scalar_one()
    )
    funding_paid = _to_decimal(
        session.execute(
            select(func.sum(FundingPayment.payment_amount)).where(
                FundingPayment.account_name == account_name
            )
        ).scalar_one()
    )
    accrued_not_settled = _to_decimal(
        session.execute(
            select(func.sum(FundingAccrual.accrual_usd)).where(
                FundingAccrual.account_name == account_name
            ).where(
                FundingAccrual.settled == False
            )
        ).scalar_one()
    )
    net = realized + unrealized + funding_paid + accrued_not_settled
    return PnLSummaryRow(
        total_realized_pnl=realized,
        total_unrealized_pnl=unrealized,
        total_funding_paid=funding_paid,
        total_accrued_not_yet_settled=accrued_not_settled,
        net_pnl=net,
    )


def get_recent_fills(
    session: Session, account_name: str, limit: int = 20
) -> list[FillRow]:
    """Return the most recent fills for account_name, joined through OrderIntent.mode."""
    stmt = (
        select(FillRecord)
        .select_from(FillRecord)
        .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
        .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
        .where(OrderIntent.mode == account_name)
        .order_by(FillRecord.fill_ts.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        FillRow(
            fill_ts=row.fill_ts,
            exchange=row.exchange,
            symbol=row.symbol,
            side=row.side,
            fill_price=_to_decimal(row.fill_price),
            fill_qty=_to_decimal(row.fill_qty),
            fee_amount=_to_decimal(row.fee_paid),
        )
        for row in rows
    ]


def get_risk_events(
    session: Session, account_name: str, limit: int = 50
) -> list[RiskEventRow]:
    """Return the most recent risk events for account_name.

    RiskEvent has no account_name column; it uses strategy_name as the
    run-scoped identifier (set to account_name / run_id by the risk engine).
    """
    stmt = (
        select(RiskEvent)
        .where(RiskEvent.strategy_name == account_name)
        .order_by(RiskEvent.created_ts.desc())
        .limit(limit)
    )
    rows = session.execute(stmt).scalars().all()
    return [
        RiskEventRow(
            created_ts=row.created_ts,
            rule_name=row.rule_name,
            event_type=row.event_type,
            severity=row.severity,
            details=row.details_json,
        )
        for row in rows
    ]


def get_run_summary(session: Session, account_name: str) -> RunSummaryRow:
    """Combine position, PnL, fill count, and risk event count for a named run."""
    open_positions = get_open_positions(session, account_name)
    pnl = get_pnl_summary(session, account_name)

    fill_count = int(
        session.execute(
            select(func.count(FillRecord.id))
            .select_from(FillRecord)
            .join(OrderRecord, OrderRecord.id == FillRecord.order_record_id)
            .join(OrderIntent, OrderIntent.id == OrderRecord.order_intent_id)
            .where(OrderIntent.mode == account_name)
        ).scalar_one()
    )

    risk_count = int(
        session.execute(
            select(func.count(RiskEvent.id)).where(
                RiskEvent.strategy_name == account_name
            )
        ).scalar_one()
    )

    return RunSummaryRow(
        account_name=account_name,
        open_position_count=len(open_positions),
        total_fills=fill_count,
        total_risk_events=risk_count,
        realized_pnl=pnl.total_realized_pnl,
        unrealized_pnl=pnl.total_unrealized_pnl,
        funding_paid=pnl.total_funding_paid,
        net_pnl=pnl.net_pnl,
    )


def get_recent_ticks(
    session: Session,
    symbol: str | None,
    limit: int = 120,
    before: datetime | None = None,
) -> list[MarketTickRow]:
    if symbol is None:
        # All-symbol mode: return the newest row per exchange/symbol so one
        # high-frequency feed does not starve other feeds out of a small limit.
        scan_limit = max(limit * 50, 500)
        stmt = select(MarketTick)
        if before is not None:
            stmt = stmt.where(MarketTick.event_ts < before)
        stmt = stmt.order_by(MarketTick.event_ts.desc()).limit(scan_limit)
        scanned_rows = session.execute(stmt).scalars().all()

        seen: set[tuple[str, str]] = set()
        rows: list[MarketTick] = []
        for row in scanned_rows:
            key = (row.exchange, row.symbol)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= limit:
                break
    else:
        stmt = select(MarketTick).where(MarketTick.symbol == symbol)
        if before is not None:
            stmt = stmt.where(MarketTick.event_ts < before)
        stmt = stmt.order_by(MarketTick.event_ts.desc()).limit(limit)
        rows = session.execute(stmt).scalars().all()
    return [
        MarketTickRow(
            exchange=row.exchange,
            symbol=row.symbol,
            bid_price=_to_decimal(row.bid_price),
            ask_price=_to_decimal(row.ask_price),
            mid_price=_to_decimal(row.mid_price),
            last_price=None if row.last_price is None else _to_decimal(row.last_price),
            event_ts=row.event_ts,
        )
        for row in rows
    ]


def get_recent_order_books(
    session: Session,
    symbol: str,
    limit: int = 20,
    before: datetime | None = None,
) -> list[OrderBookRow]:
    stmt = select(OrderBookSnapshot).where(OrderBookSnapshot.symbol == symbol)
    if before is not None:
        stmt = stmt.where(OrderBookSnapshot.event_ts < before)

    stmt = stmt.order_by(OrderBookSnapshot.event_ts.desc()).limit(limit)
    rows = session.execute(stmt).scalars().all()
    return [
        OrderBookRow(
            exchange=row.exchange,
            symbol=row.symbol,
            bid_price_1=_to_decimal(row.bid_price_1),
            bid_size_1=_to_decimal(row.bid_size_1),
            ask_price_1=_to_decimal(row.ask_price_1),
            ask_size_1=_to_decimal(row.ask_size_1),
            spread=None if row.spread is None else _to_decimal(row.spread),
            spread_bps=None if row.spread_bps is None else _to_decimal(row.spread_bps),
            mid_price=None if row.mid_price is None else _to_decimal(row.mid_price),
            event_ts=row.event_ts,
        )
        for row in rows
    ]


def get_recent_funding_rates(
    session: Session, symbol: str | None, limit: int = 48
) -> list[FundingRateRow]:
    if symbol is None:
        # All-symbol mode: return the newest row per exchange/symbol so one
        # feed cannot dominate short result windows.
        scan_limit = max(limit * 50, 500)
        stmt = select(FundingRateSnapshot).order_by(FundingRateSnapshot.event_ts.desc()).limit(scan_limit)
        scanned_rows = session.execute(stmt).scalars().all()

        seen: set[tuple[str, str]] = set()
        rows: list[FundingRateSnapshot] = []
        for row in scanned_rows:
            key = (row.exchange, row.symbol)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= limit:
                break
    else:
        stmt = (
            select(FundingRateSnapshot)
            .where(FundingRateSnapshot.symbol == symbol)
            .order_by(FundingRateSnapshot.event_ts.desc())
            .limit(limit)
        )
        rows = session.execute(stmt).scalars().all()
    return [
        FundingRateRow(
            exchange=row.exchange,
            symbol=row.symbol,
            funding_rate=_to_decimal(row.funding_rate),
            predicted_funding_rate=None
            if row.predicted_funding_rate is None
            else _to_decimal(row.predicted_funding_rate),
            mark_price=None if row.mark_price is None else _to_decimal(row.mark_price),
            next_funding_ts=row.next_funding_ts,
            event_ts=row.event_ts,
        )
        for row in rows
    ]
