import asyncpg

from parley.core.store import self_filter  # noqa: F401 - reserved for poll/peek in Task 2
from parley.core.tokens import new_token

_SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
  id text PRIMARY KEY, title text, created_by text,
  created_at timestamptz NOT NULL DEFAULT now(),
  status text NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS conv_members (
  conv_id text NOT NULL, agent_id text NOT NULL,
  joined_at timestamptz NOT NULL DEFAULT now(),
  last_read_id bigint NOT NULL DEFAULT 0,
  delivery_read_id bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (conv_id, agent_id)
);
CREATE TABLE IF NOT EXISTS conv_messages (
  id bigserial PRIMARY KEY, conv_id text NOT NULL,
  from_agent text NOT NULL, body text NOT NULL,
  kind text NOT NULL DEFAULT 'say',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS conv_messages_conv_idx ON conv_messages (conv_id, id);
CREATE TABLE IF NOT EXISTS agent_seq (
  box text NOT NULL, name text NOT NULL DEFAULT '',
  n bigint NOT NULL DEFAULT 0, PRIMARY KEY (box, name)
);
CREATE TABLE IF NOT EXISTS agent_tokens (
  token text PRIMARY KEY, box text NOT NULL, label text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_tokens_box_idx ON agent_tokens (box);
"""


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


class PostgresStore:
    """Durable multi-writer Store on Postgres (asyncpg). Ported from orchestra's
    board.py: `say` serializes appends per conversation with an advisory lock so
    bigserial ids commit in assignment order (cursor-safe); poll advances the
    per-mode cursor under a per-member FOR UPDATE. All tables live in a dedicated
    schema (search_path) so Parley never collides with other tables in the DB."""

    def __init__(self, pool):
        self._pool = pool
        self.on_message = None

    @classmethod
    async def connect(cls, dsn, schema="parley"):
        if not schema.replace("_", "").isalnum():
            raise ValueError(f"invalid schema name: {schema!r}")

        pool = await asyncpg.create_pool(
            dsn, min_size=1, max_size=4, server_settings={"search_path": schema})
        async with pool.acquire() as c:
            await c.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            await c.execute(_SCHEMA_DDL)
        return cls(pool)

    async def close(self):
        await self._pool.close()

    async def create_room(self, name, creator, title=None):
        async with self._pool.acquire() as c:
            created = await c.fetchval(
                "INSERT INTO conversations(id,title,created_by) VALUES($1,$2,$3) "
                "ON CONFLICT (id) DO NOTHING RETURNING id", name, title, creator)
            await c.execute(
                "INSERT INTO conv_members(conv_id,agent_id) VALUES($1,$2) "
                "ON CONFLICT (conv_id,agent_id) DO NOTHING", name, creator)
        return {"created": created is not None, "conv": name}

    async def get_room(self, name):
        async with self._pool.acquire() as c:
            r = await c.fetchrow(
                "SELECT id,title,created_by,status FROM conversations WHERE id=$1", name)
        return dict(r) if r else None

    async def join(self, name, agent_id):
        async with self._pool.acquire() as c:
            if not await c.fetchval("SELECT 1 FROM conversations WHERE id=$1", name):
                return {"joined": False, "exists": False}
            await c.execute(
                "INSERT INTO conv_members(conv_id,agent_id) VALUES($1,$2) "
                "ON CONFLICT (conv_id,agent_id) DO NOTHING", name, agent_id)
        return {"joined": True, "exists": True}

    async def leave(self, name, agent_id):
        async with self._pool.acquire() as c:
            await c.execute(
                "DELETE FROM conv_members WHERE conv_id=$1 AND agent_id=$2", name, agent_id)
        return {"left": True}

    async def is_member(self, name, agent_id):
        async with self._pool.acquire() as c:
            return bool(await c.fetchval(
                "SELECT 1 FROM conv_members WHERE conv_id=$1 AND agent_id=$2", name, agent_id))

    async def members(self, name):
        async with self._pool.acquire() as c:
            rows = await c.fetch(
                "SELECT agent_id FROM conv_members WHERE conv_id=$1 ORDER BY agent_id", name)
        return [r["agent_id"] for r in rows]

    async def say(self, name, agent_id, body, kind="say"):
        async with self._pool.acquire() as c:
            if not await c.fetchval(
                    "SELECT 1 FROM conv_members WHERE conv_id=$1 AND agent_id=$2", name, agent_id):
                return {"ok": False, "reason": "not a member — join first"}
            async with c.transaction():
                await c.execute("SELECT pg_advisory_xact_lock(hashtext($1))", name)
                mid = await c.fetchval(
                    "INSERT INTO conv_messages(conv_id,from_agent,body,kind) "
                    "VALUES($1,$2,$3,$4) RETURNING id", name, agent_id, body, kind)
        if self.on_message:
            try:
                res = self.on_message(name, agent_id, mid)
                if hasattr(res, "__await__"):
                    await res
            except Exception:  # noqa: BLE001, S110 - nudge is best-effort
                pass
        return {"ok": True, "id": mid}

    async def next_agent_seq(self, box, slug):
        async with self._pool.acquire() as c:
            return await c.fetchval(
                "INSERT INTO agent_seq(box,name,n) VALUES($1,$2,1) "
                "ON CONFLICT (box,name) DO UPDATE SET n=agent_seq.n+1 RETURNING n", box, slug)

    async def mint_agent_token(self, box, label=None):
        token = new_token()
        async with self._pool.acquire() as c:
            await c.execute(
                "INSERT INTO agent_tokens(token,box,label) VALUES($1,$2,$3)", token, box, label)
        return token

    async def box_for_token(self, token):
        if not token:
            return None
        async with self._pool.acquire() as c:
            return await c.fetchval("SELECT box FROM agent_tokens WHERE token=$1", token)

    async def poll(self, agent_id, room=None, box=None, box_view=False):
        raise NotImplementedError("Task 2")

    async def peek(self, agent_id, room=None, box=None, box_view=False):
        raise NotImplementedError("Task 2")

    async def list_rooms(self, agent_id, box=None):
        raise NotImplementedError("Task 2")

    async def all_rooms(self):
        raise NotImplementedError("Task 2")

    async def box_rooms(self, box):
        raise NotImplementedError("Task 2")
