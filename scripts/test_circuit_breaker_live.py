from __future__ import annotations

"""FOR TESTING ONLY - requires LIVE_MODE credentials."""

from core.config.settings import get_settings
from core.db.session import SessionLocal
from core.exchange.kraken_live import KrakenLiveAdapter
from core.risk.risk_engine import RiskEngine


def main() -> int:
    settings = get_settings()
    if not settings.live_mode:
        print("LIVE_MODE is disabled. Enable LIVE_MODE before running this test.")
        return 1

    if not settings.live_kraken_api_key or not settings.live_kraken_api_secret:
        print("LIVE Kraken credentials are required.")
        return 1

    with SessionLocal() as session:
        risk_engine = RiskEngine(account_name="live_dn", db=session)
        original_threshold = risk_engine.risk_max_consecutive_failures

        try:
            risk_engine.risk_max_consecutive_failures = max(2, original_threshold)
            threshold = risk_engine.risk_max_consecutive_failures

            print("Simulating consecutive Kraken failures with invalid credentials...")
            invalid_adapter = KrakenLiveAdapter(api_key="invalid", api_secret="invalid")
            for _ in range(threshold):
                try:
                    invalid_adapter.get_account_balance()
                except Exception:
                    risk_engine.record_exchange_failure("kraken")

            breaker_state = risk_engine.get_breaker_states(exchanges=["kraken"])[0]
            print(f"Breaker after failures: {breaker_state}")
            if breaker_state["state"] != "open":
                print("FAIL: expected breaker state=open after consecutive failures")
                return 1

            print("Restoring valid credentials and testing recovery...")
            valid_adapter = KrakenLiveAdapter(
                api_key=settings.live_kraken_api_key,
                api_secret=settings.live_kraken_api_secret,
            )
            if not valid_adapter.validate_credentials():
                print("FAIL: valid credential validation failed")
                return 1

            risk_engine.record_exchange_success("kraken")
            recovered_state = risk_engine.get_breaker_states(exchanges=["kraken"])[0]
            print(f"Breaker after recovery: {recovered_state}")
            if recovered_state["state"] != "closed":
                print("FAIL: expected breaker state=closed after success")
                return 1

            print("PASS: circuit breaker open->closed transition verified")
            return 0
        finally:
            risk_engine.risk_max_consecutive_failures = original_threshold


if __name__ == "__main__":
    raise SystemExit(main())
