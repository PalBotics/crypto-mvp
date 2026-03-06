from core.app.bootstrap import bootstrap_app


def test_bootstrap_app() -> None:
    ctx = bootstrap_app(service_name="test_service", check_db=False)

    assert ctx.service_name == "test_service"
    assert ctx.settings.app_name == "crypto-mvp"