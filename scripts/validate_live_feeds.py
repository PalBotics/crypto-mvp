from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from core.db.session import SessionLocal
from core.exchange.coinbase_advanced import CoinbaseAdvancedAdapter
from core.exchange.kraken_live import KrakenLiveAdapter
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick

THRESHOLD_PCT = Decimal("0.50")


@dataclass
class ValidationResult:
    live_price: Decimal
    db_price: Decimal
    deviation_pct: Decimal
    passed: bool


def compute_deviation_pct(live_price: Decimal, db_price: Decimal) -> Decimal:
    if db_price == 0:
        return Decimal("100")
    return (abs(live_price - db_price) / db_price) * Decimal("100")


def validate_price_tolerance(
    live_price: Decimal,
    db_price: Decimal,
    threshold_pct: Decimal = THRESHOLD_PCT,
) -> ValidationResult:
    deviation_pct = compute_deviation_pct(live_price=live_price, db_price=db_price)
    passed = deviation_pct <= threshold_pct
    return ValidationResult(
        live_price=live_price,
        db_price=db_price,
        deviation_pct=deviation_pct,
        passed=passed,
    )


def _fmt_usd(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def _fmt_pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _funding_apr(funding_rate: Decimal, interval_hours: int) -> Decimal:
    periods_per_year = Decimal(str((24 / interval_hours) * 365))
    return funding_rate * periods_per_year * Decimal("100")


def run_validation() -> bool:
    kraken_live = KrakenLiveAdapter(api_key="", api_secret="")
    coinbase_adapter = CoinbaseAdvancedAdapter(api_key="", private_key="")

    kraken_ticker = kraken_live.get_eth_ticker()
    coinbase_ticker = coinbase_adapter.get_public_ticker(product_id="ETH-PERP-INTX")
    coinbase_funding_live = coinbase_adapter.get_public_funding_rate(product_id="ETH-PERP-INTX")

    if coinbase_ticker is None or coinbase_funding_live is None:
        raise RuntimeError("Unable to fetch Coinbase public ETH-PERP data")

    with SessionLocal() as session:
        kraken_db_tick = (
            session.execute(
                select(MarketTick)
                .where(MarketTick.exchange == "kraken")
                .where(MarketTick.symbol == "ETHUSD")
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )
        if kraken_db_tick is None:
            raise RuntimeError("No kraken/ETHUSD tick found in DB")

        coinbase_db_tick = (
            session.execute(
                select(MarketTick)
                .where(MarketTick.exchange == "coinbase_advanced")
                .where(MarketTick.symbol == "ETH-PERP")
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )
        if coinbase_db_tick is None:
            raise RuntimeError("No coinbase_advanced/ETH-PERP tick found in DB")

        coinbase_db_funding = (
            session.execute(
                select(FundingRateSnapshot)
                .where(FundingRateSnapshot.exchange == "coinbase_advanced")
                .where(FundingRateSnapshot.symbol == "ETH-PERP")
                .order_by(FundingRateSnapshot.event_ts.desc())
            )
            .scalars()
            .first()
        )
        if coinbase_db_funding is None:
            raise RuntimeError("No coinbase_advanced/ETH-PERP funding snapshot found in DB")

    kraken_live_price = Decimal(str(kraken_ticker["last"]))
    kraken_db_price = Decimal(str(kraken_db_tick.mid_price))
    kraken_result = validate_price_tolerance(
        live_price=kraken_live_price,
        db_price=kraken_db_price,
    )

    coinbase_live_mark = Decimal(str(coinbase_ticker.get("mark") or coinbase_ticker["last"]))
    coinbase_db_mark = Decimal(str(coinbase_db_tick.mid_price))
    coinbase_result = validate_price_tolerance(
        live_price=coinbase_live_mark,
        db_price=coinbase_db_mark,
    )

    live_funding_rate = Decimal(str(coinbase_funding_live["funding_rate"]))
    live_funding_apr = _funding_apr(live_funding_rate, int(coinbase_funding_live["funding_interval_hours"]))

    db_funding_rate = Decimal(str(coinbase_db_funding.funding_rate))
    db_interval = int(coinbase_db_funding.funding_interval_hours or 1)
    db_funding_apr = _funding_apr(db_funding_rate, db_interval)

    funding_match = live_funding_apr.quantize(Decimal("0.01")) == db_funding_apr.quantize(Decimal("0.01"))
    overall_pass = kraken_result.passed and coinbase_result.passed and funding_match

    now_label = datetime.now(timezone.utc).isoformat()
    print("=" * 48)
    print(f"LIVE FEED VALIDATION  [{now_label}]")
    print("=" * 48)
    print("Kraken ETH/USD:")
    print(f"  Live price:   {_fmt_usd(kraken_result.live_price)}")
    print(f"  DB price:     {_fmt_usd(kraken_result.db_price)}")
    print(f"  Deviation:    {_fmt_pct(kraken_result.deviation_pct)}  [{'PASS' if kraken_result.passed else 'FAIL'}]")
    print(f"  Threshold:    {_fmt_pct(THRESHOLD_PCT)}")
    print("")
    print("Coinbase ETH-PERP:")
    print(f"  Live price:   {_fmt_usd(coinbase_result.live_price)}")
    print(f"  DB price:     {_fmt_usd(coinbase_result.db_price)}")
    print(f"  Deviation:    {_fmt_pct(coinbase_result.deviation_pct)}  [{'PASS' if coinbase_result.passed else 'FAIL'}]")
    print(f"  Threshold:    {_fmt_pct(THRESHOLD_PCT)}")
    print("")
    print("ETH Funding Rate:")
    print(f"  Live APR:     {_fmt_pct(live_funding_apr)}")
    print(f"  DB APR:       {_fmt_pct(db_funding_apr)}")
    print(f"  Match:        [{'YES' if funding_match else 'NO'}]")
    print("=" * 48)
    print(f"Overall: {'PASS' if overall_pass else 'FAIL'}")
    print("=" * 48)

    return overall_pass


def main() -> int:
    try:
        passed = run_validation()
    except Exception as exc:
        print("=" * 48)
        print("LIVE FEED VALIDATION FAILED")
        print("=" * 48)
        print(str(exc))
        print("=" * 48)
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
