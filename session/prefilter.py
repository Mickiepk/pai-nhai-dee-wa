"""Cheap rule pre-filter: decides if a passive (non-@mention) message is worth an LLM call."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+")
_LAUGH = re.compile(r"^(5{3,}|ห{3,}|ฮ{3,}|lol+|lmao|55+\+*)$", re.IGNORECASE)
_FILLER = {
    "ok", "okay", "oke", "k", "kk", "โอเค", "โอเคร", "อือ", "อืม", "ได้", "ครับ", "ค่ะ", "คับ",
    "จ้า", "จ้ะ", "เค", "ใช่", "yes", "no", "ไม่", "555", "+1", "จริง", "ฮ่าๆ", "55", "ๆ",
}


def worth_reading(message_type: str, text: str | None) -> bool:
    """False for stickers, images, '555', 'ok', links-only and anything under 3 chars."""
    if message_type != "text" or not text:
        return False
    stripped = _URL.sub("", text).strip()
    if len(stripped) < 3:
        return False
    compact = re.sub(r"[\s!?.,~]+", "", stripped).lower()
    if len(compact) < 3 or compact in _FILLER or _LAUGH.match(compact):
        return False
    letters = "".join(ch for ch in compact if ch.isalnum())  # "5555555 🤣" is still just laughing
    if not letters or letters in _FILLER or _LAUGH.match(letters):
        return False
    return True  # something other than emoji / punctuation / laughter is left
