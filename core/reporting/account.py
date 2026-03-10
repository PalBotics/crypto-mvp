from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import os

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.fill_record import FillRecord
from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.models.order_record import OrderRecord
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.utils.logging import get_logger

USD_QUANT = Decimal("0.01")
BTC_QUANT = Decimal("0.00000001")
PCT_QUANT = Decimal("0.01")

_log = get_logger(__name__)


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _q(value: Decimal, quant: Decimal) -> Decimal:
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def resolve_paper_starting_capital() -> Decimal:
    raw = os.environ.get("PAPER_STARTING_CAPITAL", "1000.00")
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal("1000.00")


@dataclass(frozen=True)
class PaperAccountSnapshot:
    starting_capital: Decimal
    realized_pnl: Decimal
    fees_paid: Decimal
    unrealized_pnl: Decimal
    account_value: Decimal
    btc_held: Decimal
    btc_value_usd: Decimal
    cash_value: Decimal
    pct_in_btc: Decimal
    currency: str = "USD"

    def to_api_dict(self) -> dict:
        return {
            "starting_capital": str(_q(self.starting_capital, USD_QUANT)),
            "realized_pnl": str(_q(self.realized_pnl, USD_QUANT)),
            "fees_paid": str(_q(self.fees_paid, USD_QUANT)),
            "unrealized_pnl": str(_q(self.unrealized_pnl, USD_QUANT)),
            "account_value": str(_q(self.account_value, USD_QUANT)),
            "btc_held": str(_q(self.btc_held, BTC_QUANT)),
            "btc_value_usd": str(_q(self.btc_value_usd, USD_QUANT)),
            "cash_value": str(_q(self.cash_value, USD_QUANT)),
            "pct_in_btc": str(_q(self.pct_in_btc, PCT_QUANT)),
            "currency": self.currency,
        }


def compute_paper_account_snapshot(
    session: Session,
    account_name: str = "paper_mm",
    exchange: str = "kraken",
    symbol: str = "XBTUSD",
    starting_capital: Decimal | None = None,
) -> PaperAccountSnapshot:
    capital = resolve_paper_starting_capital() if starting_capital is None else starting_capital

    realized_pnl = _to_decimal(
        session.execute(
            select(func.sum(PnLSnapshot.realized_pnl)).where(PnLSnapshot.strategy_name == account_name)
        ).scalar_one()
    )

    fees_paid = _to_decimal(
        session.execute(
            select(func.sum(FillRecord.fee_paid))
            .select_from(FillRecord)
            .join(OrderRecord, FillRecord.order_record_id == OrderRecord.id)
            .join(OrderIntent, OrderRecord.order_intent_id == OrderIntent.id)
            .where(OrderIntent.mode == account_name)
        ).scalar_one()
    )

    latest_position = (
        session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.account_name == account_name)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        .scalars()
        .first()
    )

    unrealized_pnl = Decimal("0")
    btc_held = Decimal("0")
    if latest_position is not None:
        unrealized_pnl = _to_decimal(latest_position.unrealized_pnl)
        raw_qty = _to_decimal(latest_position.quantity)
        side = (latest_position.side or "").strip().lower()
        if side in {"buy", "long"}:
            btc_held = raw_qty
        elif side in {"sell", "short"}:
            btc_held = -raw_qty
        else:
            btc_held = raw_qty

    latest_book = (
        session.execute(
            select(OrderBookSnapshot)
            .where(OrderBookSnapshot.exchange == exchange)
            .where(OrderBookSnapshot.symbol == symbol)
            .order_by(OrderBookSnapshot.event_ts.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    mid_price = _to_decimal(latest_book.mid_price) if latest_book is not None else Decimal("0")
    btc_value_usd = btc_held * mid_price

    account_value = capital + realized_pnl - fees_paid + unrealized_pnl
    cash_value = account_value - btc_value_usd

    _log.info(
        "paper_account_value_components",
        starting_capital=str(capital),
        realized_pnl=str(realized_pnl),
        fees_paid=str(fees_paid),
        unrealized_pnl=str(unrealized_pnl),
        account_value=str(account_value),
    )

    pct_in_btc = Decimal("0")
    if account_value != Decimal("0"):
        pct_in_btc = (btc_value_usd / account_value) * Decimal("100")

    return PaperAccountSnapshot(
        starting_capital=capital,
        realized_pnl=realized_pnl,
        fees_paid=fees_paid,
        unrealized_pnl=unrealized_pnl,
        account_value=account_value,
        btc_held=btc_held,
        btc_value_usd=btc_value_usd,
        cash_value=cash_value,
        pct_in_btc=pct_in_btc,
    )
