from core.config.settings import Settings, get_settings


def test_settings_load() -> None:
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.app_name == "crypto-mvp"
    assert settings.environment in {"development", "test", "production"}
    assert settings.run_mode in {"paper", "testnet", "live"}
    assert settings.db_host
    assert settings.db_name


def test_funding_settings_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.collect_funding is False
    assert settings.collect_funding_symbol == "BTCUSDT"


def test_funding_settings_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("COLLECT_FUNDING", "true")
    monkeypatch.setenv("COLLECT_FUNDING_SYMBOL", "ETHUSDT")

    settings = Settings(_env_file=None)

    assert settings.collect_funding is True
    assert settings.collect_funding_symbol == "ETHUSDT"