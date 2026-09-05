import httpx

from parley.gateway.app import build_app
from parley.stores.sqlite import SqliteStore
from parley.transports.polling import PollingTransport


async def _client(*, join_code=None, admin_token=None, mcp_port=None):
    store = await SqliteStore.connect(":memory:")
    app = build_app(store, PollingTransport(), admin_token=admin_token,
                    join_code=join_code, mcp_port=mcp_port)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    return store, c


async def test_enroll_disabled_without_join_code():
    store, c = await _client(join_code=None)
    r = await c.post("/enroll", json={"box": "work3"},
                     headers={"Authorization": "Bearer whatever"})
    assert r.status_code == 403
    assert "enrollment disabled" in r.json()["detail"]
    await c.aclose(); await store.close()


async def test_enroll_bad_code_rejected():
    store, c = await _client(join_code="s3cret")
    r = await c.post("/enroll", json={"box": "work3"},
                     headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403
    assert r.json()["detail"] == "invalid join code"
    await c.aclose(); await store.close()


async def test_enroll_missing_code_rejected():
    store, c = await _client(join_code="s3cret")
    r = await c.post("/enroll", json={"box": "work3"})  # no Authorization header
    assert r.status_code == 403
    await c.aclose(); await store.close()


async def test_enroll_good_code_mints_working_token():
    store, c = await _client(join_code="s3cret", mcp_port=8891)
    r = await c.post("/enroll", json={"box": "work3"},
                     headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    body = r.json()
    tok = body["token"]
    assert body["box"] == "work3"
    assert body["mcp_port"] == 8891
    assert await store.box_for_token(tok) == "work3"
    # the minted token authenticates a real rooms + poll round-trip
    hdr = {"Authorization": f"Bearer {tok}", "X-Parley-Agent": "work3-agent#1"}
    cr = await c.post("/rooms", json={"name": "general"}, headers=hdr)
    assert cr.status_code == 200
    p = await c.get("/poll", headers=hdr)
    assert p.status_code == 200
    await c.aclose(); await store.close()


async def test_enroll_taken_box_conflicts():
    store, c = await _client(join_code="s3cret")
    ok = await c.post("/enroll", json={"box": "work3"},
                      headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    again = await c.post("/enroll", json={"box": "work3"},
                         headers={"Authorization": "Bearer s3cret"})
    assert again.status_code == 409
    assert "already enrolled" in again.json()["detail"]
    await c.aclose(); await store.close()


async def test_enroll_admin_minted_box_also_conflicts():
    # First-come claim covers boxes an admin already minted: self-serve can't
    # re-claim a box that already has any token.
    store, c = await _client(join_code="s3cret")
    await store.mint_agent_token("work3")
    r = await c.post("/enroll", json={"box": "work3"},
                     headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 409
    await c.aclose(); await store.close()


async def test_enroll_rejects_bad_box_name():
    store, c = await _client(join_code="s3cret")
    r = await c.post("/enroll", json={"box": "work3-agent#1"},
                     headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 400  # '#' rejected, same rule as admin mint
    await c.aclose(); await store.close()


async def test_enroll_requires_box():
    store, c = await _client(join_code="s3cret")
    r = await c.post("/enroll", json={}, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 400
    await c.aclose(); await store.close()


async def test_enroll_mcp_port_null_when_no_mcp():
    store, c = await _client(join_code="s3cret", mcp_port=None)
    r = await c.post("/enroll", json={"box": "work3"},
                     headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert r.json()["mcp_port"] is None
    await c.aclose(); await store.close()
