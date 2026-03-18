from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

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
    bid_offset_bps: float = 120.0
    min_spread_bps: Decimal = Decimal("0.01")
    stale_book_seconds: int = 120
    twap_lookback_hours: int = 2
    ask_sg_near_bps: float = 30.0
    ask_sg_far_bps: float = 80.0
    twap_slope_mild_threshold: float = -5.0
    twap_slope_steep_threshold: float = -15.0
    twap_slope_rising_threshold: float = 5.0
    twap_slope_steep_rising_threshold: float = 15.0
    sg_concavity_threshold: float = 1.0
    unified_sizing_enabled: bool = False

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
        twap_slope_bps_per_min: float | None = None,
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
        bid_offset = Decimal(str(self.config.bid_offset_bps)) / Decimal("10000")
        bid_price = self._round_price(ask_price * (Decimal("1") - bid_offset))

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
        sell_quote_size = quote_size
        buy_multiplier = self._compute_unified_size_multiplier(
            side="buy",
            ask_price=ask_price,
            market_price=order_book.mid_price,
            twap_slope_bps_per_min=twap_slope_bps_per_min,
            concavity=concavity,
        )
        buy_quote_size = self._round_btc_size(quote_size * buy_multiplier)
        sell_multiplier = self._compute_unified_size_multiplier(
            side="sell",
            ask_price=ask_price,
            market_price=order_book.mid_price,
            twap_slope_bps_per_min=twap_slope_bps_per_min,
            concavity=concavity,
        )
        # Keep a resting sell quote present even when market is below ask.
        if sell_multiplier <= Decimal("0"):
            sell_quote_size = quote_size
        else:
            sell_quote_size = self._round_btc_size(quote_size * sell_multiplier)
            if sell_quote_size <= Decimal("0"):
                sell_quote_size = quote_size

        intents: list[OrderIntent] = []
        remaining_inventory = max_inventory - position_btc
        max_buy_size = self._floor_btc_size(remaining_inventory) if remaining_inventory > Decimal("0") else Decimal("0")
        if buy_quote_size > max_buy_size:
            buy_quote_size = max_buy_size

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
                if buy_multiplier == Decimal("0"):
                    _log.info(
                        "unified_buy_suppressed",
                        multiplier=str(buy_multiplier),
                        base_quote_size=str(quote_size),
                        buy_quote_size=str(buy_quote_size),
                        current_position=str(position_btc),
                        max_inventory=str(max_inventory),
                    )
                else:
                    _log.info(
                        "buy_suppressed_zero_size",
                        multiplier=str(buy_multiplier),
                        base_quote_size=str(quote_size),
                        buy_quote_size=str(buy_quote_size),
                        current_position=str(position_btc),
                        max_inventory=str(max_inventory),
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
                    "sell_suppressed",
                    reason="zero_position",
                    current_position_qty=str(current_position_qty),
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

    def _compute_unified_size_multiplier(
        self,
        side: str,
        ask_price: Decimal,
        market_price: Decimal,
        twap_slope_bps_per_min: float | None,
        concavity: float | None,
    ) -> Decimal:
        if not self.config.unified_sizing_enabled:
            return Decimal("1.0")

        if ask_price == Decimal("0"):
            return Decimal("1.0")

        if side == "buy":
            distance_bps = ((ask_price - market_price) / ask_price) * Decimal("10000")
        elif side == "sell":
            distance_bps = ((market_price - ask_price) / ask_price) * Decimal("10000")
        else:
            return Decimal("1.0")

        if distance_bps <= Decimal("0"):
            return Decimal("0.0")

        near = Decimal(str(self.config.ask_sg_near_bps))
        far = Decimal(str(self.config.ask_sg_far_bps))
        if distance_bps < near:
            distance_zone = "near"
        elif distance_bps < far:
            distance_zone = "mid"
        else:
            distance_zone = "far"

        slope_value = twap_slope_bps_per_min
        if slope_value is None:
            twap_slope_zone = "neutral"
        elif slope_value < self.config.twap_slope_steep_threshold:
            twap_slope_zone = "steep_falling"
        elif slope_value < self.config.twap_slope_mild_threshold:
            twap_slope_zone = "mild_falling"
        elif slope_value <= self.config.twap_slope_rising_threshold:
            twap_slope_zone = "neutral"
        elif slope_value <= self.config.twap_slope_steep_rising_threshold:
            twap_slope_zone = "mild_rising"
        else:
            twap_slope_zone = "steep_rising"

        if side == "buy":
            matrix: dict[tuple[str, str], Decimal] = {
                ("steep_falling", "near"): Decimal("0.10"),
                ("steep_falling", "mid"): Decimal("0.25"),
                ("steep_falling", "far"): Decimal("0.50"),
                ("mild_falling", "near"): Decimal("0.25"),
                ("mild_falling", "mid"): Decimal("0.50"),
                ("mild_falling", "far"): Decimal("0.75"),
                ("neutral", "near"): Decimal("0.50"),
                ("neutral", "mid"): Decimal("1.00"),
                ("neutral", "far"): Decimal("1.50"),
                ("mild_rising", "near"): Decimal("0.75"),
                ("mild_rising", "mid"): Decimal("1.25"),
                ("mild_rising", "far"): Decimal("1.50"),
                ("steep_rising", "near"): Decimal("0.75"),
                ("steep_rising", "mid"): Decimal("1.25"),
                ("steep_rising", "far"): Decimal("1.50"),
            }
        else:
            matrix = {
                ("steep_falling", "near"): Decimal("0.50"),
                ("steep_falling", "mid"): Decimal("1.25"),
                ("steep_falling", "far"): Decimal("1.50"),
                ("mild_falling", "near"): Decimal("0.25"),
                ("mild_falling", "mid"): Decimal("1.00"),
                ("mild_falling", "far"): Decimal("1.25"),
                ("neutral", "near"): Decimal("0.50"),
                ("neutral", "mid"): Decimal("1.00"),
                ("neutral", "far"): Decimal("1.50"),
                ("mild_rising", "near"): Decimal("0.25"),
                ("mild_rising", "mid"): Decimal("0.50"),
                ("mild_rising", "far"): Decimal("0.75"),
                ("steep_rising", "near"): Decimal("0.10"),
                ("steep_rising", "mid"): Decimal("0.25"),
                ("steep_rising", "far"): Decimal("0.50"),
            }
        base_multiplier = matrix[(twap_slope_zone, distance_zone)]

        if concavity is None:
            concavity_modifier = Decimal("1.00")
        elif concavity > self.config.sg_concavity_threshold:
            concavity_modifier = Decimal("1.25")
        elif concavity < -self.config.sg_concavity_threshold:
            concavity_modifier = Decimal("0.50")
        else:
            concavity_modifier = Decimal("1.00")

        final_multiplier = base_multiplier * concavity_modifier
        _log.info(
            "unified_sizing_applied",
            side=side,
            distance_bps=str(distance_bps.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
            distance_zone=distance_zone,
            twap_slope_bps_per_min=twap_slope_bps_per_min,
            twap_slope_zone=twap_slope_zone,
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

    @staticmethod
    def _floor_btc_size(size: Decimal) -> Decimal:
        return size.quantize(BTC_QUANT, rounding=ROUND_DOWN)

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
