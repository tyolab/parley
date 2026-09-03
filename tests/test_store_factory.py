from parley.stores.factory import is_pg_dsn


def test_detects_postgres_dsn():
    assert is_pg_dsn("postgres://u:p@h/db") is True
    assert is_pg_dsn("postgresql://u@h:5432/db") is True

def test_treats_paths_as_sqlite():
    assert is_pg_dsn("/home/x/.parley/parley.db") is False
    assert is_pg_dsn(":memory:") is False
    assert is_pg_dsn(None) is False
