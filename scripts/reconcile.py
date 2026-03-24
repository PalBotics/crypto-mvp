from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from core.config.settings import get_settings
from core.db.session import SessionLocal
from core.exchange.kraken_live import KrakenLiveAdapter
from core.models.position_snapshot import PositionSnapshot


@dataclass(frozen=True)
class DbPosition:
    account_name: str
    exchange: str
    symbol: str
    quantity: Decimal
    side: str
    position_type: str
    contract_qty: int | None


def _to_decimal(value: object) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _normalize_side(side: str, quantity: Decimal) -> str:
    raw = (side or "").strip().lower()
    if raw in {"buy", "long"}:
        return "long"
    if raw in {"sell", "short"}:
        return "short"
    return "long" if quantity >= Decimal("0") else "short"


def _within_tolerance(db_qty: Decimal, ex_qty: Decimal, tolerance: Decimal = Decimal("0.01")) -> bool:
    db_abs = abs(db_qty)
    ex_abs = abs(ex_qty)
    if db_abs == Decimal("0"):
        return ex_abs == Decimal("0")
    return abs(db_abs - ex_abs) <= (db_abs * tolerance)


def _format_qty(value: Decimal, unit: str) -> str:
    return f"{value.quantize(Decimal('0.00000001'))} {unit}"


def _load_latest_positions() -> dict[tuple[str, str, str], DbPosition]:
    targets = {"paper_dn", "live_dn", "paper_mm"}
    out: dict[tuple[str, str, str], DbPosition] = {}

    with SessionLocal() as session:
        stmt = (
            select(PositionSnapshot)
            .where(PositionSnapshot.account_name.in_(targets))
            .where(PositionSnapshot.quantity > 0)
            .order_by(PositionSnapshot.snapshot_ts.desc())
        )
        rows = session.execute(stmt).scalars().all()

    for row in rows:
        key = (str(row.account_name), str(row.exchange), str(row.symbol))
        if key in out:
            continue
        qty = _to_decimal(row.quantity)
        out[key] = DbPosition(
            account_name=str(row.account_name),
            exchange=str(row.exchange),
            symbol=str(row.symbol),
            quantity=qty,
            side=_normalize_side(str(row.side), qty),
            position_type=str(row.position_type),
            contract_qty=row.contract_qty,
        )

    return out


def _extract_kraken_balances(balances: dict[str, Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    usd_keys = ["ZUSD", "USD"]
    eth_keys = ["XETH", "ETH", "ETH2"]
    btc_keys = ["XXBT", "XBT", "BTC"]

    def pick(keys: list[str]) -> Decimal:
        for key in keys:
            if key in balances:
                return balances[key]
        return Decimal("0")

    return pick(usd_keys), pick(eth_keys), pick(btc_keys)


def main() -> int:
    settings = get_settings()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db_positions = _load_latest_positions()

    live_dn_spot = db_positions.get(("live_dn", "kraken", "ETHUSD"))
    live_dn_perp = db_positions.get(("live_dn", "coinbase_advanced", "ETH-PERP"))
    paper_mm_spot = db_positions.get(("paper_mm", "kraken", "XBTUSD"))

    kraken_balances: dict[str, Decimal] | None = None
    usd_balance = Decimal("0")
    eth_balance = Decimal("0")

    mismatches = 0

    if settings.live_mode:
        try:
            adapter = KrakenLiveAdapter(
                api_key=settings.live_kraken_api_key,
                api_secret=settings.live_kraken_api_secret,
            )
            kraken_balances = adapter.get_account_balance()
            usd_balance, eth_balance, _ = _extract_kraken_balances(kraken_balances)
        except Exception as exc:  # noqa: BLE001
            print("LIVE_MODE=True but Kraken reconciliation failed")
            print(f"Error: {exc}")
            return 1
    else:
        print("LIVE_MODE=False: skipping exchange API reconciliation")

    print("=" * 48)
    print(f"POSITION RECONCILIATION  [{now}]")
    print("=" * 48)
    print("Account: live_dn")
    print("-" * 48)

    print("ETH spot (Kraken):")
    if live_dn_spot is None:
        print("  DB:       [missing position]")
        if settings.live_mode:
            print(f"  Exchange: {_format_qty(eth_balance, 'ETH')}  (USD balance: ${usd_balance.quantize(Decimal('0.01'))})")
            if abs(eth_balance) > Decimal("0.00000001"):
                print("  Match:    [MISMATCH]")
                mismatches += 1
            else:
                print("  Match:    [PASS]")
        else:
            print("  Exchange: [LIVE_MODE=False - skipped]")
            print("  Match:    [SKIPPED]")
    else:
        print(f"  DB:       {_format_qty(live_dn_spot.quantity, 'ETH')} {live_dn_spot.side}")
        if settings.live_mode:
            print(f"  Exchange: {_format_qty(eth_balance, 'ETH')}  (USD balance: ${usd_balance.quantize(Decimal('0.01'))})")
            side_ok = live_dn_spot.side == "long" and eth_balance > Decimal("0")
            qty_ok = _within_tolerance(live_dn_spot.quantity, eth_balance)
            if side_ok and qty_ok:
                print("  Match:    [PASS]")
            else:
                print("  Match:    [MISMATCH]")
                mismatches += 1
        else:
            print("  Exchange: [LIVE_MODE=False - skipped]")
            print("  Match:    [SKIPPED]")

    print("")
    print("ETH-PERP (Coinbase CFM):")
    if live_dn_perp is None:
        print("  DB:       [missing position]")
    else:
        contracts = live_dn_perp.contract_qty if live_dn_perp.contract_qty is not None else 0
        print(f"  DB:       {contracts} contracts {live_dn_perp.side}")
    print("  Exchange: [requires live CFM API - implement in Sprint 4]")
    print("  Match:    [SKIPPED - CFM position API not yet implemented]")

    print("-" * 48)
    print("Account: paper_mm")
    print("-" * 48)

    print("BTC spot (Kraken):")
    if paper_mm_spot is None:
        print("  DB:       [missing position]")
    else:
        print(f"  DB:       {_format_qty(paper_mm_spot.quantity, 'BTC')} {paper_mm_spot.side}")
    if settings.live_mode:
        print("  Exchange: [paper account - skipped]")
    else:
        print("  Exchange: [LIVE_MODE=False - skipped]")
    print("  Match:    [SKIPPED]")

    print("-" * 48)
    print(f"MISMATCHES: {mismatches}")
    overall = "PASS" if mismatches == 0 else "FAIL"
    print(f"Overall: {overall}")
    print("=" * 48)

    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
