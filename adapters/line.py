"""LINE Messaging API gateway: reply only (no push in the pilot), plus signature check."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)

Msg = dict[str, Any]  # LINE message JSON (text / flex)


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """Check LINE's x-line-signature: base64(HMAC-SHA256(secret, raw body)). Fails closed on empty secret/signature."""
    if not channel_secret or not signature:
        return False
    digest = hmac.new(channel_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


class LineGateway(Protocol):
    """What the engine needs from LINE: reply with a token and look up a member's display name."""

    async def reply(self, reply_token: str, messages: list[Msg]) -> None:
        """Send up to 5 messages using a (single-use, short-lived) reply token."""
        ...
    async def member_name(self, group_id: str, user_id: str) -> str:
        """Display name of a group member."""
        ...


class RealLine:
    """LINE Messaging API client (lazy-imports the SDK). Raises on reply failure so the SQS retry can run."""

    def __init__(self, access_token: str):
        from linebot.v3.messaging import Configuration

        self._config = Configuration(access_token=access_token)

    async def reply(self, reply_token: str, messages: list[Msg]) -> None:
        """Reply via the Messaging API; only the first 5 messages are sent. Errors propagate."""
        from linebot.v3.messaging import AsyncApiClient, AsyncMessagingApi, ReplyMessageRequest

        req = ReplyMessageRequest.from_dict({"replyToken": reply_token, "messages": messages[:5]})
        async with AsyncApiClient(self._config) as client:
            await AsyncMessagingApi(client).reply_message(req)
        log.info("line_reply messages=%d", len(messages))

    async def member_name(self, group_id: str, user_id: str) -> str:
        """Group member profile name; falls back to 'เพื่อน' when the profile is unavailable."""
        from linebot.v3.messaging import AsyncApiClient, AsyncMessagingApi

        try:
            async with AsyncApiClient(self._config) as client:
                prof = await AsyncMessagingApi(client).get_group_member_profile(group_id, user_id)
            return prof.display_name
        except Exception:  # user may have no profile permission
            return "เพื่อน"


class FakeLine:
    """Records replies instead of sending. Used by tests and the simulator."""

    def __init__(self, names: dict[str, str] | None = None):
        self.names = names or {}
        self.replies: list[tuple[str, list[Msg]]] = []

    async def reply(self, reply_token: str, messages: list[Msg]) -> None:
        """Record the reply (first 5 messages) instead of sending it."""
        self.replies.append((reply_token, messages[:5]))

    async def member_name(self, group_id: str, user_id: str) -> str:
        """Name from the injected map, else the user id."""
        return self.names.get(user_id, user_id)
