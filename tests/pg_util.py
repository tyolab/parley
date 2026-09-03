import os

import asyncpg
import pytest

DSN = os.environ.get("PARLEY_PG_DSN", "postgresql://postgres:postgres@127.0.0.1:5432/parley")
SCHEMA = os.environ.get("PARLEY_PG_TEST_SCHEMA", "parley_test")


async def pg_available() -> bool:
    try:
        c = await asyncpg.connect(DSN, timeout=3)
        await c.close()
        return True
    except Exception:  # noqa: BLE001 - reachability probe, any failure means "no"
        return False


async def fresh_store():
    """A PostgresStore on an isolated, freshly-dropped schema. Skips the test if no
    Postgres is reachable. Caller must `await store.close()`."""
    if not await pg_available():
        pytest.skip(f"no Postgres at {DSN}")
    admin = await asyncpg.connect(DSN)
    await admin.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    await admin.close()
    from parley.stores.postgres import PostgresStore
    return await PostgresStore.connect(DSN, schema=SCHEMA)
