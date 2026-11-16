"""Worker Lambda: SQS FIFO (one group = one ordered stream) -> SessionEngine."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from session.engine import SessionEngine

log = logging.getLogger()
log.setLevel(logging.INFO)

_engine: SessionEngine | None = None


def _get_engine() -> SessionEngine:
    global _engine
    if _engine is None:
        from handlers.ssm import settings_from_ssm
        from wiring import build_engine

        settings = settings_from_ssm(only=(
            "LINE_CHANNEL_ACCESS_TOKEN_PARAM", "GEMINI_API_KEY_PARAM", "GOOGLE_PLACES_API_KEY_PARAM"))
        for problem in settings.problems():
            log.warning("config: %s", problem)
        _engine = build_engine(settings)
    return _engine


def handler(sqs_event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    engine = _get_engine()
    failures = []
    for record in sqs_event.get("Records", []):
        try:
            asyncio.run(engine.handle(json.loads(record["body"])))
        except Exception as exc:
            log.error("event failed: %s", type(exc).__name__)  # no payload in logs
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
