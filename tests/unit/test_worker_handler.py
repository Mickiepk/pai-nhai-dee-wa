"""handlers/worker.py: SQS batch handling, partial batch failure, retry and DLQ semantics.

No network, no AWS. The SQS redelivery / redrive policy is simulated by `redrive()` below; what
AWS itself does (visibility timeout, real DLQ move) is only provable on AWS (docs/ENVIRONMENTS.md).
These tests are sync on purpose: the handler calls asyncio.run().
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

import handlers.worker as worker
from scripts.events import postback_event, text_event
from tests.fakes import make_engine

MAX_RECEIVE = 3  # template.yaml EventQueue RedrivePolicy.maxReceiveCount


def record(ev: dict[str, Any] | str, mid: str) -> dict[str, str]:
    return {"messageId": mid, "body": ev if isinstance(ev, str) else json.dumps(ev, ensure_ascii=False)}


def batch(*records: dict[str, str]) -> dict[str, Any]:
    return {"Records": list(records)}


class ScriptedEngine:
    """Stands in for SessionEngine: records calls, raises for chosen event ids."""

    def __init__(self, fail_ids: set[str] | None = None):
        self.fail_ids = fail_ids or set()
        self.seen: list[str] = []

    async def handle(self, event: dict[str, Any]) -> None:
        self.seen.append(event["webhookEventId"])
        if event["webhookEventId"] in self.fail_ids:
            raise RuntimeError("boom: secret chat text must not leak")


@pytest.fixture
def scripted(monkeypatch):
    def install(fail_ids: set[str] | None = None) -> ScriptedEngine:
        eng = ScriptedEngine(fail_ids)
        monkeypatch.setattr(worker, "_engine", eng)
        return eng

    return install


def ev(eid: str) -> dict[str, Any]:
    e = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    e["webhookEventId"] = eid
    return e


# ---------------------------------------------------------------- batch shape
def test_empty_batch_and_missing_records_key(scripted):
    scripted()
    assert worker.handler({"Records": []}, None) == {"batchItemFailures": []}
    assert worker.handler({}, None) == {"batchItemFailures": []}


def test_all_success_reports_no_failures(scripted):
    eng = scripted()
    out = worker.handler(batch(record(ev("e1"), "m1"), record(ev("e2"), "m2")), None)
    assert out == {"batchItemFailures": []}
    assert eng.seen == ["e1", "e2"]


def test_partial_batch_failure_reports_only_failed_message_ids(scripted):
    eng = scripted({"e2"})
    out = worker.handler(batch(record(ev("e1"), "m1"), record(ev("e2"), "m2"), record(ev("e3"), "m3")), None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "m2"}]}
    assert eng.seen == ["e1", "e2", "e3"]  # a failure does not stop the rest of the batch


def test_all_fail_reports_all_in_order(scripted):
    scripted({"e1", "e2"})
    out = worker.handler(batch(record(ev("e1"), "m1"), record(ev("e2"), "m2")), None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "m1"}, {"itemIdentifier": "m2"}]}


def test_malformed_body_is_a_failure_not_a_crash(scripted):
    eng = scripted()
    out = worker.handler(batch(record("{not json", "bad"), record(ev("e1"), "ok")), None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    assert eng.seen == ["e1"]


def test_record_without_body_is_a_failure(scripted):
    scripted()
    out = worker.handler({"Records": [{"messageId": "nobody"}]}, None)
    assert out == {"batchItemFailures": [{"itemIdentifier": "nobody"}]}


def test_failure_log_has_exception_type_only_never_payload(scripted, caplog):
    scripted({"e1"})
    secret_text = "ลับสุดยอด-เบอร์โทร-0812345678"
    e = text_event("G", "A", f"@bot {secret_text}")
    e["webhookEventId"] = "e1"
    with caplog.at_level(logging.INFO):
        worker.handler(batch(record(e, "m1")), None)
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged
    assert secret_text not in logged and "boom" not in logged


# ---------------------------------------------------------------- real engine: retry semantics
class FlakyLine:
    """FakeLine whose first N replies raise (e.g. LINE 5xx / expired token)."""

    def __init__(self, inner, fail_first: int):
        self.inner, self.left = inner, fail_first
        self.attempts = 0

    async def reply(self, token, messages):
        self.attempts += 1
        if self.left > 0:
            self.left -= 1
            raise ConnectionError("LINE down")
        await self.inner.reply(token, messages)

    async def member_name(self, gid, uid):
        return await self.inner.member_name(gid, uid)


def test_failed_event_is_retried_and_processed_exactly_once(monkeypatch):
    engine, line, *_ = make_engine()
    engine.line = FlakyLine(line, fail_first=1)
    monkeypatch.setattr(worker, "_engine", engine)
    e = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    rec = batch(record(e, "m1"))

    first = worker.handler(rec, None)
    assert first == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert line.replies == []
    # forget_event ran: the SQS retry must NOT be dropped as a duplicate
    second = worker.handler(rec, None)
    assert second == {"batchItemFailures": []}
    assert len(line.replies) == 1
    # a later duplicate delivery of the same event is ignored (idempotent)
    third = worker.handler(rec, None)
    assert third == {"batchItemFailures": []}
    assert len(line.replies) == 1


def test_duplicate_delivery_in_same_batch_runs_once(monkeypatch):
    engine, line, *_ = make_engine()
    monkeypatch.setattr(worker, "_engine", engine)
    e = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    out = worker.handler(batch(record(e, "m1"), record(e, "m2")), None)
    assert out == {"batchItemFailures": []}
    assert len(line.replies) == 1


def test_kill_switch_acks_silently(monkeypatch):
    engine, line, *_ = make_engine(bot_enabled=False)
    monkeypatch.setattr(worker, "_engine", engine)
    out = worker.handler(batch(record(text_event("G", "A", "@bot กินไรดีแถวอารีย์"), "m1")), None)
    assert out == {"batchItemFailures": []}  # acked, not retried: the queue drains while the bot is off
    assert line.replies == []


def test_postback_without_session_replies_expired_not_error(monkeypatch):
    engine, line, *_ = make_engine()
    monkeypatch.setattr(worker, "_engine", engine)
    out = worker.handler(batch(record(postback_event("G", "A", "act=ack&v=yes&sid=zzz"), "m1")), None)
    assert out == {"batchItemFailures": []}
    assert len(line.replies) == 1


# ---------------------------------------------------------------- poison message -> DLQ
def redrive(handler, rec: dict[str, str], max_receive: int = MAX_RECEIVE) -> tuple[int, bool]:
    """Mimic the SQS redrive policy: redeliver while the handler reports the message failed;
    after `max_receive` receives it goes to the DLQ. Returns (receives, dead_lettered)."""
    for receive in range(1, max_receive + 1):
        out = handler(batch(rec), None)
        if not out["batchItemFailures"]:
            return receive, False
    return max_receive, True


def test_poison_message_exhausts_receives_then_dead_letters(monkeypatch):
    engine, line, *_ = make_engine()
    monkeypatch.setattr(worker, "_engine", engine)
    # decision button on a session whose store blows up -> every attempt fails
    boom = {"n": 0}

    def broken_get(_gid):
        boom["n"] += 1
        raise RuntimeError("store down")

    engine.store.get_session = broken_get
    e = postback_event("G", "A", "act=stop&sid=x")
    receives, dead = redrive(worker.handler, record(e, "poison"))
    assert (receives, dead) == (MAX_RECEIVE, True)
    assert boom["n"] == MAX_RECEIVE  # really retried each time, not skipped as "seen"
    assert line.replies == []


def test_poison_does_not_block_healthy_messages_in_same_batch(scripted):
    eng = scripted({"bad"})
    out = worker.handler(batch(record(ev("bad"), "mp"), record(ev("good"), "mg")), None)
    assert out["batchItemFailures"] == [{"itemIdentifier": "mp"}]
    assert "good" in eng.seen


def test_transient_failure_recovers_before_dlq(monkeypatch):
    engine, line, *_ = make_engine()
    engine.line = FlakyLine(line, fail_first=2)  # fails twice, third receive succeeds
    monkeypatch.setattr(worker, "_engine", engine)
    e = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    receives, dead = redrive(worker.handler, record(e, "m1"))
    assert (receives, dead) == (3, False)
    assert len(line.replies) == 1


# ---------------------------------------------------------------- lazy engine construction
def test_engine_is_built_lazily_once_and_config_problems_logged(monkeypatch, caplog):
    import handlers.ssm as ssm
    import wiring
    from config import Settings

    monkeypatch.setattr(worker, "_engine", None)
    built: list[Any] = []
    fake_engine = ScriptedEngine()
    seen_only: list[Any] = []

    def fake_ssm(only=None):
        seen_only.append(only)
        return Settings(bot_enabled=False)  # .problems() reports the kill switch

    monkeypatch.setattr(ssm, "settings_from_ssm", fake_ssm)
    monkeypatch.setattr(wiring, "build_engine", lambda s: built.append(s) or fake_engine)
    with caplog.at_level(logging.WARNING):
        a, b = worker._get_engine(), worker._get_engine()
    assert a is b is fake_engine and len(built) == 1
    assert "LINE_CHANNEL_SECRET_PARAM" not in seen_only[0]  # least privilege: worker never reads the signature secret
    assert any("kill switch" in r.getMessage() for r in caplog.records)
    monkeypatch.setattr(worker, "_engine", None)  # leave no module state behind
