import asyncio
import datetime

import aiosqlite

from parley.core.store import self_filter
from parley.core.tokens import new_token

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
CREATE TABLE IF NOT EXISTS agent_tokens (
  token      TEXT PRIMARY KEY,
  box        TEXT NOT NULL,
  label      TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS agent_tokens_box_idx ON agent_tokens (box);
"""


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


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
            except Exception:  # noqa: BLE001, S110 - nudge is best-effort
                pass
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

    async def mint_agent_token(self, box, label=None):
        token = new_token()
        async with self._wlock:
            await self._db.execute(
                "INSERT INTO agent_tokens(token,box,label,created_at) VALUES(?,?,?,?)",
                (token, box, label, _now()))
            await self._db.commit()
        return token

    async def box_for_token(self, token):
        if not token:
            return None
        cur = await self._db.execute(
            "SELECT box FROM agent_tokens WHERE token=?", (token,))
        r = await cur.fetchone()
        return r["box"] if r else None

    async def _collect(self, agent_id, room, box, advance, box_view):
        pred, _extra = self_filter(agent_id, box, "from_agent", ":agent", ":box",
                                   box_view=box_view)
        out = []
        async with self._wlock:
            cur = await self._db.execute(
                "SELECT conv_id,last_read_id FROM conv_members "
                "WHERE agent_id=? AND (? IS NULL OR conv_id=?) ORDER BY conv_id",
                (agent_id, room, room))
            members = await cur.fetchall()
            for m in members:
                q = ("SELECT id,from_agent,body,created_at FROM conv_messages "
                     f"WHERE conv_id=:conv AND id>:last AND {pred} ORDER BY id")
                mc = await self._db.execute(q, {"conv": m["conv_id"], "last": m["last_read_id"],
                                                "agent": agent_id, "box": box})
                rows = await mc.fetchall()
                if not rows:
                    continue
                if advance:
                    await self._db.execute(
                        "UPDATE conv_members SET last_read_id=? WHERE conv_id=? AND agent_id=?",
                        (rows[-1]["id"], m["conv_id"], agent_id))
                out.append({"conv": m["conv_id"], "messages": [
                    {"from": r["from_agent"], "body": r["body"], "at": r["created_at"]}
                    for r in rows]})
            if advance:
                await self._db.commit()
        return out

    async def poll(self, agent_id, room=None, box=None, box_view=False):
        return await self._collect(agent_id, room, box, advance=True, box_view=box_view)

    async def peek(self, agent_id, room=None, box=None, box_view=False):
        return await self._collect(agent_id, room, box, advance=False, box_view=box_view)

    async def list_rooms(self, agent_id, box=None):
        pred, _extra = self_filter(agent_id, box, "x.from_agent", ":agent", ":box")
        q = ("SELECT m.conv_id AS conv, "
             "(SELECT count(*) FROM conv_messages x WHERE x.conv_id=m.conv_id "
             f" AND x.id>m.last_read_id AND {pred}) AS unread "
             "FROM conv_members m WHERE m.agent_id=:agent ORDER BY m.conv_id")
        cur = await self._db.execute(q, {"agent": agent_id, "box": box})
        return [{"conv": r["conv"], "unread": int(r["unread"])} for r in await cur.fetchall()]

    async def all_rooms(self):
        q = ("SELECT cm.conv_id AS conv, count(*) AS members, "
             "(SELECT count(*) FROM conv_messages x WHERE x.conv_id=cm.conv_id) AS messages, "
             "co.title AS title "
             "FROM conv_members cm LEFT JOIN conversations co ON co.id=cm.conv_id "
             "GROUP BY cm.conv_id, co.title ORDER BY cm.conv_id")
        cur = await self._db.execute(q)
        return [{"conv": r["conv"], "members": int(r["members"]),
                 "messages": int(r["messages"]), "title": r["title"]}
                for r in await cur.fetchall()]

    async def box_rooms(self, box):
        cur = await self._db.execute(
            "SELECT DISTINCT conv_id FROM conv_members "
            "WHERE agent_id=? OR agent_id LIKE ? || '-%' ORDER BY conv_id", (box, box))
        return [r["conv_id"] for r in await cur.fetchall()]
