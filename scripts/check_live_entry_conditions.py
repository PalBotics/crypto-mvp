from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from core.config.settings import get_settings
from core.db.session import SessionLocal
from core.models.funding_rate_snapshot import FundingRateSnapshot
from core.models.market_tick import MarketTick
from core.models.pnl_snapshot import PnLSnapshot
from core.models.position_snapshot import PositionSnapshot
from core.risk.risk_engine import is_kill_switch_active

try:
    from scripts.validate_live_feeds import run_validation
except ModuleNotFoundError:
    from validate_live_feeds import run_validation


@dataclass
class EntryCheckState:
    live_mode: bool
    kill_switch_inactive: bool
    funding_apr: Decimal
    funding_threshold_apr: Decimal
    kraken_age_seconds: int | None
    coinbase_age_seconds: int | None
    positions_flat: bool
    credentials_set: bool
    feeds_match: bool
    daily_loss_usd: Decimal
    live_dn_contract_qty: int


@dataclass
class ConditionResult:
    name: str
    passed: bool
    detail: str


def evaluate_conditions(state: EntryCheckState) -> list[ConditionResult]:
    results: list[ConditionResult] = []

    results.append(
        ConditionResult(
            name="Live mode enabled",
            passed=state.live_mode,
            detail="LIVE_MODE=True" if state.live_mode else "LIVE_MODE=False",
        )
    )
    results.append(
        ConditionResult(
            name="Kill switch inactive",
            passed=state.kill_switch_inactive,
            detail="Kill switch inactive" if state.kill_switch_inactive else "Kill switch active",
        )
    )

    funding_pass = state.funding_apr >= state.funding_threshold_apr
    results.append(
        ConditionResult(
            name="Funding APR threshold",
            passed=funding_pass,
            detail=f"Funding APR: {state.funding_apr:.2f}% (need >= {state.funding_threshold_apr:.2f}%)",
        )
    )

    kraken_fresh = state.kraken_age_seconds is not None and state.kraken_age_seconds < 60
    coinbase_fresh = state.coinbase_age_seconds is not None and state.coinbase_age_seconds < 60
    results.append(
        ConditionResult(
            name="Feed freshness",
            passed=kraken_fresh and coinbase_fresh,
            detail=f"Kraken {state.kraken_age_seconds}s, Coinbase {state.coinbase_age_seconds}s",
        )
    )

    results.append(
        ConditionResult(
            name="Positions flat",
            passed=state.positions_flat,
            detail="paper_dn/live_dn flat" if state.positions_flat else "open positions present",
        )
    )

    results.append(
        ConditionResult(
            name="Live credentials configured",
            passed=state.credentials_set,
            detail="credentials present" if state.credentials_set else "credentials missing",
        )
    )

    results.append(
        ConditionResult(
            name="Price feeds agree",
            passed=state.feeds_match,
            detail="validate_live_feeds.py PASS" if state.feeds_match else "validate_live_feeds.py FAIL",
        )
    )

    results.append(
        ConditionResult(
            name="Daily loss",
            passed=state.daily_loss_usd == Decimal("0"),
            detail=f"Daily loss: ${state.daily_loss_usd:.2f}",
        )
    )

    results.append(
        ConditionResult(
            name="Contract qty",
            passed=state.live_dn_contract_qty >= 2,
            detail=f"Contract qty: {state.live_dn_contract_qty}",
        )
    )

    return results


def gather_state() -> EntryCheckState:
    settings = get_settings()

    with SessionLocal() as session:
        kill_switch_inactive = not is_kill_switch_active(session)

        latest_funding = (
            session.execute(
                select(FundingRateSnapshot)
                .where(FundingRateSnapshot.exchange == settings.dn_perp_exchange)
                .where(FundingRateSnapshot.symbol == settings.dn_perp_symbol)
                .order_by(FundingRateSnapshot.event_ts.desc())
            )
            .scalars()
            .first()
        )
        if latest_funding is None:
            funding_apr = Decimal("-999")
        else:
            rate = Decimal(str(latest_funding.funding_rate))
            interval_hours = int(latest_funding.funding_interval_hours or 1)
            periods_per_year = Decimal(str((24 / interval_hours) * 365))
            funding_apr = rate * periods_per_year * Decimal("100")

        now = datetime.now(timezone.utc)
        kraken_tick = (
            session.execute(
                select(MarketTick)
                .where(MarketTick.exchange == settings.dn_spot_exchange)
                .where(MarketTick.symbol == settings.dn_spot_symbol)
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )
        coinbase_tick = (
            session.execute(
                select(MarketTick)
                .where(MarketTick.exchange == settings.dn_perp_exchange)
                .where(MarketTick.symbol == settings.dn_perp_symbol)
                .order_by(MarketTick.event_ts.desc())
            )
            .scalars()
            .first()
        )

        kraken_age_seconds = None
        if kraken_tick is not None:
            kraken_age_seconds = max(0, int((now - kraken_tick.event_ts).total_seconds()))

        coinbase_age_seconds = None
        if coinbase_tick is not None:
            coinbase_age_seconds = max(0, int((now - coinbase_tick.event_ts).total_seconds()))

        open_positions = (
            session.execute(
                select(PositionSnapshot)
                .where(PositionSnapshot.account_name.in_(["paper_dn", "live_dn"]))
                .where(PositionSnapshot.quantity > 0)
            )
            .scalars()
            .all()
        )
        positions_flat = len(open_positions) == 0

        day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        realized_today = Decimal(
            str(
                session.execute(
                    select(func.coalesce(func.sum(PnLSnapshot.realized_pnl), 0))
                    .where(PnLSnapshot.strategy_name == "live_dn")
                    .where(PnLSnapshot.snapshot_ts >= day_start)
                ).scalar_one()
            )
        )
        daily_loss_usd = abs(realized_today) if realized_today < 0 else Decimal("0")

    credentials_set = all(
        [
            bool((settings.live_kraken_api_key or "").strip()),
            bool((settings.live_kraken_api_secret or "").strip()),
            bool((settings.live_coinbase_api_key or "").strip()),
            bool((settings.live_coinbase_private_key or "").strip()),
        ]
    )

    feeds_match = run_validation()

    return EntryCheckState(
        live_mode=bool(settings.live_mode),
        kill_switch_inactive=kill_switch_inactive,
        funding_apr=funding_apr,
        funding_threshold_apr=Decimal(str(settings.dn_funding_entry_threshold_apr)),
        kraken_age_seconds=kraken_age_seconds,
        coinbase_age_seconds=coinbase_age_seconds,
        positions_flat=positions_flat,
        credentials_set=credentials_set,
        feeds_match=feeds_match,
        daily_loss_usd=daily_loss_usd,
        live_dn_contract_qty=int(settings.live_dn_contract_qty),
    )


def main() -> int:
    state = gather_state()
    results = evaluate_conditions(state)

    print("=" * 48)
    print("LIVE ENTRY CONDITIONS CHECK")
    print("=" * 48)

    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {result.detail}")

    failures = [r for r in results if not r.passed]

    print("=" * 48)
    if failures:
        print(f"Overall: NOT READY ({len(failures)} condition failed)")
        print(f"Reason: {failures[0].detail}")
        print("=" * 48)
        return 1

    print("Overall: READY")
    print("=" * 48)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
