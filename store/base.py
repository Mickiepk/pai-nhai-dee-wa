"""Storage interface. Two implementations: memory (local/tests) and DynamoDB (AWS)."""

from __future__ import annotations

from typing import Protocol

from session.models import Session

EVENT_TTL_S = 24 * 3600
COUNTER_TTL_S = 2 * 24 * 3600


class Store(Protocol):
    """Persistence interface: processed-event ids, one active session per group, and daily counters."""

    def seen_event(self, event_id: str, now: int) -> bool:
        """Mark a webhookEventId as processed. Returns True if it was ALREADY seen."""
        ...

    def forget_event(self, event_id: str) -> None:
        """Undo seen_event when processing failed, so the SQS retry is not skipped."""
        ...

    def get_session(self, group_id: str) -> Session | None:
        """The group's active session, or None."""
        ...
    def put_session(self, session: Session) -> None:
        """Create or replace the group's active session."""
        ...
    def delete_session(self, group_id: str) -> None:
        """Delete the group's session (end of session or the bot left the group)."""
        ...

    def incr(self, key: str, now: int) -> int:
        """Atomically increment a daily counter (e.g. QUOTA#GROUP#g#20261116). Returns new value."""
        ...
