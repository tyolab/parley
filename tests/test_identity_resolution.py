import pytest

from parley.gateway.identity import resolve_identity
from parley.stores.sqlite import SqliteStore


@pytest.fixture
async def store():
    s = await SqliteStore.connect(":memory:")
    yield s
    await s.close()


def hdr(**kw):
    return {k.replace("_", "-"): v for k, v in kw.items()}


async def test_agent_token_resolves_box_and_ignores_spoofed_box_header(store):
    tok = await store.mint_agent_token("work3")
    aid, box, is_admin = await resolve_identity(
        store, hdr(authorization=f"Bearer {tok}",
                   **{"x-parley-agent": "work3-agent#1", "x-parley-box": "elitebook2"}),
        admin_token="admin")
    assert (aid, box, is_admin) == ("work3-agent#1", "work3", False)

async def test_agent_token_handle_is_antispoof_composed(store):
    tok = await store.mint_agent_token("work3")
    aid, box, _ = await resolve_identity(
        store, hdr(authorization=f"Bearer {tok}", **{"x-parley-agent": "elitebook2-x"}),
        admin_token="admin")
    assert aid == "work3" and box == "work3"

async def test_admin_token_is_dev_mode_trusts_box_header(store):
    aid, box, is_admin = await resolve_identity(
        store, hdr(authorization="Bearer admin", **{"x-parley-box": "work3",
                   "x-parley-agent": "work3-agent#2"}), admin_token="admin")
    assert (aid, box, is_admin) == ("work3-agent#2", "work3", True)

async def test_no_admin_token_open_dev_trusts_headers(store):
    aid, box, is_admin = await resolve_identity(
        store, hdr(**{"x-parley-agent": "alice"}), admin_token=None)
    assert (aid, box, is_admin) == ("alice", None, True)

async def test_admin_token_set_but_bad_bearer_is_unauthenticated(store):
    aid, box, is_admin = await resolve_identity(
        store, hdr(authorization="Bearer wrong", **{"x-parley-agent": "alice"}),
        admin_token="admin")
    assert (aid, box, is_admin) == (None, None, False)
