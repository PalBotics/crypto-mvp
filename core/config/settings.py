"""Application settings and configuration.

Uses Pydantic Settings for environment-based configuration with .env file support.
All settings can be overridden via environment variables.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables and .env file.

    Configuration is case-insensitive and loads from .env if present.
    All fields have sensible defaults for local development.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="crypto-mvp", alias="APP_NAME")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    run_mode: str = Field(default="paper", alias="RUN_MODE")
    service_name: str = Field(default="collector", alias="SERVICE_NAME")

    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="crypto_mvp", alias="DB_NAME")
    db_user: str = Field(default="postgres", alias="DB_USER")
    db_password: str = Field(default="postgres", alias="DB_PASSWORD")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    collect_exchange: str = Field(default="mock", alias="COLLECT_EXCHANGE")
    collect_symbol: str = Field(default="BTC-USD", alias="COLLECT_SYMBOL")
    collect_interval_seconds: int = Field(default=5, alias="COLLECT_INTERVAL_SECONDS")
    collect_funding: bool = Field(default=False, alias="COLLECT_FUNDING")
    collect_funding_symbol: str = Field(
        default="BTCUSDT", alias="COLLECT_FUNDING_SYMBOL"
    )

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()