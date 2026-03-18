import os

from apps.collector.collector_loop import CollectorLoop
from apps.collector.kraken_rest import CollectorConfig, KrakenRestAdapter
from core.app import bootstrap_app
from core.config.settings import get_settings
from core.db.session import SessionLocal
from core.exchange.coinbase_advanced import CoinbaseAdvancedAdapter


def main() -> None:
    ctx = bootstrap_app(service_name="collector", check_db=True)
    settings = get_settings()
    config = CollectorConfig(
        spot_exchange=os.environ.get("COLLECT_SPOT_EXCHANGE", "kraken"),
        perp_exchange=os.environ.get("COLLECT_PERP_EXCHANGE", "kraken_futures"),
        spot_symbol=os.environ.get("COLLECT_SPOT_SYMBOL", "XBTUSD"),
        perp_symbol=os.environ.get("COLLECT_PERP_SYMBOL", "XBTUSD"),
        spot_exchange_symbol=os.environ.get("COLLECT_SPOT_EXCHANGE_SYMBOL", "XXBTZUSD"),
        perp_exchange_symbol=os.environ.get("COLLECT_PERP_EXCHANGE_SYMBOL", "PF_XBTUSD"),
        adapter_name=os.environ.get("COLLECT_ADAPTER_NAME", "kraken_rest"),
        poll_interval_seconds=int(os.environ.get("COLLECT_INTERVAL_SECONDS", "60")),
        spot_base_url=os.environ.get("COLLECT_SPOT_BASE_URL", "https://api.kraken.com"),
        futures_base_url=os.environ.get(
            "COLLECT_FUTURES_BASE_URL", "https://futures.kraken.com"
        ),
        request_timeout_seconds=int(
            os.environ.get("COLLECT_REQUEST_TIMEOUT_SECONDS", "10")
        ),
    )

    adapter = KrakenRestAdapter(config)
    coinbase_adapter = CoinbaseAdvancedAdapter(
        api_key=settings.coinbase_api_key,
        private_key=settings.coinbase_private_key_pem,
        timeout_seconds=config.request_timeout_seconds,
    )

    collector_loop = CollectorLoop(
        config=config,
        adapter=adapter,
        coinbase_adapter=coinbase_adapter,
        session_factory=SessionLocal,
    )

    ctx.logger.info(
        "collector_loop_starting",
        spot_exchange=config.spot_exchange,
        perp_exchange=config.perp_exchange,
        spot_symbol=config.spot_symbol,
        perp_symbol=config.perp_symbol,
        coinbase_perp_symbol="ETH-PERP",
        coinbase_enabled=coinbase_adapter.is_enabled,
        poll_interval_seconds=config.poll_interval_seconds,
    )
    collector_loop.run()


if __name__ == "__main__":
    main()