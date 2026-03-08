from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

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


class MarketMakingStrategy:
    def __init__(self, config: MarketMakingConfig) -> None:
        self.config = config

    def evaluate(
        self,
        session: Session,
        order_book: OrderBookSnapshot,
        current_position: Decimal,
        current_ts: datetime,
    ) -> list[OrderIntent]:
        del session  # Caller owns transaction/session lifecycle; evaluate is pure signal generation.

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

        half_spread = self.config.spread_bps / Decimal("2") / Decimal("10000")
        bid_price = self._round_price(order_book.mid_price * (Decimal("1") - half_spread))
        ask_price = self._round_price(order_book.mid_price * (Decimal("1") + half_spread))

        intents: list[OrderIntent] = []

        if current_position < self.config.max_inventory:
            intents.append(
                self._build_intent(
                    side="buy",
                    limit_price=bid_price,
                    current_ts=current_ts,
                )
            )

        if current_position > -self.config.max_inventory:
            intents.append(
                self._build_intent(
                    side="sell",
                    limit_price=ask_price,
                    current_ts=current_ts,
                )
            )

        _log.info(
            "market_making_signal_generated",
            mid_price=str(order_book.mid_price),
            bid_price=str(bid_price),
            ask_price=str(ask_price),
            market_spread_bps=str(market_spread_bps),
            our_spread_bps=str(self.config.spread_bps),
            current_position=str(current_position),
            intents_generated=len(intents),
        )

        return intents

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
