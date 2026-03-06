from core.config.settings import get_settings


def test_settings_load() -> None:
    settings = get_settings()

    assert settings.app_name == "crypto-mvp"
    assert settings.environment in {"development", "test", "production"}
    assert settings.run_mode in {"paper", "testnet", "live"}
    assert settings.db_host
    assert settings.db_name