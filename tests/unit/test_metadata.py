from core.db.base import Base
import core.models  # noqa: F401


def test_metadata_contains_expected_tables() -> None:
    expected_tables = {
        "market_ticks",
        "funding_rate_snapshots",
        "system_events",
        "strategy_signals",
        "order_intents",
        "order_records",
        "fill_records",
        "position_snapshots",
        "pnl_snapshots",
        "risk_events",
    }

    actual_tables = set(Base.metadata.tables.keys())

    assert expected_tables.issubset(actual_tables)
    