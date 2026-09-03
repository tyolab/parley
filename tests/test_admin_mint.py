import httpx

from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


async def _client(admin_token):
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport(), admin_token=admin_token)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return store, c


async def test_admin_can_mint_and_token_authenticates():
    store, c = await _client("adm")
    r = await c.post("/admin/agents", json={"box": "work3"},
                     headers={"Authorization": "Bearer adm"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert await store.box_for_token(tok) == "work3"
    p = await c.get("/poll", headers={"Authorization": f"Bearer {tok}",
                                      "X-Parley-Agent": "work3-agent#1"})
    assert p.status_code == 200
    await c.aclose(); await store.close()


async def test_non_admin_cannot_mint():
    store, c = await _client("adm")
    tok = await store.mint_agent_token("work3")  # normal agent token, not admin
    r = await c.post("/admin/agents", json={"box": "evil"},
                     headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403
    await c.aclose(); await store.close()

async def test_mint_requires_box():
    store, c = await _client("adm")
    r = await c.post("/admin/agents", json={}, headers={"Authorization": "Bearer adm"})
    assert r.status_code == 400
    await c.aclose(); await store.close()

async def test_mint_disabled_in_open_mode():
    store, c = await _client(None)  # no admin token = open dev
    r = await c.post("/admin/agents", json={"box": "work3"})
    assert r.status_code == 403
    await c.aclose(); await store.close()

async def test_mint_rejects_session_handle_shaped_box():
    store, c = await _client("adm")
    r = await c.post("/admin/agents", json={"box": "work3-agent#1"},
                     headers={"Authorization": "Bearer adm"})
    assert r.status_code == 400  # '#' rejected -> can't impersonate a session handle
    await c.aclose(); await store.close()

async def test_admin_without_handle_can_mint_but_not_act_as_null_identity():
    # An admin token with no X-Parley-Agent may mint (agent-agnostic), but must NOT
    # be able to run a room op as a null identity — room routes require a real agent.
    store, c = await _client("adm")
    ok = await c.post("/admin/agents", json={"box": "work3"},
                      headers={"Authorization": "Bearer adm"})
    assert ok.status_code == 200
    r = await c.post("/rooms", json={"name": "r"}, headers={"Authorization": "Bearer adm"})
    assert r.status_code == 400  # no agent identity
    await c.aclose(); await store.close()
