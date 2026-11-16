import base64
import hashlib
import hmac
import json

from handlers.webhook import parse_body, process, should_enqueue
from scripts.events import join_event, postback_event, sticker_event, text_event

SECRET = "test-secret"


def _sign(body: bytes) -> str:
    return base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()


def _body(*events) -> bytes:
    return json.dumps({"destination": "Ubot", "events": list(events)}).encode()


def test_bad_signature_is_401_and_nothing_queued():
    sent = []
    body = _body(text_event("G", "A", "@bot กินไรดี"))
    assert process(body, "wrong", SECRET, lambda *a: sent.append(a))["statusCode"] == 401
    assert process(body, None, SECRET, lambda *a: sent.append(a))["statusCode"] == 401
    assert sent == []


def test_good_signature_queues_only_useful_events_per_group():
    sent = []
    body = _body(text_event("G", "A", "@bot กินไรดี"), text_event("G", "B", "555"),
                 sticker_event("G", "B"), text_event("G", "C", "อยากกินชาบู"),
                 postback_event("G", "A", "act=stop&sid=x"), join_event("G2"))
    resp = process(body, _sign(body), SECRET, lambda *a: sent.append(a))
    assert resp["statusCode"] == 200
    assert len(sent) == 4
    assert {group for _b, group, _d in sent} == {"G", "G2"}
    assert len({dedup for *_x, dedup in sent}) == 4


def test_should_enqueue_mention_even_if_short():
    assert should_enqueue(text_event("G", "A", "@bot"))
    assert not should_enqueue(text_event("G", "A", "ok"))


def test_parse_base64_body():
    assert parse_body({"body": base64.b64encode(b"abc").decode(), "isBase64Encoded": True}) == b"abc"
