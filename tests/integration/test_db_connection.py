from core.db.session import check_database_connection


def test_database_connection() -> None:
    assert check_database_connection() is True