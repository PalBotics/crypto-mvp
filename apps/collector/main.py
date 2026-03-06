from apps.collector.collector import MarketDataCollector
from core.app import bootstrap_app


def main() -> None:
    ctx = bootstrap_app(service_name="collector", check_db=True)

    collector = MarketDataCollector(settings=ctx.settings, logger=ctx.logger)

    ctx.logger.info("collector_loop_starting")
    collector.run()


if __name__ == "__main__":
    main()