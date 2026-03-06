from apps.collector.collector import MarketDataCollector
from core.config.settings import get_settings


def test_collector_uses_settings() -> None:
    settings = get_settings()
    collector = MarketDataCollector(settings=settings)

    assert collector.symbol == settings.collect_symbol
    assert collector.interval_seconds == settings.collect_interval_seconds