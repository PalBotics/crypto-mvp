from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

from core.models.order_book_snapshot import OrderBookSnapshot
from core.strategy.market_making import MarketMakingConfig, MarketMakingStrategy


def _config() -> MarketMakingConfig:
    return MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )


def _order_book(*, spread_bps: Decimal = Decimal("8"), event_ts: datetime | None = None) -> OrderBookSnapshot:
    ts = event_ts or datetime.now(timezone.utc)
    mid = Decimal("60000")
    spread = mid * spread_bps / Decimal("10000")
    return OrderBookSnapshot(
        exchange="kraken",
        adapter_name="kraken_rest",
        symbol="XBTUSD",
        exchange_symbol="XXBTZUSD",
        bid_price_1=mid - spread / Decimal("2"),
        bid_size_1=Decimal("1"),
        ask_price_1=mid + spread / Decimal("2"),
        ask_size_1=Decimal("1"),
        bid_price_2=mid - Decimal("1"),
        bid_size_2=Decimal("1"),
        ask_price_2=mid + Decimal("1"),
        ask_size_2=Decimal("1"),
        bid_price_3=mid - Decimal("2"),
        bid_size_3=Decimal("1"),
        ask_price_3=mid + Decimal("2"),
        ask_size_3=Decimal("1"),
        spread=spread,
        spread_bps=spread_bps,
        mid_price=mid,
        event_ts=ts,
        ingested_ts=ts,
    )


def _session_with_twap(*, snapshot_count: int = 3, twap: Decimal = Decimal("60000")) -> Mock:
    session = Mock()
    session.execute.return_value.one.return_value = (snapshot_count, twap)
    return session


def test_generates_bid_and_ask_when_conditions_met() -> None:
    strategy = MarketMakingStrategy(_config())

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0.001"),
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 2
    bid = next(i for i in intents if i.side == "buy")
    ask = next(i for i in intents if i.side == "sell")
    assert bid.limit_price < Decimal(str(_order_book().mid_price)) < ask.limit_price
    assert isinstance(bid.limit_price, Decimal)
    assert isinstance(ask.limit_price, Decimal)


def test_suppresses_bid_at_max_long_inventory() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=config.max_inventory,
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "sell"


def test_suppresses_sell_when_no_inventory() -> None:
    strategy = MarketMakingStrategy(_config())

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "buy"


def test_suppresses_buy_when_at_max_inventory() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=config.max_inventory,
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "sell"


def test_suppresses_ask_at_max_short_inventory() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=-config.max_inventory,
        current_ts=datetime.now(timezone.utc),
    )

    assert len(intents) == 1
    assert intents[0].side == "buy"


def test_returns_empty_on_stale_book() -> None:
    strategy = MarketMakingStrategy(_config())
    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=180)

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(event_ts=stale_ts),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert intents == []


def test_returns_empty_when_spread_too_tight() -> None:
    strategy = MarketMakingStrategy(_config())

    intents = strategy.evaluate(
        session=Mock(),
        order_book=_order_book(spread_bps=Decimal("1")),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    assert intents == []


def test_bid_price_below_mid_ask_price_above_mid() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=book,
        current_position=Decimal("0.001"),
        current_ts=datetime.now(timezone.utc),
    )

    bid = next(i for i in intents if i.side == "buy")
    ask = next(i for i in intents if i.side == "sell")
    assert bid.limit_price < book.mid_price
    assert ask.limit_price > book.mid_price


def test_prices_rounded_to_one_decimal_place() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=book,
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    for intent in intents:
        text = format(intent.limit_price, "f")
        decimals = text.split(".")[1] if "." in text else ""
        assert len(decimals.rstrip("0")) <= 1


def test_intent_fields_are_correct() -> None:
    config = _config()
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0"),
        current_ts=datetime.now(timezone.utc),
    )

    for intent in intents:
        assert intent.intent_type == "limit"
        assert intent.quantity == config.quote_size
        assert intent.mode == "paper"
        assert intent.strategy_name == "market_making"
        assert intent.status == "pending"
        assert intent.reduce_only is False


def test_twap_insufficient_data_falls_back_to_current_mid() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()

    intents = strategy.evaluate(
        session=_session_with_twap(snapshot_count=1, twap=Decimal("59900")),
        order_book=book,
        current_position=Decimal("0.001"),
        current_ts=datetime.now(timezone.utc),
    )

    bid = next(i for i in intents if i.side == "buy")
    ask = next(i for i in intents if i.side == "sell")

    assert bid.limit_price == Decimal("59940.0")
    assert ask.limit_price == Decimal("60060.0")
    assert strategy.last_quote_context is not None
    assert strategy.last_quote_context.snapshot_count == 1
    assert strategy.last_quote_context.twap == book.mid_price


def test_bid_anchors_to_mid_when_mid_below_avg_entry() -> None:
    strategy = MarketMakingStrategy(_config())
    book = _order_book()
    book.mid_price = Decimal("70000")
    book.spread_bps = Decimal("10")

    with patch("core.strategy.market_making._log.info") as info_log:
        intents = strategy.evaluate(
            session=_session_with_twap(twap=Decimal("70500")),
            order_book=book,
            current_position=Decimal("0.001"),
            current_ts=datetime.now(timezone.utc),
            avg_entry_price=Decimal("71000"),
        )

    buy = next(i for i in intents if i.side == "buy")
    assert buy.limit_price == Decimal("69930.0")

    anchor_call = next(
        call for call in info_log.call_args_list
        if call.args and call.args[0] == "bid_anchor_mode_selected"
    )
    assert anchor_call.kwargs["bid_anchor_mode"] == "mid"
    assert anchor_call.kwargs["mid_price"] == "70000"
    assert anchor_call.kwargs["avg_entry_price"] == "71000"


def test_pct_sizing_applied_when_account_value_provided() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        quote_size_pct=Decimal("10"),
        max_inventory_pct=Decimal("50"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )
    strategy = MarketMakingStrategy(config)
    book = _order_book()

    with patch("core.strategy.market_making._log.info") as info_log:
        intents = strategy.evaluate(
            session=_session_with_twap(),
            order_book=book,
            current_position=Decimal("0.001"),
            current_ts=datetime.now(timezone.utc),
            account_value=Decimal("1200"),
        )

    buy = next(i for i in intents if i.side == "buy")
    assert buy.quantity == Decimal("0.00200000")
    assert any(
        call.args and call.args[0] == "pct_sizing_applied"
        for call in info_log.call_args_list
    )


def test_pct_sizing_preserves_eight_decimal_btc_precision() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        quote_size_pct=Decimal("10"),
        max_inventory_pct=Decimal("50"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )
    strategy = MarketMakingStrategy(config)
    book = _order_book()
    book.mid_price = Decimal("70037")

    with patch("core.strategy.market_making._log.info") as info_log:
        intents = strategy.evaluate(
            session=_session_with_twap(twap=Decimal("70037")),
            order_book=book,
            current_position=Decimal("0.01000000"),
            current_ts=datetime.now(timezone.utc),
            account_value=Decimal("1996.74"),
        )

    buy = next(i for i in intents if i.side == "buy")
    sell = next(i for i in intents if i.side == "sell")

    assert buy.quantity == Decimal("0.00285098")
    assert sell.quantity == Decimal("0.00285098")
    pct_sizing_call = next(
        call for call in info_log.call_args_list
        if call.args and call.args[0] == "pct_sizing_applied"
    )
    assert pct_sizing_call.kwargs["max_inventory"] == "0.01425489"
    assert pct_sizing_call.kwargs["quote_size"] == "0.00285098"


def test_pct_sizing_does_not_suppress_buy_when_max_inventory_exceeds_position() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        quote_size_pct=Decimal("10"),
        max_inventory_pct=Decimal("50"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )
    strategy = MarketMakingStrategy(config)
    book = _order_book()
    book.mid_price = Decimal("70037")

    intents = strategy.evaluate(
        session=_session_with_twap(twap=Decimal("70037")),
        order_book=book,
        current_position=Decimal("0.01000000"),
        current_ts=datetime.now(timezone.utc),
        account_value=Decimal("1996.74"),
    )

    assert sorted(intent.side for intent in intents) == ["buy", "sell"]


def test_pct_sizing_falls_back_to_fixed_when_account_value_missing() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        quote_size_pct=Decimal("10"),
        max_inventory_pct=Decimal("50"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
    )
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0.02"),
        current_ts=datetime.now(timezone.utc),
        account_value=None,
    )

    assert len(intents) == 1
    assert intents[0].side == "sell"
    assert intents[0].quantity == Decimal("0.001")


def test_sg_sizing_disabled_returns_base_size() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        quote_size_pct=Decimal("10"),
        max_inventory_pct=Decimal("50"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
        sg_sizing_enabled=False,
    )
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0.001"),
        current_ts=datetime.now(timezone.utc),
        account_value=Decimal("1200"),
        sg_value=Decimal("60500"),
        slope=20.0,
        concavity=2.0,
    )

    buy = next(i for i in intents if i.side == "buy")
    assert buy.quantity == Decimal("0.00200000")


def test_sg_near_steep_suppresses_buy() -> None:
    config = MarketMakingConfig(
        exchange="kraken",
        symbol="XBTUSD",
        account_name="paper_mm",
        spread_bps=Decimal("20"),
        quote_size=Decimal("0.001"),
        max_inventory=Decimal("0.01"),
        min_spread_bps=Decimal("5"),
        stale_book_seconds=120,
        sg_sizing_enabled=True,
    )
    strategy = MarketMakingStrategy(config)

    intents = strategy.evaluate(
        session=_session_with_twap(),
        order_book=_order_book(),
        current_position=Decimal("0.001"),
        current_ts=datetime.now(timezone.utc),
        sg_value=Decimal("60020"),
        slope=-35.0,
        concavity=0.0,
    )

    assert all(intent.side != "buy" for intent in intents)
    assert len(intents) == 1
    assert intents[0].side == "sell"


def test_sg_far_rising_returns_150pct() -> None:
    config = MarketMakingConfig(sg_sizing_enabled=True)
    strategy = MarketMakingStrategy(config)

    multiplier = strategy._compute_sg_size_multiplier(
        mid_price=Decimal("60000"),
        sg_value=Decimal("60300"),
        slope=20.0,
        concavity=0.0,
    )

    assert multiplier == Decimal("1.50")


def test_sg_mid_flat_returns_50pct() -> None:
    config = MarketMakingConfig(sg_sizing_enabled=True)
    strategy = MarketMakingStrategy(config)

    multiplier = strategy._compute_sg_size_multiplier(
        mid_price=Decimal("60000"),
        sg_value=Decimal("60120"),
        slope=0.0,
        concavity=0.0,
    )

    assert multiplier == Decimal("0.50")


def test_sg_concavity_up_multiplies_125pct() -> None:
    config = MarketMakingConfig(sg_sizing_enabled=True)
    strategy = MarketMakingStrategy(config)

    multiplier = strategy._compute_sg_size_multiplier(
        mid_price=Decimal("60000"),
        sg_value=Decimal("60120"),
        slope=0.0,
        concavity=2.0,
    )

    assert multiplier == Decimal("0.6250")


def test_sg_concavity_down_multiplies_50pct() -> None:
    config = MarketMakingConfig(sg_sizing_enabled=True)
    strategy = MarketMakingStrategy(config)

    multiplier = strategy._compute_sg_size_multiplier(
        mid_price=Decimal("60000"),
        sg_value=Decimal("60120"),
        slope=0.0,
        concavity=-2.0,
    )

    assert multiplier == Decimal("0.2500")


def test_sg_none_values_falls_back_to_base() -> None:
    config = MarketMakingConfig(sg_sizing_enabled=True)
    strategy = MarketMakingStrategy(config)

    multiplier = strategy._compute_sg_size_multiplier(
        mid_price=Decimal("60000"),
        sg_value=None,
        slope=None,
        concavity=None,
    )

    assert multiplier == Decimal("1.0")
