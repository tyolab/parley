import asyncio
import datetime
import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id         TEXT PRIMARY KEY,
  title      TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS conv_members (
  conv_id      TEXT NOT NULL,
  agent_id     TEXT NOT NULL,
  joined_at    TEXT NOT NULL,
  last_read_id INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (conv_id, agent_id)
);
CREATE TABLE IF NOT EXISTS conv_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  conv_id    TEXT NOT NULL,
  from_agent TEXT NOT NULL,
  body       TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'say',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS conv_messages_conv_idx ON conv_messages (conv_id, id);
CREATE TABLE IF NOT EXISTS agent_seq (
  box  TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  n    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (box, name)
);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, db: aiosqlite.Connection):
        self._db = db
        self._wlock = asyncio.Lock()
        self.on_message = None  # optional async(conv, frm, mid) nudge hook (used by a later plan)

    @classmethod
    async def connect(cls, path: str = ":memory:") -> "SqliteStore":
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        await db.executescript(_SCHEMA)
        await db.commit()
        return cls(db)

    async def close(self) -> None:
        await self._db.close()

    async def create_room(self, name, creator, title=None):
        async with self._wlock:
            cur = await self._db.execute(
                "INSERT OR IGNORE INTO conversations(id,title,created_by,created_at) "
                "VALUES(?,?,?,?)", (name, title, creator, _now()))
            created = cur.rowcount > 0
            await self._db.execute(
                "INSERT OR IGNORE INTO conv_members(conv_id,agent_id,joined_at) VALUES(?,?,?)",
                (name, creator, _now()))
            await self._db.commit()
        return {"created": created, "conv": name}

    async def get_room(self, name):
        cur = await self._db.execute(
            "SELECT id,title,created_by,status FROM conversations WHERE id=?", (name,))
        r = await cur.fetchone()
        return dict(r) if r else None

    async def join(self, name, agent_id):
        cur = await self._db.execute("SELECT 1 FROM conversations WHERE id=?", (name,))
        if not await cur.fetchone():
            return {"joined": False, "exists": False}
        async with self._wlock:
            await self._db.execute(
                "INSERT OR IGNORE INTO conv_members(conv_id,agent_id,joined_at) VALUES(?,?,?)",
                (name, agent_id, _now()))
            await self._db.commit()
        return {"joined": True, "exists": True}

    async def leave(self, name, agent_id):
        async with self._wlock:
            await self._db.execute(
                "DELETE FROM conv_members WHERE conv_id=? AND agent_id=?", (name, agent_id))
            await self._db.commit()
        return {"left": True}

    async def is_member(self, name, agent_id):
        cur = await self._db.execute(
            "SELECT 1 FROM conv_members WHERE conv_id=? AND agent_id=?", (name, agent_id))
        return (await cur.fetchone()) is not None

    async def members(self, name):
        cur = await self._db.execute(
            "SELECT agent_id FROM conv_members WHERE conv_id=? ORDER BY agent_id", (name,))
        return [r["agent_id"] for r in await cur.fetchall()]

    async def say(self, name, agent_id, body, kind="say"):
        if not await self.is_member(name, agent_id):
            return {"ok": False, "reason": "not a member — join first"}
        async with self._wlock:
            cur = await self._db.execute(
                "INSERT INTO conv_messages(conv_id,from_agent,body,kind,created_at) "
                "VALUES(?,?,?,?,?)", (name, agent_id, body, kind, _now()))
            mid = cur.lastrowid
            await self._db.commit()
        if self.on_message:
            try:
                res = self.on_message(name, agent_id, mid)
                if hasattr(res, "__await__"):
                    await res
            except Exception:
                pass  # nudge is best-effort
        return {"ok": True, "id": mid}

    async def next_agent_seq(self, box, slug):
        async with self._wlock:
            await self._db.execute(
                "INSERT INTO agent_seq(box,name,n) VALUES(?,?,1) "
                "ON CONFLICT(box,name) DO UPDATE SET n=n+1", (box, slug))
            cur = await self._db.execute(
                "SELECT n FROM agent_seq WHERE box=? AND name=?", (box, slug))
            await self._db.commit()
            return (await cur.fetchone())["n"]

    async def poll(self, agent_id, room=None, box=None, box_view=False):
        raise NotImplementedError("Task 4")

    async def peek(self, agent_id, room=None, box=None, box_view=False):
        raise NotImplementedError("Task 4")

    async def list_rooms(self, agent_id, box=None):
        raise NotImplementedError("Task 5")

    async def all_rooms(self):
        raise NotImplementedError("Task 5")

    async def box_rooms(self, box):
        raise NotImplementedError("Task 5")
