"""Webhook Lambda (Function URL): verify signature, drop noise, enqueue to SQS FIFO, return 200.

Never logs message text.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any

from adapters.line import verify_signature
from session.engine import self_mentioned
from session.prefilter import worth_reading

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_BODY_BYTES = 256 * 1024  # LINE webhook bodies are a few KB; anything bigger is not LINE (-> 413)

_secret: str | None = None
_sqs: Any = None


def should_enqueue(event: dict[str, Any]) -> bool:
    """Cheap filter: keep join/leave/memberLeft/postback and text that @mentions the bot or passes the prefilter."""
    etype = event.get("type")
    if etype in ("join", "leave", "memberLeft", "postback"):
        return True
    if etype != "message":
        return False
    msg = event.get("message", {})
    if msg.get("type") != "text":
        return False
    return self_mentioned(msg) or worth_reading("text", msg.get("text"))


def parse_body(request: dict[str, Any]) -> bytes:
    """Raw request body as bytes (decodes base64 when the Function URL says so)."""
    body = request.get("body") or ""
    return base64.b64decode(body) if request.get("isBase64Encoded") else body.encode()


def fallback_dedup_id(ev: dict[str, Any]) -> str:
    """Stable SQS dedup id for an event without webhookEventId: sha256 of its canonical JSON.
    (builtin hash() is salted per process, so it differs between Lambda cold starts.)"""
    canonical = json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def process(body: bytes, signature: str | None, secret: str, send: Any) -> dict[str, Any]:
    """Verify, parse and fan out one webhook body. 413 too big, 401 bad signature, 400 bad JSON, else 200."""
    if len(body) > MAX_BODY_BYTES:  # cheap check first: no HMAC, no parse
        return {"statusCode": 413, "body": "payload too large"}
    if not verify_signature(secret, body, signature):
        return {"statusCode": 401, "body": "bad signature"}
    try:
        payload = json.loads(body or b"{}")
        events = payload.get("events", [])
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            raise ValueError("events must be a list of objects")
    except (ValueError, AttributeError):  # JSONDecodeError/UnicodeDecodeError are ValueErrors; non-object payload
        log.warning("webhook: signed body is not valid LINE JSON")
        return {"statusCode": 400, "body": "bad request"}
    queued = 0
    for ev in events:
        if not should_enqueue(ev):
            continue
        src = ev.get("source", {})
        group = src.get("groupId") or src.get("roomId") or src.get("userId") or "none"
        send(json.dumps(ev, ensure_ascii=False), group, ev.get("webhookEventId") or fallback_dedup_id(ev))
        queued += 1
    log.info("webhook events=%d queued=%d", len(events), queued)
    return {"statusCode": 200, "body": "ok"}


def handler(request: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """Lambda entry (Function URL): load the LINE secret once, then verify, filter and enqueue via process()."""
    global _secret, _sqs
    if _secret is None:
        import boto3

        from handlers.ssm import settings_from_ssm

        _secret = settings_from_ssm(only=("LINE_CHANNEL_SECRET_PARAM",)).line_channel_secret
        _sqs = boto3.client("sqs")
    headers = {k.lower(): v for k, v in (request.get("headers") or {}).items()}
    queue_url = os.environ["QUEUE_URL"]

    def send(body: str, group: str, dedup: str) -> None:
        """Send one event to SQS FIFO (group = chat id, dedup id = event id)."""
        _sqs.send_message(QueueUrl=queue_url, MessageBody=body,
                          MessageGroupId=group, MessageDeduplicationId=dedup)

    return process(parse_body(request), headers.get("x-line-signature"), _secret, send)
