"""Test doubles: counting LLM, controllable clock, engine factory."""

from __future__ import annotations

from typing import Any

from adapters.line import FakeLine
from adapters.llm import RuleExtractor
from adapters.models import MessageDelta
from adapters.places import FakePlaces
from config import Settings
from session.engine import SessionEngine
from store.memory import MemoryStore


class CountingLLM(RuleExtractor):
    """Offline rules + a call counter, to assert the caps work."""

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, text: str, *, mentioned: bool, context: dict[str, Any]) -> MessageDelta:
        self.calls += 1
        return self.extract_sync(text, mentioned=mentioned)


class Clock:
    def __init__(self, now: int = 1_800_000_000):
        self.now = now

    def __call__(self) -> int:
        return self.now


def make_engine(**overrides: Any) -> tuple[SessionEngine, FakeLine, CountingLLM, FakePlaces, Clock]:
    settings = Settings(**overrides)
    line = FakeLine(names={"A": "เอ", "B": "บี", "C": "ซี"})
    llm, places, clock = CountingLLM(), FakePlaces(), Clock()
    engine = SessionEngine(settings, MemoryStore(), line, llm, places, clock=clock)
    return engine, line, llm, places, clock
