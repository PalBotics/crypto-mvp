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
BTC_QUANT = Decimal("0.00000001")


@dataclass(frozen=True)
class MarketMakingConfig:
    exchange: str = "kraken"
    symbol: str = "XBTUSD"
    account_name: str = "paper_mm"
    spread_bps: Decimal = Decimal("20")
    quote_size: Decimal = Decimal("0.001")
    max_inventory: Decimal = Decimal("0.01")
    quote_size_pct: Decimal | None = None
    max_inventory_pct: Decimal | None = None
    min_profit_bps: Decimal = Decimal("10")
    mm_fee_bps: float = 25.0
    mm_target_profit_bps: float = 20.0
    min_spread_bps: Decimal = Decimal("0.01")
    stale_book_seconds: int = 120
    twap_lookback_hours: int = 2
    sg_slope_steep_threshold: float = -30.0
    sg_slope_rising_threshold: float = 15.0
    sg_distance_near_bps: float = 10.0
    sg_distance_far_bps: float = 40.0
    sg_concavity_threshold: float = 1.0
    sg_sizing_enabled: bool = False

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
        twap: Decimal | None = None,
        account_value: Decimal | None = None,
        avg_entry_price: Decimal | None = None,
        allowed_sides: set[str] | None = None,
        sg_value: Decimal | None = None,
        slope: float | None = None,
        concavity: float | None = None,
    ) -> list[OrderIntent]:
        self.last_quote_context = None
        quoteable_sides = (
            {"buy", "sell"}
            if allowed_sides is None
            else {side.strip().lower() for side in allowed_sides}
        )

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

        calculated_twap, snapshot_count = self._calculate_twap(
            session=session,
            current_ts=current_ts,
            current_mid=order_book.mid_price,
        )
        twap_vs_mid_bps = Decimal("0")
        if order_book.mid_price != Decimal("0"):
            twap_vs_mid_bps = ((calculated_twap - order_book.mid_price) / order_book.mid_price) * Decimal("10000")
        _log.info(
            "twap_calculated",
            twap=str(calculated_twap),
            current_mid=str(order_book.mid_price),
            twap_lookback_hours=self.config.twap_lookback_hours,
            snapshot_count=snapshot_count,
            twap_vs_mid_bps=str(twap_vs_mid_bps.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        )

        half_spread = self.config.spread_bps / Decimal("2") / Decimal("10000")
        buy_spread = self.config.spread_bps / Decimal("10000")
        buy_reference_price = twap if twap is not None else order_book.mid_price
        bid_price = self._round_price(buy_reference_price * (Decimal("1") - buy_spread))
        total_markup = (
            Decimal(str((2 * self.config.mm_fee_bps) + self.config.mm_target_profit_bps))
            / Decimal("10000")
        )
        ask_reference = (
            avg_entry_price
            if avg_entry_price is not None and avg_entry_price > Decimal("0")
            else (twap if twap is not None else calculated_twap)
        )
        ask_price = self._round_price(ask_reference * (Decimal("1") + total_markup))

        quote_size = self.config.quote_size
        max_inventory = self.config.max_inventory
        position_btc = self._round_btc_size(current_position)
        pct_sizing_used = False

        if account_value is not None and order_book.mid_price not in (None, Decimal("0")):
            btc_price = order_book.mid_price
            if self.config.quote_size_pct is not None:
                quote_size = self._round_btc_size(
                    (account_value * self.config.quote_size_pct / Decimal("100")) / btc_price
                )
                pct_sizing_used = True

            if self.config.max_inventory_pct is not None:
                max_inventory = self._round_btc_size(
                    (account_value * self.config.max_inventory_pct / Decimal("100")) / btc_price
                )
                pct_sizing_used = True

            if pct_sizing_used:
                _log.info(
                    "pct_sizing_applied",
                    quote_size=str(quote_size),
                    max_inventory=str(max_inventory),
                    account_value=str(account_value),
                    btc_price=str(btc_price),
                )

        buy_quote_size = quote_size
        buy_multiplier = Decimal("1.0")
        sell_quote_size = quote_size
        sell_multiplier = Decimal("1.0")
        if self.config.sg_sizing_enabled:
            buy_multiplier = self._compute_sg_size_multiplier(
                side="buy",
                mid_price=order_book.mid_price,
                sg_value=sg_value,
                slope=slope,
                concavity=concavity,
            )
            buy_quote_size = self._round_btc_size(quote_size * buy_multiplier)
            sell_multiplier = self._compute_sg_size_multiplier(
                side="sell",
                mid_price=ask_price,
                sg_value=sg_value,
                slope=slope,
                concavity=concavity,
            )
            sell_quote_size = self._round_btc_size(quote_size * sell_multiplier)

        intents: list[OrderIntent] = []

        if "buy" in quoteable_sides and position_btc < max_inventory:
            if buy_quote_size > Decimal("0"):
                intents.append(
                    self._build_intent(
                        side="buy",
                        limit_price=bid_price,
                        current_ts=current_ts,
                        quantity=buy_quote_size,
                    )
                )
            else:
                _log.info(
                    "sg_buy_suppressed",
                    multiplier=str(buy_multiplier),
                    base_quote_size=str(quote_size),
                    buy_quote_size=str(buy_quote_size),
                )
        elif "buy" in quoteable_sides:
            _log.info(
                "buy_suppressed_max_inventory",
                current_position=str(position_btc),
                max_inventory=str(max_inventory),
            )

        current_position_qty = position_btc if position_btc > Decimal("0") else Decimal("0")
        if "sell" in quoteable_sides:
            if current_position_qty <= Decimal("0"):
                _log.info(
                    "sg_sell_suppressed",
                    reason="zero_position",
                    current_position_qty=str(current_position_qty),
                )
            elif sell_quote_size <= Decimal("0"):
                _log.info(
                    "sg_sell_suppressed",
                    reason="zero_multiplier",
                    multiplier=str(sell_multiplier),
                    base_quote_size=str(quote_size),
                    sell_quote_size=str(sell_quote_size),
                )
            else:
                uncapped_sell_size = sell_quote_size
                sell_quote_size = min(sell_quote_size, current_position_qty)
                if sell_quote_size < uncapped_sell_size:
                    _log.info(
                        "sg_sell_capped",
                        uncapped_sell_size=str(uncapped_sell_size),
                        capped_sell_size=str(sell_quote_size),
                        current_position_qty=str(current_position_qty),
                    )
                intents.append(
                    self._build_intent(
                        side="sell",
                        limit_price=ask_price,
                        current_ts=current_ts,
                        quantity=sell_quote_size,
                    )
                )

        _log.info(
            "market_making_signal_generated",
            mid_price=str(order_book.mid_price),
            twap=str(calculated_twap),
            bid_price=str(bid_price),
            ask_price=str(ask_price),
            market_spread_bps=str(market_spread_bps),
            our_spread_bps=str(self.config.spread_bps),
            current_position=str(position_btc),
            intents_generated=len(intents),
        )

        self.last_quote_context = QuoteContext(
            twap=calculated_twap,
            current_mid=order_book.mid_price,
            bid_quote=bid_price,
            ask_quote=ask_price,
            snapshot_count=snapshot_count,
        )

        return intents

    def _compute_sg_size_multiplier(
        self,
        side: str,
        mid_price: Decimal,
        sg_value: Decimal | None,
        slope: float | None,
        concavity: float | None,
    ) -> Decimal:
        """Returns a SG-driven size multiplier for buy or sell side."""
        if not self.config.sg_sizing_enabled:
            return Decimal("1.0")

        if sg_value is None or slope is None or concavity is None or sg_value == Decimal("0"):
            return Decimal("1.0")

        if side == "buy":
            distance_bps = ((sg_value - mid_price) / sg_value) * Decimal("10000")
        elif side == "sell":
            distance_bps = ((mid_price - sg_value) / sg_value) * Decimal("10000")
        else:
            return Decimal("1.0")

        if distance_bps < Decimal("0"):
            distance_bps = Decimal("0")

        if slope < self.config.sg_slope_steep_threshold:
            slope_zone = "steep"
        elif slope > self.config.sg_slope_rising_threshold:
            slope_zone = "rising"
        else:
            slope_zone = "flat"

        near = Decimal(str(self.config.sg_distance_near_bps))
        far = Decimal(str(self.config.sg_distance_far_bps))
        if distance_bps < near:
            distance_zone = "near"
        elif distance_bps <= far:
            distance_zone = "mid"
        else:
            distance_zone = "far"

        if side == "buy":
            matrix: dict[tuple[str, str], Decimal] = {
                ("near", "steep"): Decimal("0.0"),
                ("near", "flat"): Decimal("0.10"),
                ("near", "rising"): Decimal("0.25"),
                ("mid", "steep"): Decimal("0.10"),
                ("mid", "flat"): Decimal("0.50"),
                ("mid", "rising"): Decimal("0.75"),
                ("far", "steep"): Decimal("0.25"),
                ("far", "flat"): Decimal("1.00"),
                ("far", "rising"): Decimal("1.50"),
            }
        else:
            matrix = {
                ("near", "steep"): Decimal("0.25"),
                ("near", "flat"): Decimal("0.10"),
                ("near", "rising"): Decimal("0.0"),
                ("mid", "steep"): Decimal("0.75"),
                ("mid", "flat"): Decimal("0.50"),
                ("mid", "rising"): Decimal("0.10"),
                ("far", "steep"): Decimal("1.50"),
                ("far", "flat"): Decimal("1.00"),
                ("far", "rising"): Decimal("0.25"),
            }
        base_multiplier = matrix[(distance_zone, slope_zone)]

        if concavity > self.config.sg_concavity_threshold:
            concavity_modifier = Decimal("1.25")
        elif concavity < -self.config.sg_concavity_threshold:
            concavity_modifier = Decimal("0.50")
        else:
            concavity_modifier = Decimal("1.00")

        final_multiplier = base_multiplier * concavity_modifier
        _log.info(
            "sg_sizing_applied",
            side=side,
            slope=slope,
            concavity=concavity,
            distance_bps=str(distance_bps.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            slope_zone=slope_zone,
            distance_zone=distance_zone,
            base_multiplier=str(base_multiplier),
            concavity_modifier=str(concavity_modifier),
            final_multiplier=str(final_multiplier),
        )

        return final_multiplier

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

    @staticmethod
    def _round_btc_size(size: Decimal) -> Decimal:
        return size.quantize(BTC_QUANT, rounding=ROUND_HALF_UP)

    def _build_intent(
        self,
        side: str,
        limit_price: Decimal,
        current_ts: datetime,
        quantity: Decimal,
    ) -> OrderIntent:
        intent = OrderIntent(
            strategy_signal_id=None,
            portfolio_id=None,
            mode="paper",
            exchange=self.config.exchange,
            symbol=self.config.symbol,
            side=side,
            order_type="limit",
            time_in_force=None,
            quantity=quantity,
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
