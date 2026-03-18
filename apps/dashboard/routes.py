"""Dashboard API routes.

HTTP layer only — all query logic is delegated to core/reporting/queries.py.
Session is injected via FastAPI dependency injection.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Annotated, Generator

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from scipy.signal import savgol_filter
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from core.db.session import SessionLocal
from core.models.fill_record import FillRecord
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.paper_deposit import PaperDeposit
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.models.quote_snapshot import QuoteSnapshot
from core.models.risk_event import RiskEvent
from core.paper.hedge_ratio import compute_hedge_ratio
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
from core.utils.logging import get_logger
from core.reporting.account import compute_paper_account_snapshot

from apps.dashboard.schemas import (
    FillSchema,
    FundingRateSchema,
    HedgeStatusSchema,
    MarketTickSchema,
    OrderBookSchema,
    PnLSummarySchema,
    PositionSchema,
    RiskEventSchema,
    RunSummarySchema,
)

router = APIRouter()
_log = get_logger(__name__)

USD_QUANT = Decimal("0.01")
BPS_QUANT = Decimal("0.0001")
ALLOWED_HOURS = {1, 2, 4, 8, 24}
TWAP_OVERRIDE_PATH = Path(__file__).resolve().parents[2] / "data" / "twap_lookback_override.json"


def _round_decimal(value: Decimal, quant: Decimal) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def _to_fixed_8(value: Decimal | float | int) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP), "f")


class TwapLookbackRequest(BaseModel):
    hours: int


class DepositRequest(BaseModel):
    amount: str
    note: str | None = None


def _resolve_twap_lookback_hours() -> int:
    if TWAP_OVERRIDE_PATH.exists():
        try:
            payload = json.loads(TWAP_OVERRIDE_PATH.read_text(encoding="utf-8"))
            hours = int(payload.get("hours"))
            if hours in ALLOWED_HOURS:
                return hours
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    env_raw = os.environ.get("MM_TWAP_LOOKBACK_HOURS")
    if env_raw is not None:
        try:
            env_hours = int(env_raw)
            if env_hours in ALLOWED_HOURS:
                return env_hours
        except ValueError:
            pass

    return 2


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/health")
def health(session: SessionDep) -> dict:
    latest_snapshot_ts = session.execute(
        select(func.max(OrderBookSnapshot.event_ts)).where(
            OrderBookSnapshot.exchange == "kraken",
            OrderBookSnapshot.symbol == "XBTUSD",
        )
    ).scalar_one_or_none()

    age_seconds: int | None = None
    if latest_snapshot_ts is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - latest_snapshot_ts).total_seconds()))

    return {
        "status": "ok",
        "last_snapshot_age_seconds": age_seconds,
        "last_snapshot_ts": latest_snapshot_ts,
    }


@router.get("/twap-lookback")
def twap_lookback_get() -> dict:
    return {"hours": _resolve_twap_lookback_hours()}


@router.post("/twap-lookback")
def twap_lookback_set(payload: TwapLookbackRequest) -> dict:
    hours = int(payload.hours)
    if hours not in ALLOWED_HOURS:
        raise HTTPException(status_code=422, detail="hours must be one of: 1, 2, 4, 8, 24")

    TWAP_OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TWAP_OVERRIDE_PATH.write_text(json.dumps({"hours": hours}), encoding="utf-8")

    return {"hours": hours, "status": "ok"}


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


@router.get("/runs/{account_name}/hedge-status", response_model=HedgeStatusSchema)
def hedge_status(account_name: str, session: SessionDep) -> HedgeStatusSchema:
    hs = compute_hedge_ratio(account_name, session)
    return HedgeStatusSchema.from_hedge_status(hs)


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


@router.post("/runs/{account_name}/reset")
def reset_run_history(account_name: str, session: SessionDep) -> dict:
    intent_ids_subquery = select(OrderIntent.id).where(OrderIntent.mode == account_name)
    order_record_ids_subquery = select(OrderRecord.id).where(
        OrderRecord.order_intent_id.in_(intent_ids_subquery)
    )

    rows_deleted = {
        "fills": 0,
        "positions": 0,
        "risk_events": 0,
        "pnl_snapshots": 0,
        "order_records": 0,
        "order_intents": 0,
    }

    try:
        with session.begin():
            fill_delete_result = session.execute(
                delete(FillRecord).where(FillRecord.order_record_id.in_(order_record_ids_subquery))
            )
            rows_deleted["fills"] = int(fill_delete_result.rowcount or 0)

            order_record_delete_result = session.execute(
                delete(OrderRecord).where(OrderRecord.id.in_(order_record_ids_subquery))
            )
            rows_deleted["order_records"] = int(order_record_delete_result.rowcount or 0)

            order_intent_delete_result = session.execute(
                delete(OrderIntent).where(OrderIntent.mode == account_name)
            )
            rows_deleted["order_intents"] = int(order_intent_delete_result.rowcount or 0)

            position_delete_result = session.execute(
                delete(PositionSnapshot).where(PositionSnapshot.account_name == account_name)
            )
            rows_deleted["positions"] = int(position_delete_result.rowcount or 0)

            risk_delete_result = session.execute(
                delete(RiskEvent).where(RiskEvent.strategy_name == account_name)
            )
            rows_deleted["risk_events"] = int(risk_delete_result.rowcount or 0)

            pnl_delete_result = session.execute(
                delete(PnLSnapshot).where(PnLSnapshot.strategy_name == account_name)
            )
            rows_deleted["pnl_snapshots"] = int(pnl_delete_result.rowcount or 0)
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"reset failed: {exc}") from exc

    _log.info(
        "paper_trader_reset",
        account_name=account_name,
        rows_deleted=rows_deleted,
    )

    return {
        "success": True,
        "account_name": account_name,
        "rows_deleted": rows_deleted,
    }


@router.get("/market/ticks", response_model=list[MarketTickSchema])
def recent_ticks(
    session: SessionDep,
    symbol: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 120,
    before: datetime | None = None,
) -> list[MarketTickSchema]:
    rows = get_recent_ticks(session, symbol, limit=limit, before=before)
    return [MarketTickSchema.from_row(r) for r in rows]


@router.get("/market/order-books", response_model=list[OrderBookSchema])
def recent_order_books(
    session: SessionDep,
    symbol: Annotated[str, Query()] = "XBTUSD",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    before: datetime | None = None,
) -> list[OrderBookSchema]:
    rows = get_recent_order_books(session, symbol, limit=limit, before=before)
    return [OrderBookSchema.from_row(r) for r in rows]


@router.get("/market/funding", response_model=list[FundingRateSchema])
def recent_funding_rates(
    session: SessionDep,
    symbol: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 48,
) -> list[FundingRateSchema]:
    rows = get_recent_funding_rates(session, symbol, limit=limit)
    return [FundingRateSchema.from_row(r) for r in rows]


@router.get("/market/perp-status")
def perp_status(session: SessionDep) -> list[dict]:
    feeds: list[tuple[str, str]] = [
        ("kraken_futures", "XBTUSD"),
        ("coinbase_advanced", "ETH-PERP"),
    ]

    now_utc = datetime.now(timezone.utc)
    items: list[dict] = []

    for exchange, symbol in feeds:
        tick = session.execute(
            select(MarketTick)
            .where(MarketTick.exchange == exchange, MarketTick.symbol == symbol)
            .order_by(MarketTick.event_ts.desc())
            .limit(1)
        ).scalar_one_or_none()

        funding = session.execute(
            select(FundingRateSnapshot)
            .where(
                FundingRateSnapshot.exchange == exchange,
                FundingRateSnapshot.symbol == symbol,
            )
            .order_by(FundingRateSnapshot.event_ts.desc())
            .limit(1)
        ).scalar_one_or_none()

        if tick is None and funding is None:
            continue

        newest_ts = max(
            [
                ts
                for ts in [
                    tick.event_ts if tick is not None else None,
                    funding.event_ts if funding is not None else None,
                ]
                if ts is not None
            ]
        )
        age_seconds = max(0, int((now_utc - newest_ts).total_seconds()))
        stale = age_seconds > 120

        funding_rate = (
            Decimal(str(funding.funding_rate)) if funding is not None else None
        )
        funding_interval_hours = (
            int(funding.funding_interval_hours)
            if funding is not None and funding.funding_interval_hours
            else None
        )

        funding_rate_apr_pct: str | None = None
        if funding_rate is not None and funding_interval_hours is not None and funding_interval_hours > 0:
            # Unit normalization note:
            # - Kraken futures adapter stores raw `fundingRate` from
            #   /derivatives/api/v3/tickers ("current absolute funding rate").
            #   In stored snapshots this is already an annualized rate in decimal
            #   form (for example 0.0062385519 == 0.62385519% APR), so do NOT
            #   multiply by settlement periods again.
            # - Coinbase Advanced stores interval funding-rate fractions from
            #   product `future_product_details[.perpetual_details].funding_rate`
            #   (typically hourly for INTX perps), so annualize by periods.
            if exchange == "kraken_futures":
                apr_pct = funding_rate * Decimal("100")
            else:
                periods_per_year = Decimal(str((24 / funding_interval_hours) * 365))
                apr_pct = funding_rate * periods_per_year * Decimal("100")
            funding_rate_apr_pct = str(
                apr_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )

        items.append(
            {
                "exchange": exchange,
                "symbol": symbol,
                "mark_price": (
                    str(funding.mark_price)
                    if funding is not None and funding.mark_price is not None
                    else (str(tick.mid_price) if tick is not None else None)
                ),
                "bid_price": str(tick.bid_price) if tick is not None else None,
                "ask_price": str(tick.ask_price) if tick is not None else None,
                "funding_rate": str(funding.funding_rate) if funding is not None else None,
                "funding_rate_apr_pct": funding_rate_apr_pct,
                "predicted_funding_rate": (
                    str(funding.predicted_funding_rate)
                    if funding is not None and funding.predicted_funding_rate is not None
                    else None
                ),
                "data_age_seconds": age_seconds,
                "is_stale": stale,
            }
        )

    return items


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


@router.get("/account")
def account(session: SessionDep) -> dict:
    snapshot = compute_paper_account_snapshot(
        session=session,
        account_name="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
    )
    return snapshot.to_api_dict()


@router.post("/deposit")
def deposit_create(payload: DepositRequest, session: SessionDep) -> dict:
    try:
        amount = Decimal(payload.amount.strip())
    except Exception:
        raise HTTPException(status_code=422, detail="amount must be a valid number")

    if amount <= Decimal("0"):
        raise HTTPException(status_code=422, detail="amount must be positive")
    if amount > Decimal("10000"):
        raise HTTPException(status_code=422, detail="amount must not exceed 10000 per deposit")

    note = payload.note.strip() if payload.note else None

    record = PaperDeposit(
        amount=amount,
        note=note,
        created_ts=datetime.now(timezone.utc),
    )
    session.add(record)
    session.flush()

    snapshot = compute_paper_account_snapshot(
        session=session,
        account_name="paper_mm",
        exchange="kraken",
        symbol="XBTUSD",
    )
    session.commit()

    return {
        "id": str(record.id),
        "amount": str(_round_decimal(amount, USD_QUANT)),
        "note": record.note,
        "created_ts": record.created_ts.isoformat().replace("+00:00", "Z"),
        "new_account_value": str(_round_decimal(snapshot.account_value, USD_QUANT)),
    }


@router.get("/deposits")
def deposits_list(session: SessionDep) -> dict:
    records = session.execute(
        select(PaperDeposit).order_by(PaperDeposit.created_ts.desc())
    ).scalars().all()

    total = sum((r.amount for r in records), Decimal("0"))

    return {
        "deposits": [
            {
                "id": str(r.id),
                "amount": str(_round_decimal(Decimal(str(r.amount)), USD_QUANT)),
                "note": r.note,
                "created_ts": (
                    r.created_ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                    if r.created_ts.tzinfo is not None
                    else r.created_ts.isoformat() + "Z"
                ),
            }
            for r in records
        ],
        "total_deposited": str(_round_decimal(total, USD_QUANT)),
        "deposit_count": len(records),
    }


@router.get("/market-range")
def market_range(
    session: SessionDep,
    hours: Annotated[int, Query()] = 2,
    before: datetime | None = None,
) -> dict:
    if hours not in ALLOWED_HOURS:
        raise HTTPException(status_code=422, detail="hours must be one of: 1, 2, 4, 8, 24")

    window_end = before if before is not None else datetime.now(timezone.utc)
    cutoff = window_end - timedelta(hours=int(hours))

    snapshots = session.execute(
        select(OrderBookSnapshot)
        .where(
            OrderBookSnapshot.exchange == "kraken",
            OrderBookSnapshot.symbol == "XBTUSD",
            OrderBookSnapshot.event_ts > cutoff,
            OrderBookSnapshot.event_ts < window_end,
        )
        .order_by(OrderBookSnapshot.event_ts.asc())
    ).scalars().all()

    mids = [snap.mid_price for snap in snapshots if snap.mid_price is not None]
    low = min(mids) if mids else None
    high = max(mids) if mids else None
    current_mid = snapshots[-1].mid_price if snapshots else None

    range_usd: Decimal | None = None
    range_bps: Decimal | None = None
    if low is not None and high is not None:
        range_usd = _round_decimal(high - low, USD_QUANT)

    if range_usd is not None and current_mid not in (None, Decimal("0")):
        range_bps = _round_decimal((range_usd / current_mid) * Decimal("10000"), BPS_QUANT)

    return {
        "hours": int(hours),
        "low": None if low is None else str(low),
        "high": None if high is None else str(high),
        "range_usd": None if range_usd is None else str(range_usd),
        "range_bps": None if range_bps is None else str(range_bps),
        "current_mid": None if current_mid is None else str(current_mid),
        "snapshots": [
            {
                "ts": snap.event_ts,
                "mid": None if snap.mid_price is None else str(snap.mid_price),
                "bid": None if snap.bid_price_1 is None else str(snap.bid_price_1),
                "ask": None if snap.ask_price_1 is None else str(snap.ask_price_1),
            }
            for snap in snapshots
        ],
        "last_updated": datetime.now(timezone.utc),
    }


@router.get("/sg-curve")
def sg_curve(
    session: SessionDep,
    hours: Annotated[int, Query()] = 2,
    window: Annotated[int, Query(ge=3)] = 25,
    degree: Annotated[int, Query(ge=1)] = 2,
    before: datetime | None = None,
) -> dict:
    if hours not in ALLOWED_HOURS:
        raise HTTPException(status_code=422, detail="hours must be one of: 1, 2, 4, 8, 24")

    effective_window = int(window)
    if effective_window % 2 == 0:
        effective_window += 1

    if int(degree) >= effective_window:
        raise HTTPException(status_code=422, detail="degree must be less than window")

    window_end = before if before is not None else datetime.now(timezone.utc)
    cutoff = window_end - timedelta(hours=int(hours))
    snapshots = session.execute(
        select(OrderBookSnapshot)
        .where(
            OrderBookSnapshot.exchange == "kraken",
            OrderBookSnapshot.symbol == "XBTUSD",
            OrderBookSnapshot.event_ts > cutoff,
            OrderBookSnapshot.event_ts < window_end,
            OrderBookSnapshot.mid_price.is_not(None),
        )
        .order_by(OrderBookSnapshot.event_ts.asc())
    ).scalars().all()

    mids = np.array([float(s.mid_price) for s in snapshots], dtype=float)
    enough_points = mids.size >= effective_window

    sg_values = None
    slope_values = None
    concavity_values = None
    if enough_points:
        sg_values = savgol_filter(mids, window_length=effective_window, polyorder=int(degree), deriv=0)
        slope_values = savgol_filter(mids, window_length=effective_window, polyorder=int(degree), deriv=1)
        concavity_values = savgol_filter(mids, window_length=effective_window, polyorder=int(degree), deriv=2)

    points: list[dict] = []
    for idx, snap in enumerate(snapshots):
        ts = snap.event_ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_value = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        sg = None if sg_values is None else _to_fixed_8(sg_values[idx])
        slope = None if slope_values is None else _to_fixed_8(slope_values[idx])
        concavity = None if concavity_values is None else _to_fixed_8(concavity_values[idx])

        points.append(
            {
                "ts": ts_value,
                "mid": _to_fixed_8(snap.mid_price),
                "sg": sg,
                "slope": slope,
                "concavity": concavity,
            }
        )

    return {
        "hours": int(hours),
        "window": int(effective_window),
        "degree": int(degree),
        "points": points,
        "last_updated": datetime.now(timezone.utc),
    }


@router.get("/quote-history")
def quote_history(
    session: SessionDep,
    hours: Annotated[int, Query()] = 8,
    before: datetime | None = None,
) -> dict:
    if hours not in ALLOWED_HOURS:
        raise HTTPException(status_code=422, detail="hours must be one of: 1, 2, 4, 8, 24")

    window_end = before if before is not None else datetime.now(timezone.utc)
    cutoff = window_end - timedelta(hours=int(hours))
    snapshots = session.execute(
        select(QuoteSnapshot)
        .where(
            QuoteSnapshot.exchange == "kraken",
            QuoteSnapshot.symbol == "XBTUSD",
            QuoteSnapshot.account_name == "paper_mm",
            QuoteSnapshot.snapshot_ts > cutoff,
            QuoteSnapshot.snapshot_ts < window_end,
        )
        .order_by(QuoteSnapshot.snapshot_ts.asc())
    ).scalars().all()

    payload: list[dict] = []
    for snap in snapshots:
        twap_vs_mid_bps: str | None = None
        if snap.twap != Decimal("0"):
            delta_bps = ((snap.mid_price - snap.twap) / snap.twap) * Decimal("10000")
            twap_vs_mid_bps = str(_round_decimal(delta_bps, BPS_QUANT))

        payload.append(
            {
                "ts": snap.snapshot_ts,
                "twap": str(snap.twap),
                "mid_price": str(snap.mid_price),
                "bid_quote": None if snap.bid_quote is None else str(snap.bid_quote),
                "ask_quote": None if snap.ask_quote is None else str(snap.ask_quote),
                "twap_vs_mid_bps": twap_vs_mid_bps,
            }
        )

    fill_counts = (
        select(
            OrderRecord.order_intent_id.label("order_intent_id"),
            func.count(FillRecord.id).label("fill_count"),
        )
        .join(FillRecord, FillRecord.order_record_id == OrderRecord.id)
        .group_by(OrderRecord.order_intent_id)
        .subquery()
    )

    intent_rows = session.execute(
        select(
            OrderIntent.created_ts,
            OrderIntent.side,
            OrderIntent.limit_price,
            OrderIntent.quantity,
            OrderIntent.status,
            fill_counts.c.fill_count,
        )
        .outerjoin(fill_counts, fill_counts.c.order_intent_id == OrderIntent.id)
        .where(
            OrderIntent.mode == "paper_mm",
            OrderIntent.created_ts > cutoff,
            OrderIntent.created_ts < window_end,
        )
        .order_by(OrderIntent.created_ts.asc())
    ).all()

    order_events: list[dict] = []
    for row in intent_rows:
        fill_count = int(row.fill_count or 0)
        status = "filled" if fill_count > 0 else str(row.status).lower()
        side = str(row.side).lower()

        ts = row.created_ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_value = ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        order_events.append(
            {
                "ts": ts_value,
                "side": side,
                "price": None if row.limit_price is None else str(row.limit_price),
                "status": status,
                "qty": str(row.quantity),
            }
        )

    return {
        "hours": int(hours),
        "snapshots": payload,
        "order_events": order_events,
        "last_updated": datetime.now(timezone.utc),
    }


@router.get("/fill-drought")
def fill_drought(session: SessionDep) -> dict:
    now = datetime.now(timezone.utc)
    midnight_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)

    last_fill_ts = session.execute(
        select(func.max(FillRecord.fill_ts))
        .join(OrderRecord, FillRecord.order_record_id == OrderRecord.id)
        .join(OrderIntent, OrderRecord.order_intent_id == OrderIntent.id)
        .where(OrderIntent.mode == "paper_mm")
    ).scalar_one_or_none()

    fill_count_total = session.execute(
        select(func.count(FillRecord.id))
        .join(OrderRecord, FillRecord.order_record_id == OrderRecord.id)
        .join(OrderIntent, OrderRecord.order_intent_id == OrderIntent.id)
        .where(OrderIntent.mode == "paper_mm")
    ).scalar_one()

    fill_count_today = session.execute(
        select(func.count(FillRecord.id))
        .join(OrderRecord, FillRecord.order_record_id == OrderRecord.id)
        .join(OrderIntent, OrderRecord.order_intent_id == OrderIntent.id)
        .where(
            OrderIntent.mode == "paper_mm",
            FillRecord.fill_ts >= midnight_utc,
        )
    ).scalar_one()

    hours_since_fill: float | None = None
    if last_fill_ts is not None:
        hours_since_fill = round((now - last_fill_ts).total_seconds() / 3600, 2)

    return {
        "last_fill_ts": last_fill_ts,
        "hours_since_fill": hours_since_fill,
        "fill_count_today": int(fill_count_today or 0),
        "fill_count_total": int(fill_count_total or 0),
    }
