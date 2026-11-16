"""Webhook Lambda (Function URL): verify signature, drop noise, enqueue to SQS FIFO, return 200.

Never logs message text.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from adapters.line import verify_signature
from session.engine import self_mentioned
from session.prefilter import worth_reading

log = logging.getLogger()
log.setLevel(logging.INFO)

_secret: str | None = None
_sqs: Any = None


def should_enqueue(event: dict[str, Any]) -> bool:
    etype = event.get("type")
    if etype in ("join", "leave", "postback"):
        return True
    if etype != "message":
        return False
    msg = event.get("message", {})
    if msg.get("type") != "text":
        return False
    return self_mentioned(msg) or worth_reading("text", msg.get("text"))


def parse_body(request: dict[str, Any]) -> bytes:
    body = request.get("body") or ""
    return base64.b64decode(body) if request.get("isBase64Encoded") else body.encode()


def process(body: bytes, signature: str | None, secret: str, send: Any) -> dict[str, Any]:
    if not verify_signature(secret, body, signature):
        return {"statusCode": 401, "body": "bad signature"}
    events = json.loads(body or b"{}").get("events", [])
    queued = 0
    for ev in events:
        if not should_enqueue(ev):
            continue
        src = ev.get("source", {})
        group = src.get("groupId") or src.get("roomId") or src.get("userId") or "none"
        send(json.dumps(ev, ensure_ascii=False), group, ev.get("webhookEventId") or str(hash(json.dumps(ev))))
        queued += 1
    log.info("webhook events=%d queued=%d", len(events), queued)
    return {"statusCode": 200, "body": "ok"}


def handler(request: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    global _secret, _sqs
    if _secret is None:
        import boto3

        from handlers.ssm import settings_from_ssm

        _secret = settings_from_ssm(only=("LINE_CHANNEL_SECRET_PARAM",)).line_channel_secret
        _sqs = boto3.client("sqs")
    headers = {k.lower(): v for k, v in (request.get("headers") or {}).items()}
    queue_url = os.environ["QUEUE_URL"]

    def send(body: str, group: str, dedup: str) -> None:
        _sqs.send_message(QueueUrl=queue_url, MessageBody=body,
                          MessageGroupId=group, MessageDeduplicationId=dedup)

    return process(parse_body(request), headers.get("x-line-signature"), _secret, send)
