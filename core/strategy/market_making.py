from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.models.order_book_snapshot import OrderBookSnapshot
from core.models.order_intent import OrderIntent
from core.utils.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class MarketMakingConfig:
    exchange: str = "kraken"
    symbol: str = "XBTUSD"
    account_name: str = "paper_mm"
    spread_bps: Decimal = Decimal("20")
    quote_size: Decimal = Decimal("0.001")
    max_inventory: Decimal = Decimal("0.01")
    min_spread_bps: Decimal = Decimal("0.01")
    stale_book_seconds: int = 120
    twap_lookback_hours: int = 2

    def __post_init__(self) -> None:
        if self.twap_lookback_hours not in {1, 2, 4, 8, 24}:
            raise ValueError("twap_lookback_hours must be one of: 1, 2, 4, 8, 24")


@dataclass(frozen=True)
class QuoteContext:
    twap: Decimal
    current_mid: Decimal
    bid_quote: Decimal
    ask_quote: Decimal
    snapshot_count: int


class MarketMakingStrategy:
    def __init__(self, config: MarketMakingConfig) -> None:
        self.config = config
        self.last_quote_context: QuoteContext | None = None

    def evaluate(
        self,
        session: Session,
        order_book: OrderBookSnapshot,
        current_position: Decimal,
        current_ts: datetime,
    ) -> list[OrderIntent]:
        self.last_quote_context = None

        age_seconds = (current_ts - order_book.event_ts).total_seconds()
        if age_seconds > self.config.stale_book_seconds:
            _log.info(
                "market_making_stale_book",
                age_seconds=age_seconds,
                stale_book_seconds=self.config.stale_book_seconds,
            )
            _log.info(
                "market_making_signal_generated",
                mid_price=(str(order_book.mid_price) if order_book.mid_price is not None else None),
                bid_price=None,
                ask_price=None,
                market_spread_bps=(
                    str(order_book.spread_bps) if order_book.spread_bps is not None else None
                ),
                our_spread_bps=str(self.config.spread_bps),
                current_position=str(current_position),
                intents_generated=0,
            )
            return []

        market_spread_bps = order_book.spread_bps
        if market_spread_bps is None or market_spread_bps < self.config.min_spread_bps:
            _log.info(
                "market_making_spread_too_tight",
                market_spread_bps=(
                    str(market_spread_bps) if market_spread_bps is not None else None
                ),
                min_spread_bps=str(self.config.min_spread_bps),
            )
            _log.info(
                "market_making_signal_generated",
                mid_price=(str(order_book.mid_price) if order_book.mid_price is not None else None),
                bid_price=None,
                ask_price=None,
                market_spread_bps=(
                    str(order_book.spread_bps) if order_book.spread_bps is not None else None
                ),
                our_spread_bps=str(self.config.spread_bps),
                current_position=str(current_position),
                intents_generated=0,
            )
            return []

        if order_book.mid_price is None:
            _log.info("market_making_signal_generated", intents_generated=0)
            return []

        twap, snapshot_count = self._calculate_twap(
            session=session,
            current_ts=current_ts,
            current_mid=order_book.mid_price,
        )
        twap_vs_mid_bps = Decimal("0")
        if order_book.mid_price != Decimal("0"):
            twap_vs_mid_bps = ((twap - order_book.mid_price) / order_book.mid_price) * Decimal("10000")
        _log.info(
            "twap_calculated",
            twap=str(twap),
            current_mid=str(order_book.mid_price),
            twap_lookback_hours=self.config.twap_lookback_hours,
            snapshot_count=snapshot_count,
            twap_vs_mid_bps=str(twap_vs_mid_bps.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        )

        half_spread = self.config.spread_bps / Decimal("2") / Decimal("10000")
        bid_price = self._round_price(twap * (Decimal("1") - half_spread))
        ask_price = self._round_price(twap * (Decimal("1") + half_spread))

        intents: list[OrderIntent] = []

        if current_position < self.config.max_inventory:
            intents.append(
                self._build_intent(
                    side="buy",
                    limit_price=bid_price,
                    current_ts=current_ts,
                )
            )
        else:
            _log.info(
                "buy_suppressed_max_inventory",
                current_position=str(current_position),
                max_inventory=str(self.config.max_inventory),
            )

        if current_position > Decimal("0"):
            intents.append(
                self._build_intent(
                    side="sell",
                    limit_price=ask_price,
                    current_ts=current_ts,
                )
            )
        else:
            _log.info(
                "sell_suppressed_no_inventory",
                current_position=str(current_position),
            )

        _log.info(
            "market_making_signal_generated",
            mid_price=str(order_book.mid_price),
            twap=str(twap),
            bid_price=str(bid_price),
            ask_price=str(ask_price),
            market_spread_bps=str(market_spread_bps),
            our_spread_bps=str(self.config.spread_bps),
            current_position=str(current_position),
            intents_generated=len(intents),
        )

        self.last_quote_context = QuoteContext(
            twap=twap,
            current_mid=order_book.mid_price,
            bid_quote=bid_price,
            ask_quote=ask_price,
            snapshot_count=snapshot_count,
        )

        return intents

    def _calculate_twap(
        self,
        session: Session,
        current_ts: datetime,
        current_mid: Decimal,
    ) -> tuple[Decimal, int]:
        cutoff = current_ts - timedelta(hours=self.config.twap_lookback_hours)
        snapshot_count, avg_mid = session.execute(
            select(
                func.count(OrderBookSnapshot.id),
                func.avg(OrderBookSnapshot.mid_price),
            ).where(
                OrderBookSnapshot.exchange == self.config.exchange,
                OrderBookSnapshot.symbol == self.config.symbol,
                OrderBookSnapshot.mid_price.is_not(None),
                OrderBookSnapshot.event_ts > cutoff,
            )
        ).one()

        count = int(snapshot_count or 0)
        if count < 2 or avg_mid is None:
            _log.info("twap_insufficient_data", snapshot_count=count)
            return current_mid, count

        return Decimal(str(avg_mid)), count

    @staticmethod
    def _round_price(price: Decimal) -> Decimal:
        return price.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    def _build_intent(self, side: str, limit_price: Decimal, current_ts: datetime) -> OrderIntent:
        intent = OrderIntent(
            strategy_signal_id=None,
            portfolio_id=None,
            mode="paper",
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            side=side,
            order_type="limit",
            time_in_force=None,
            quantity=self.config.quote_size,
            limit_price=limit_price,
            reduce_only=False,
            post_only=False,
            client_order_id=None,
            status="pending",
            created_ts=current_ts if current_ts.tzinfo is not None else current_ts.replace(tzinfo=timezone.utc),
        )
        # Non-persistent helper attributes retained for strategy-layer assertions/telemetry.
        intent.account_name = self.config.account_name
        intent.intent_type = "limit"
        intent.strategy_name = "market_making"
        return intent
