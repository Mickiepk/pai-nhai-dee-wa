"""Build fake LINE webhook events (shared by the simulator and tests)."""

from __future__ import annotations

import itertools
from typing import Any

BOT_TAG = "@bot"
_ids = itertools.count(1)


def _base(etype: str, group: str, user: str) -> dict[str, Any]:
    n = next(_ids)
    return {"type": etype, "webhookEventId": f"ev{n:05d}", "replyToken": f"rt{n:05d}",
            "timestamp": 0, "mode": "active",
            "source": {"type": "group", "groupId": group, "userId": user}}


def text_event(group: str, user: str, text: str) -> dict[str, Any]:
    ev = _base("message", group, user)
    msg: dict[str, Any] = {"type": "text", "id": ev["webhookEventId"], "text": text}
    if text.startswith(BOT_TAG):
        msg["mention"] = {"mentionees": [{"index": 0, "length": len(BOT_TAG), "type": "user",
                                          "userId": "Ubot", "isSelf": True}]}
    ev["message"] = msg
    return ev


def sticker_event(group: str, user: str) -> dict[str, Any]:
    ev = _base("message", group, user)
    ev["message"] = {"type": "sticker", "id": "s", "packageId": "1", "stickerId": "1"}
    return ev


def postback_event(group: str, user: str, data: str) -> dict[str, Any]:
    ev = _base("postback", group, user)
    ev["postback"] = {"data": data}
    return ev


def join_event(group: str) -> dict[str, Any]:
    ev = _base("join", group, "")
    del ev["source"]["userId"]
    return ev
