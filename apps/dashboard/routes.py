"""Dashboard API routes.

HTTP layer only — all query logic is delegated to core/reporting/queries.py.
Session is injected via FastAPI dependency injection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Generator

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.session import SessionLocal
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.reporting.queries import (
    get_recent_funding_rates,
    get_open_positions,
    get_recent_order_books,
    get_pnl_summary,
    get_recent_fills,
    get_recent_ticks,
    get_risk_events,
    get_run_summary,
)

from apps.dashboard.schemas import (
    FillSchema,
    FundingRateSchema,
    MarketTickSchema,
    OrderBookSchema,
    PnLSummarySchema,
    PositionSchema,
    RiskEventSchema,
    RunSummarySchema,
)

router = APIRouter()

USD_QUANT = Decimal("0.01")
BPS_QUANT = Decimal("0.0001")


def _round_decimal(value: Decimal, quant: Decimal) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/runs/{account_name}/summary", response_model=RunSummarySchema)
def run_summary(account_name: str, session: SessionDep) -> RunSummarySchema:
    row = get_run_summary(session, account_name)
    return RunSummarySchema.from_row(row)


@router.get("/runs/{account_name}/positions", response_model=list[PositionSchema])
def open_positions(account_name: str, session: SessionDep) -> list[PositionSchema]:
    rows = get_open_positions(session, account_name)
    return [PositionSchema.from_row(r) for r in rows]


@router.get("/runs/{account_name}/pnl", response_model=PnLSummarySchema)
def pnl_summary(account_name: str, session: SessionDep) -> PnLSummarySchema:
    row = get_pnl_summary(session, account_name)
    return PnLSummarySchema.from_row(row)


@router.get("/runs/{account_name}/fills", response_model=list[FillSchema])
def recent_fills(
    account_name: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> list[FillSchema]:
    rows = get_recent_fills(session, account_name, limit=limit)
    return [FillSchema.from_row(r) for r in rows]


@router.get("/runs/{account_name}/risk-events", response_model=list[RiskEventSchema])
def risk_events(
    account_name: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RiskEventSchema]:
    rows = get_risk_events(session, account_name, limit=limit)
    return [RiskEventSchema.from_row(r) for r in rows]


@router.get("/market/ticks", response_model=list[MarketTickSchema])
def recent_ticks(
    session: SessionDep,
    symbol: Annotated[str, Query()] = "XBTUSD",
    limit: Annotated[int, Query(ge=1, le=500)] = 120,
) -> list[MarketTickSchema]:
    rows = get_recent_ticks(session, symbol, limit=limit)
    return [MarketTickSchema.from_row(r) for r in rows]


@router.get("/market/order-books", response_model=list[OrderBookSchema])
def recent_order_books(
    session: SessionDep,
    symbol: Annotated[str, Query()] = "XBTUSD",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OrderBookSchema]:
    rows = get_recent_order_books(session, symbol, limit=limit)
    return [OrderBookSchema.from_row(r) for r in rows]


@router.get("/market/funding", response_model=list[FundingRateSchema])
def recent_funding_rates(
    session: SessionDep,
    symbol: Annotated[str, Query()] = "XBTUSD",
    limit: Annotated[int, Query(ge=1, le=200)] = 48,
) -> list[FundingRateSchema]:
    rows = get_recent_funding_rates(session, symbol, limit=limit)
    return [FundingRateSchema.from_row(r) for r in rows]


@router.get("/quotes")
def quotes(session: SessionDep) -> dict:
    intents = session.execute(
        select(OrderIntent)
        .where(
            OrderIntent.mode == "paper_mm",
            OrderIntent.status == "pending",
        )
        .order_by(OrderIntent.created_ts.desc())
    ).scalars().all()

    latest_book = session.execute(
        select(OrderBookSnapshot)
        .where(
            OrderBookSnapshot.exchange == "kraken",
            OrderBookSnapshot.symbol == "XBTUSD",
        )
        .order_by(OrderBookSnapshot.event_ts.desc())
        .limit(1)
    ).scalar_one_or_none()

    quote_items: list[dict] = []
    market_bid = latest_book.bid_price_1 if latest_book else None
    market_ask = latest_book.ask_price_1 if latest_book else None
    mid_price = latest_book.mid_price if latest_book else None

    for intent in intents:
        limit_price = intent.limit_price
        side = str(intent.side).lower()

        distance_usd: str | None = None
        distance_bps: str | None = None

        if latest_book and limit_price is not None and mid_price not in (None, Decimal("0")):
            if side == "buy" and market_ask is not None:
                diff = market_ask - limit_price
            elif side == "sell" and market_bid is not None:
                diff = limit_price - market_bid
            else:
                diff = None

            if diff is not None:
                distance_usd = str(_round_decimal(diff, USD_QUANT))
                bps = (diff / mid_price) * Decimal("10000")
                distance_bps = str(_round_decimal(bps, BPS_QUANT))

        quote_items.append(
            {
                "side": side,
                "limit_price": None if limit_price is None else str(limit_price),
                "mid_price": None if mid_price is None else str(mid_price),
                "market_bid": None if market_bid is None else str(market_bid),
                "market_ask": None if market_ask is None else str(market_ask),
                "distance_usd": distance_usd,
                "distance_bps": distance_bps,
                "created_ts": intent.created_ts,
                "status": intent.status,
            }
        )

    return {
        "quotes": quote_items,
        "last_updated": datetime.now(timezone.utc),
    }
