def is_pg_dsn(location) -> bool:
    return bool(location) and str(location).startswith(("postgres://", "postgresql://"))


async def make_store(location, schema="parley"):
    """Open the right Store for a location: a postgres:// DSN -> PostgresStore,
    anything else -> SqliteStore at that filesystem path (or ':memory:')."""
    if is_pg_dsn(location):
        from parley.stores.postgres import PostgresStore
        return await PostgresStore.connect(location, schema=schema)
    from parley.stores.sqlite import SqliteStore
    return await SqliteStore.connect(location or ":memory:")
