"""Postgres store for the LOCAL environment (psycopg v3). Same contract as DynamoStore.

TTL semantics mirror DynamoDB: every row has `expires_at` (epoch seconds). Expired rows are
ignored by the idempotency check and purged lazily (every PURGE_EVERY writes) or explicitly via
purge_expired(now). Like DynamoDB, get_session does not hide an expired-but-not-yet-purged
session; the engine checks Session.is_expired itself.

Connections are per-thread (autocommit), so concurrent webhook threads never share a cursor.
"""

from __future__ import annotations

import threading
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from session.models import Session
from store.base import COUNTER_TTL_S, EVENT_TTL_S

PURGE_EVERY = 200
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class PostgresStore:
    def __init__(self, dsn: str, *, auto_migrate: bool = True):
        self._dsn = dsn
        self._local = threading.local()
        self._writes = 0
        if auto_migrate:
            self.migrate()

    # -- plumbing ---------------------------------------------------------
    def _conn(self) -> psycopg.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed:
            conn = psycopg.connect(self._dsn, autocommit=True)
            self._local.conn = conn
        return conn

    def migrate(self) -> None:
        """Idempotent: CREATE ... IF NOT EXISTS. Advisory lock stops two starters racing."""
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with psycopg.connect(self._dsn, autocommit=False) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(727274)")
            conn.execute(sql)

    def reset(self) -> None:
        """Test helper: empty all tables."""
        self._conn().execute("TRUNCATE pnd_events, pnd_sessions, pnd_counters")

    def dump(self) -> str:
        """Everything persisted, as one string (tests assert no raw chat text is stored)."""
        c = self._conn()
        parts = [r[0] for r in c.execute("SELECT data::text FROM pnd_sessions")]
        parts += [r[0] for r in c.execute("SELECT event_id FROM pnd_events")]
        parts += [r[0] for r in c.execute("SELECT key FROM pnd_counters")]
        return "".join(parts)

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()

    def _maybe_purge(self, now: int) -> None:
        self._writes += 1
        if self._writes % PURGE_EVERY == 0:
            self.purge_expired(now)

    def purge_expired(self, now: int) -> int:
        """Delete expired rows (what DynamoDB TTL does in the background). Returns rows removed."""
        total = 0
        for table in ("pnd_events", "pnd_sessions", "pnd_counters"):
            total += self._conn().execute(
                f"DELETE FROM {table} WHERE expires_at < %s", (now,)  # noqa: S608 (fixed names)
            ).rowcount
        return total

    # -- Store protocol ---------------------------------------------------
    def seen_event(self, event_id: str, now: int) -> bool:
        # Insert, or take over an expired row. Returns a row only if WE claimed it.
        row = self._conn().execute(
            "INSERT INTO pnd_events (event_id, expires_at) VALUES (%s, %s) "
            "ON CONFLICT (event_id) DO UPDATE SET expires_at = EXCLUDED.expires_at "
            "WHERE pnd_events.expires_at < %s RETURNING 1",
            (event_id, now + EVENT_TTL_S, now),
        ).fetchone()
        self._maybe_purge(now)
        return row is None

    def forget_event(self, event_id: str) -> None:
        self._conn().execute("DELETE FROM pnd_events WHERE event_id = %s", (event_id,))

    def get_session(self, group_id: str) -> Session | None:
        row = self._conn().execute(
            "SELECT data FROM pnd_sessions WHERE group_id = %s", (group_id,)
        ).fetchone()
        return Session.model_validate(row[0]) if row else None

    def put_session(self, session: Session) -> None:
        self._conn().execute(
            "INSERT INTO pnd_sessions (group_id, data, expires_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (group_id) DO UPDATE SET data = EXCLUDED.data, "
            "expires_at = EXCLUDED.expires_at",
            (session.group_id, Jsonb(session.model_dump(mode="json")), session.expires_at),
        )

    def delete_session(self, group_id: str) -> None:
        self._conn().execute("DELETE FROM pnd_sessions WHERE group_id = %s", (group_id,))

    def incr(self, key: str, now: int) -> int:
        # Atomic. Expired counter restarts at 1 (DynamoDB: row would already be TTL-deleted).
        row = self._conn().execute(
            "INSERT INTO pnd_counters (key, value, expires_at) VALUES (%s, 1, %s) "
            "ON CONFLICT (key) DO UPDATE SET "
            "value = CASE WHEN pnd_counters.expires_at < %s THEN 1 ELSE pnd_counters.value + 1 END, "
            "expires_at = CASE WHEN pnd_counters.expires_at < %s THEN EXCLUDED.expires_at "
            "ELSE pnd_counters.expires_at END RETURNING value",
            (key, now + COUNTER_TTL_S, now, now),
        ).fetchone()
        self._maybe_purge(now)
        assert row is not None
        return int(row[0])
