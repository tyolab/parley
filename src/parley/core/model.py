from dataclasses import dataclass


@dataclass
class Room:
    name: str
    title: str | None = None
    created_by: str | None = None
    status: str = "open"


@dataclass
class Membership:
    room: str
    agent_id: str
    last_read_id: int = 0


@dataclass
class Message:
    id: int
    room: str
    frm: str
    body: str
    at: str  # ISO-8601 UTC
    kind: str = "say"

    def as_wire(self) -> dict:
        return {"from": self.frm, "body": self.body, "at": self.at, "kind": self.kind}
