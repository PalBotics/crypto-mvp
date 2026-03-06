from __future__ import annotations

from dataclasses import dataclass

from core.config.settings import Settings, get_settings
from core.db.session import check_database_connection
from core.utils.logging import configure_logging, get_logger


@dataclass(slots=True)
class AppContext:
    settings: Settings
    logger: object
    service_name: str


def bootstrap_app(*, service_name: str, check_db: bool = True) -> AppContext:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(service_name)

    logger.info(
        "service_starting",
        app_name=settings.app_name,
        service_name=service_name,
        environment=settings.environment,
        run_mode=settings.run_mode,
    )

    if check_db:
        db_ok = check_database_connection()
        logger.info("database_connection_check", success=db_ok)

    logger.info("service_started")

    return AppContext(
        settings=settings,
        logger=logger,
        service_name=service_name,
    )