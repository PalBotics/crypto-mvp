from core.exchange.mock_adapter import MockExchangeAdapter


def test_mock_ticker():
    adapter = MockExchangeAdapter()

    ticker = adapter.fetch_ticker("BTC-USD")

    assert ticker["bid"] < ticker["ask"]
    assert ticker["symbol"] == "BTC-USD"