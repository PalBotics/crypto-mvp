from __future__ import annotations

from decimal import Decimal

from core.config.settings import get_settings
from core.exchange.kraken_live import KrakenLiveAdapter


def _redact_key(api_key: str) -> str:
    key = (api_key or "").strip()
    if not key:
        return "[redacted]"
    return f"{key[:8]}...[redacted]"


def _money(value: Decimal) -> str:
    return f"${value.quantize(Decimal('0.01'))}"


def _qty(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.00000000'))}"


def _pick_balance(balances: dict[str, Decimal], keys: list[str]) -> Decimal:
    for key in keys:
        if key in balances:
            return balances[key]
    return Decimal("0")


def main() -> int:
    settings = get_settings()

    print("=" * 48)
    print("KRAKEN LIVE CREDENTIAL TEST")
    print("=" * 48)

    if not settings.live_mode:
        print("Result:      SKIPPED")
        print("Warning:     LIVE_MODE=False")
        print("Action:      Set LIVE_MODE=True in .env to run this test")
        print("=" * 48)
        return 0

    if not settings.live_kraken_api_key.strip() or not settings.live_kraken_api_secret.strip():
        print("Result:      FAILED")
        print("Error:       LIVE_KRAKEN_API_KEY or LIVE_KRAKEN_API_SECRET is empty")
        print("Check:       Set both credentials in .env")
        print("=" * 48)
        return 1

    print(f"API key:     {_redact_key(settings.live_kraken_api_key)}")
    print("Endpoint:    POST /0/private/Balance")
    print("-" * 48)

    try:
        adapter = KrakenLiveAdapter(
            api_key=settings.live_kraken_api_key,
            api_secret=settings.live_kraken_api_secret,
        )
        balances = adapter.get_account_balance()

        usd = _pick_balance(balances, ["ZUSD", "USD"])
        eth = _pick_balance(balances, ["XETH", "ETH", "ETH2"])
        btc = _pick_balance(balances, ["XXBT", "XBT", "BTC"])

        print("Result:      SUCCESS")
        print("Balances:")
        print(f"  USD:       {_money(usd)}")
        print(f"  ETH:       {_qty(eth)}")
        print(f"  BTC:       {_qty(btc)}")

        non_zero = []
        for asset, amount in sorted(balances.items()):
            if amount != Decimal("0") and asset not in {"ZUSD", "USD", "XETH", "ETH", "ETH2", "XXBT", "XBT", "BTC"}:
                non_zero.append((asset, amount))

        if non_zero:
            print("  (other non-zero balances)")
            for asset, amount in non_zero:
                print(f"    {asset}: {_qty(amount)}")
        else:
            print("  (other non-zero balances: none)")

        print("=" * 48)
        print("Credentials: VALID")
        print("=" * 48)
        return 0

    except Exception as exc:  # noqa: BLE001
        print("=" * 48)
        print("Result:      FAILED")
        print(f"Error:       {exc}")
        print("Check:       API key has Query Funds permission")
        print("=" * 48)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
