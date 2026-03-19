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

    coinbase_api_key: str = Field(default="", alias="COINBASE_API_KEY")
    coinbase_private_key: str = Field(default="", alias="COINBASE_PRIVATE_KEY")

    dn_funding_entry_threshold_apr: float = Field(
        default=5.0,
        alias="DN_FUNDING_ENTRY_THRESHOLD_APR",
    )
    dn_funding_exit_threshold_apr: float = Field(
        default=2.0,
        alias="DN_FUNDING_EXIT_THRESHOLD_APR",
    )
    dn_contract_qty: int = Field(default=8, alias="DN_CONTRACT_QTY")
    dn_iteration_seconds: int = Field(default=60, alias="DN_ITERATION_SECONDS")
    dn_force_entry: bool = Field(default=False, alias="DN_FORCE_ENTRY")
    dn_block_on_ratio_violation: bool = Field(default=True, alias="DN_BLOCK_ON_RATIO_VIOLATION")
    dn_max_daily_loss_usd: float = Field(default=50.0, alias="DN_MAX_DAILY_LOSS_USD")
    dn_spot_exchange: str = Field(default="kraken", alias="DN_SPOT_EXCHANGE")
    dn_spot_symbol: str = Field(default="ETHUSD", alias="DN_SPOT_SYMBOL")
    dn_perp_exchange: str = Field(default="coinbase_advanced", alias="DN_PERP_EXCHANGE")
    dn_perp_symbol: str = Field(default="ETH-PERP", alias="DN_PERP_SYMBOL")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def coinbase_private_key_pem(self) -> str:
        return self.coinbase_private_key.replace("\\n", "\n")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()