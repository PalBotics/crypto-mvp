"""Dashboard API routes.

HTTP layer only — all query logic is delegated to core/reporting/queries.py.
Session is injected via FastAPI dependency injection.
"""

from __future__ import annotations

from typing import Annotated, Generator

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.db.session import SessionLocal
from core.reporting.queries import (
    get_open_positions,
    get_pnl_summary,
    get_recent_fills,
    get_risk_events,
    get_run_summary,
)

from apps.dashboard.schemas import (
    FillSchema,
    PnLSummarySchema,
    PositionSchema,
    RiskEventSchema,
    RunSummarySchema,
)

router = APIRouter()


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
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
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
