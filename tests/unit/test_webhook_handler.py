"""handlers/webhook.py: signature check, empty/odd bodies, size, Function URL envelope, SQS fan-out.

No network, no AWS: SQS is a recording fake, the signature secret is injected.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
from typing import Any

import pytest

import handlers.webhook as webhook
from handlers.webhook import handler, parse_body, process, should_enqueue
from scripts.events import join_event, sticker_event, text_event

SECRET = "unit-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def body_of(*events: dict[str, Any]) -> bytes:
    return json.dumps({"destination": "Ubot", "events": list(events)}, ensure_ascii=False).encode()


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def __call__(self, body: str, group: str, dedup: str) -> None:
        self.sent.append((body, group, dedup))


# ---------------------------------------------------------------- signature
@pytest.mark.parametrize("signature", [None, "", "not-base64!!", "AAAA", sign(b"other body")])
def test_invalid_signature_is_401_and_queues_nothing(signature):
    rec = Recorder()
    body = body_of(text_event("G", "A", "@bot กินไรดี"))
    assert process(body, signature, SECRET, rec)["statusCode"] == 401
    assert rec.sent == []


def test_signature_made_with_other_secret_is_rejected():
    rec = Recorder()
    body = body_of(text_event("G", "A", "@bot กินไรดี"))
    assert process(body, sign(body, "different"), SECRET, rec)["statusCode"] == 401


def test_empty_secret_never_validates():
    """A misconfigured (empty) secret must fail closed, even for a signature made with ''."""
    body = body_of()
    assert process(body, sign(body, ""), "", Recorder())["statusCode"] == 401


def test_one_byte_change_in_body_breaks_signature():
    body = body_of(text_event("G", "A", "@bot กินไรดี"))
    assert process(body + b" ", sign(body), SECRET, Recorder())["statusCode"] == 401


# ---------------------------------------------------------------- empty / odd bodies
@pytest.mark.parametrize("raw", [b'{"destination":"U","events":[]}', b"{}", b""])
def test_empty_events_is_200_and_nothing_queued(raw):
    """LINE's console 'Verify' button sends events=[]; scripts/smoke.py relies on this too."""
    rec = Recorder()
    assert process(raw, sign(raw), SECRET, rec) == {"statusCode": 200, "body": "ok"}
    assert rec.sent == []


def test_only_noise_events_queue_nothing():
    rec = Recorder()
    body = body_of(text_event("G", "A", "555"), text_event("G", "A", "ok"), sticker_event("G", "A"),
                   {"type": "unfollow", "source": {"type": "user", "userId": "U"}},
                   {"type": "message", "message": {"type": "image"}, "source": {"groupId": "G"}})
    assert process(body, sign(body), SECRET, rec)["statusCode"] == 200
    assert rec.sent == []


def test_event_without_source_does_not_crash():
    rec = Recorder()
    e = text_event("G", "A", "@bot กินไรดี")
    del e["source"]
    process(body_of(e), sign(body_of(e)), SECRET, rec)
    assert rec.sent and rec.sent[0][1] == "none"  # falls back to the "none" message group


def test_group_id_selection_group_room_user():
    rec = Recorder()
    g = text_event("G1", "A", "@bot กินไรดี")
    r = text_event("x", "A", "@bot กินไรดี")
    r["source"] = {"type": "room", "roomId": "R1", "userId": "A"}
    u = text_event("x", "A", "@bot กินไรดี")
    u["source"] = {"type": "user", "userId": "U1"}
    b = body_of(g, r, u)
    process(b, sign(b), SECRET, rec)
    assert [grp for _b, grp, _d in rec.sent] == ["G1", "R1", "U1"]


def test_dedup_id_is_the_webhook_event_id():
    rec = Recorder()
    e = join_event("G")
    b = body_of(e)
    process(b, sign(b), SECRET, rec)
    assert rec.sent[0][2] == e["webhookEventId"]


def test_queued_body_is_the_event_json_and_keeps_thai_unescaped():
    rec = Recorder()
    e = text_event("G", "A", "@bot กินไรดีแถวอารีย์")
    b = body_of(e)
    process(b, sign(b), SECRET, rec)
    assert "กินไรดี" in rec.sent[0][0]  # ensure_ascii=False keeps the SQS body small
    assert json.loads(rec.sent[0][0]) == e


def test_event_order_is_preserved_in_fan_out():
    rec = Recorder()
    evs = [text_event("G", "A", f"@bot กินไรดีแถวอารีย์ {i}") for i in range(5)]
    b = body_of(*evs)
    process(b, sign(b), SECRET, rec)
    assert [json.loads(x[0])["webhookEventId"] for x in rec.sent] == [e["webhookEventId"] for e in evs]


def test_sqs_failure_propagates_so_line_redelivers():
    """If SQS send fails we must NOT answer 200 (LINE would never retry and the event is lost)."""
    def broken(*_a):
        raise RuntimeError("sqs down")

    b = body_of(text_event("G", "A", "@bot กินไรดี"))
    with pytest.raises(RuntimeError):
        process(b, sign(b), SECRET, broken)


# ---------------------------------------------------------------- size limit
def test_large_valid_body_is_processed_without_truncation():
    """A body just under MAX_BODY_BYTES (256 KB) of 'noise' events still parses and filters correctly."""
    rec = Recorder()
    noise = [text_event("G", "A", "555") for _ in range(1100)]
    keep = text_event("G", "B", "@bot กินไรดีแถวอารีย์")
    b = body_of(*noise, keep)
    assert 150_000 < len(b) <= webhook.MAX_BODY_BYTES
    assert process(b, sign(b), SECRET, rec)["statusCode"] == 200
    assert len(rec.sent) == 1


def test_unsigned_garbage_body_is_401_before_json_parse():
    """Signature is checked before parsing, so garbage unsigned input costs one HMAC, not a parse."""
    garbage = b"[" * 200_000  # under the size cap; would blow the JSON parser's recursion if parsed
    assert process(garbage, "bad", SECRET, Recorder())["statusCode"] == 401


@pytest.mark.parametrize("signature", ["bad", None])
def test_body_over_256kb_is_413_without_hmac_or_parse(signature):
    rec = Recorder()
    big = b"x" * (webhook.MAX_BODY_BYTES + 1)
    assert process(big, signature, SECRET, rec)["statusCode"] == 413 and rec.sent == []
    big_signed = b" " * (webhook.MAX_BODY_BYTES + 1)
    assert process(big_signed, sign(big_signed), SECRET, rec)["statusCode"] == 413


def test_body_exactly_at_limit_is_accepted():
    rec = Recorder()
    b = b'{"events":[]}'
    b = b + b" " * (webhook.MAX_BODY_BYTES - len(b))
    assert len(b) == webhook.MAX_BODY_BYTES
    assert process(b, sign(b), SECRET, rec)["statusCode"] == 200


@pytest.mark.parametrize("raw", [b"not json", b"{", b"\xff\xfe", b"[1,2]", b'"str"', b'{"events": "x"}',
                                 b'{"events": [1]}', b"null"])
def test_valid_signature_but_invalid_json_is_400_not_an_exception(raw):
    rec = Recorder()
    assert process(raw, sign(raw), SECRET, rec)["statusCode"] == 400 and rec.sent == []


def test_fallback_dedup_id_is_sha256_of_canonical_json():
    a = {"type": "join", "source": {"groupId": "G", "type": "group"}}
    b = {"source": {"type": "group", "groupId": "G"}, "type": "join"}  # same event, other key order
    assert webhook.fallback_dedup_id(a) == webhook.fallback_dedup_id(b)
    assert len(webhook.fallback_dedup_id(a)) == 64 and webhook.fallback_dedup_id(a) != webhook.fallback_dedup_id(
        {**a, "type": "leave"})
    rec = Recorder()
    body = body_of(a)
    process(body, sign(body), SECRET, rec)
    assert rec.sent[0][2] == webhook.fallback_dedup_id(a)


# ---------------------------------------------------------------- should_enqueue
@pytest.mark.parametrize("event,expected", [
    ({"type": "join"}, True),
    ({"type": "leave"}, True),
    ({"type": "memberLeft"}, True),
    ({"type": "postback"}, True),
    ({"type": "follow"}, False),
    ({"type": "unsend"}, False),
    ({}, False),
    ({"type": "message"}, False),
    ({"type": "message", "message": {"type": "text", "text": None}}, False),
    ({"type": "message", "message": {"type": "text", "text": "@bot", "mention": {"mentionees": [
        {"isSelf": True, "index": 0, "length": 4}]}}}, True),
    ({"type": "message", "message": {"type": "text", "text": "@someone-else hi", "mention": {"mentionees": [
        {"isSelf": False, "index": 0, "length": 13}]}}}, True),  # not for us, but long enough to be read
    ({"type": "message", "message": {"type": "text", "text": "ok", "mention": {"mentionees": [
        {"isSelf": False, "index": 0, "length": 2}]}}}, False),
    ({"type": "message", "message": {"type": "text", "text": "อยากกินชาบูกัน"}}, True),
])
def test_should_enqueue_table(event, expected):
    assert should_enqueue(event) is expected


# ---------------------------------------------------------------- parse_body / Function URL envelope
def test_parse_body_variants():
    assert parse_body({"body": "abc"}) == b"abc"
    assert parse_body({"body": None}) == b""
    assert parse_body({}) == b""
    assert parse_body({"body": base64.b64encode("ไทย".encode()).decode(), "isBase64Encoded": True}) == "ไทย".encode()
    assert parse_body({"body": "ไทย"}) == "ไทย".encode()


class FakeSqs:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_message(self, **kw: Any) -> None:
        self.calls.append(kw)


@pytest.fixture
def wired(monkeypatch):
    """handler() with the cold-start state pre-filled (no boto3, no SSM)."""
    sqs = FakeSqs()
    monkeypatch.setattr(webhook, "_secret", SECRET)
    monkeypatch.setattr(webhook, "_sqs", sqs)
    monkeypatch.setenv("QUEUE_URL", "https://sqs.example/queue.fifo")
    return sqs


def test_handler_function_url_envelope_headers_case_insensitive(wired):
    b = body_of(text_event("G", "A", "@bot กินไรดี"))
    for header in ("x-line-signature", "X-Line-Signature", "X-LINE-SIGNATURE"):
        wired.calls.clear()
        out = handler({"headers": {header: sign(b)}, "body": b.decode()}, None)
        assert out["statusCode"] == 200
        assert len(wired.calls) == 1


def test_handler_base64_body_and_sqs_arguments(wired):
    e = text_event("GRP", "A", "@bot กินไรดี")
    b = body_of(e)
    out = handler({"headers": {"x-line-signature": sign(b)},
                   "body": base64.b64encode(b).decode(), "isBase64Encoded": True}, None)
    assert out["statusCode"] == 200
    call = wired.calls[0]
    assert call["QueueUrl"] == "https://sqs.example/queue.fifo"
    assert call["MessageGroupId"] == "GRP"
    assert call["MessageDeduplicationId"] == e["webhookEventId"]


def test_handler_missing_headers_is_401(wired):
    b = body_of(text_event("G", "A", "@bot กินไรดี"))
    assert handler({"body": b.decode()}, None)["statusCode"] == 401
    assert handler({"headers": None, "body": b.decode()}, None)["statusCode"] == 401
    assert wired.calls == []


def test_handler_requires_queue_url(wired, monkeypatch):
    monkeypatch.delenv("QUEUE_URL")
    with pytest.raises(KeyError):
        handler({"headers": {}, "body": ""}, None)


def test_handler_cold_start_loads_only_the_signature_secret(monkeypatch):
    """Least privilege: the webhook Lambda may read just one SSM parameter."""
    import boto3

    import handlers.ssm as ssm
    from config import Settings

    asked: list[Any] = []
    monkeypatch.setattr(webhook, "_secret", None)
    monkeypatch.setattr(webhook, "_sqs", None)
    monkeypatch.setenv("QUEUE_URL", "q")
    monkeypatch.setattr(ssm, "settings_from_ssm",
                        lambda only=None: asked.append(only) or Settings(line_channel_secret=SECRET))
    monkeypatch.setattr(boto3, "client", lambda name: FakeSqs())
    b = body_of()
    assert handler({"headers": {"x-line-signature": sign(b)}, "body": b.decode()}, None)["statusCode"] == 200
    assert asked == [("LINE_CHANNEL_SECRET_PARAM",)]
    monkeypatch.setattr(webhook, "_secret", None)
    monkeypatch.setattr(webhook, "_sqs", None)


# ---------------------------------------------------------------- fallback dedup id (was a known weakness)
def test_fallback_dedup_id_is_stable_across_processes():
    code = (
        "import json,sys;from handlers.webhook import process;sent=[];"
        "e={'type':'join','source':{'type':'group','groupId':'G'}};"
        "import base64,hashlib,hmac;b=json.dumps({'events':[e]}).encode();"
        "sig=base64.b64encode(hmac.new(b's',b,hashlib.sha256).digest()).decode();"
        "process(b,sig,'s',lambda *a:sent.append(a));print(sent[0][2])"
    )
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    outs = {
        subprocess.run([sys.executable, "-I", "-c", f"import sys;sys.path.insert(0,{root!r});{code}"],
                       capture_output=True, text=True, check=True,
                       env={"PYTHONHASHSEED": seed, "PATH": os.environ.get("PATH", "")}).stdout.strip()
        for seed in ("1", "2")
    }
    assert len(outs) == 1
