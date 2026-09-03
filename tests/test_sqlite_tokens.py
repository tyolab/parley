import pytest
from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


async def test_mint_returns_distinct_tokens(store):
    t1 = await store.mint_agent_token("work3")
    t2 = await store.mint_agent_token("work3")
    assert t1 and t2 and t1 != t2  # two agents on one box get distinct tokens

async def test_box_for_token_roundtrip(store):
    t = await store.mint_agent_token("elitebook2", label="ci")
    assert await store.box_for_token(t) == "elitebook2"

async def test_box_for_unknown_token_is_none(store):
    assert await store.box_for_token("nope") is None
    assert await store.box_for_token("") is None
