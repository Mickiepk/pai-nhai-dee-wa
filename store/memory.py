"""In-memory store for local dev, the simulator and tests. Not persistent."""

from __future__ import annotations

import threading

from session.models import Session
from store.base import COUNTER_TTL_S, EVENT_TTL_S


class MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()  # local_server may be threaded
        self.events: dict[str, int] = {}  # event_id -> expires_at
        self.sessions: dict[str, str] = {}  # group_id -> session JSON (like DynamoDB)
        self.counters: dict[str, tuple[int, int]] = {}  # key -> (value, expires_at)

    def seen_event(self, event_id: str, now: int) -> bool:
        with self._lock:
            return self._seen_event(event_id, now)

    def _seen_event(self, event_id: str, now: int) -> bool:
        exp = self.events.get(event_id)
        if exp is not None and exp >= now:  # same boundary as DynamoDB (ttl < now = expired)
            return True
        self.events[event_id] = now + EVENT_TTL_S
        return False

    def forget_event(self, event_id: str) -> None:
        self.events.pop(event_id, None)

    def get_session(self, group_id: str) -> Session | None:
        raw = self.sessions.get(group_id)
        return Session.model_validate_json(raw) if raw else None

    def put_session(self, session: Session) -> None:
        self.sessions[session.group_id] = session.model_dump_json()

    def delete_session(self, group_id: str) -> None:
        self.sessions.pop(group_id, None)

    def incr(self, key: str, now: int) -> int:
        with self._lock:
            return self._incr(key, now)

    def _incr(self, key: str, now: int) -> int:
        value, exp = self.counters.get(key, (0, 0))
        if exp < now:
            value, exp = 0, now + COUNTER_TTL_S
        self.counters[key] = (value + 1, exp)  # TTL set on first increment (DynamoDB if_not_exists)
        return value + 1

    def dump(self) -> str:
        """Everything persisted, as one string (tests assert no raw chat text is stored)."""
        return "".join(self.sessions.values()) + "".join(self.events) + "".join(self.counters)
