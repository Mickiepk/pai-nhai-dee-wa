"""Message -> MessageDelta extraction.

Two providers behind one interface:
- RuleExtractor: offline Thai keyword rules. Free. Used in tests, the simulator,
  and as the fallback when Gemini fails or the per-session LLM cap is hit.
- GeminiExtractor: small Gemini model with structured JSON output.

Privacy: the message text is passed in memory only. Never log it.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol

from adapters.lexicon import canonical_term, normalize
from adapters.models import MessageDelta

log = logging.getLogger(__name__)


class Extractor(Protocol):
    """Turns ONE chat message into a MessageDelta. Implementations: RuleExtractor (offline) and GeminiExtractor."""

    async def extract(self, text: str, *, mentioned: bool, context: dict[str, Any]) -> MessageDelta:
        """Extract intent/preferences from text; context carries area, recent wants and suggestion names."""
        ...


# ---------------------------------------------------------------- offline rules

FOOD_TERMS = [
    "บุฟเฟต์นานาชาติ", "บุฟเฟต์", "ญี่ปุ่น", "เกาหลี", "จีน", "ไทย", "อิตาเลียน", "ฝรั่ง",
    "ปิ้งย่าง", "หมูกระทะ", "ชาบู", "สุกี้", "ซูชิ", "ราเมน", "ส้มตำ", "อีสาน", "ก๋วยเตี๋ยว",
    "ซีฟู้ด", "สเต๊ก", "พิซซ่า", "คาเฟ่", "ของหวาน", "มังสวิรัติ", "ฮาลาล",
]
ACTIVITY_TERMS = [
    "โบว์ลิ่ง", "คาราโอเกะ", "ดูหนัง", "พิพิธภัณฑ์", "สวนสาธารณะ", "ห้างสรรพสินค้า",
    "ห้าง", "นวด", "บอร์ดเกม", "ปีนผา", "แกลเลอรี่", "ตลาดนัด",
]
AREAS = [
    "อารีย์", "สยาม", "สาทร", "สีลม", "อโศก", "ทองหล่อ", "เอกมัย", "พร้อมพงษ์", "อนุสาวรีย์",
    "รัชดา", "ลาดพร้าว", "บางนา", "พระราม 9", "เยาวราช", "จตุจักร", "ชิดลม", "ราชเทวี",
]
_FOOD_INTENT = ["กินไร", "กินอะไร", "กินไหร", "กินอัลไล", "หิว", "ร้านอาหาร", "ข้าว", "มื้อ", "eat"]
_ACTIVITY_INTENT = ["ทำไร", "ทำอะไร", "ทำไหร", "เที่ยว", "ไปไหนดี", "เล่นอะไร", "activity"]
_MEETUP_INTENT = ["นัดเจอ", "เจอกันกี่โมง", "นัดกัน"]
# Explicit "we pick this one" phrases only. Bare "ตกลงไป..." / "จบที่..." were removed (BUG-11): they
# matched questions like "ตกลงไปไหนกันแน่" and vague "จบที่ไหนก็ได้".
_DECISION = ["ไปร้านนี้", "เอาร้านนี้", "ไปที่นี่", "เอาที่นี่", "ไปร้านที่", "เอาร้านที่",
             "เอาอันนี้แหละ", "ไปอันนี้", "ตกลงไปร้าน", "ตกลงเอาร้าน"]
# A message that asks something or stays open is never a decision.
_UNDECIDED = ["ไหม", "มั้ย", "หรือเปล่า", "ป่ะ", "กันแน่", "ก็ได้", "ที่ไหน", "ร้านไหน", "ดีวะ", "?", "？"]
_FAR = ["ไกลไป", "ไกลจัง", "ไกลเกิน", "ไกลอะ", "ไกลมาก", "too far"]
_RADIUS = re.compile(
    r"(?:ไม่เกิน|ภายใน|within|under|<=?)\s*(\d{1,2}(?:\.\d)?)\s*(?:กม|กิโล(?:เมตร)?|โล|km|k\b)")
_RADIUS_M = re.compile(  # BUG-13: meters, "ไม่เกิน 400 ม." / "ภายใน 500 เมตร" / "within 300 m"
    r"(?:ไม่เกิน|ภายใน|within|under|<=?)\s*(\d{2,4})\s*(?:เมตร|ม\.|ม(?![ก-๙])|meters?|m\b)")
_BETWEEN = ["ระหว่าง", "กึ่งกลาง", "ตรงกลาง", "between"]


def looks_undecided(text: str) -> bool:
    """True for questions / open-ended phrasing. Code-side guard on top of any extractor (rules or LLM)."""
    t = normalize(text.strip())
    return any(k in t for k in _UNDECIDED)


def find_areas(t: str) -> list[str]:
    """Known areas in the order they were SAID (not the order of the AREAS table)."""
    hits = sorted((t.index(a), a) for a in AREAS if a in t)
    return [a for _i, a in hits]
_NEGATIVE = ["ไม่เอา", "ไม่กิน", "ไม่อยาก", "เบื่อ", "ไม่ไป"]


def _find_terms(clause: str, vocab: list[str]) -> list[str]:
    found: list[str] = []
    rest = clause
    for term in sorted(vocab, key=len, reverse=True):  # longest first
        if term in rest:
            found.append(term)
            rest = rest.replace(term, " ")
    return found


class RuleExtractor:
    """Deterministic, offline. Good enough for the demo scenario and as a fallback."""

    async def extract(self, text: str, *, mentioned: bool, context: dict[str, Any]) -> MessageDelta:
        """Async wrapper around extract_sync (same result)."""
        return self.extract_sync(text, mentioned=mentioned)

    def extract_sync(self, text: str, *, mentioned: bool) -> MessageDelta:
        """Rule-based extraction: normalise slang/typos, then match intent, area, prefs, radius, decision, requests."""
        t = normalize(text.strip())  # table-driven slang/typo/English -> canonical Thai
        d = MessageDelta(asks_bot=mentioned)

        if any(k in t for k in _FOOD_INTENT):
            d.intent = "food"
        elif any(k in t for k in _ACTIVITY_INTENT):
            d.intent = "activity"
        elif any(k in t for k in _MEETUP_INTENT):
            d.intent = "meetup"

        areas = find_areas(t)
        if areas:
            d.area = areas[0]  # "A หรือ B" -> the one said first (BUG-18)
            if len(areas) > 1 and any(k in t for k in _BETWEEN):
                d.area2 = areas[1]  # "ระหว่าง A กับ B" -> midpoint (BUG-14)

        carry_ate = False
        carry_negative = False  # "ไม่เอา japanese": a bare negative word negates the next clause
        for clause in re.split(r"\s+", t):
            negative = any(n in clause for n in _NEGATIVE) or carry_negative
            ate = "เพิ่งกิน" in clause or "พึ่งกิน" in clause or carry_ate
            carry_negative = clause in _NEGATIVE
            carry_ate = clause in ("เพิ่งกิน", "พึ่งกิน")
            for term in _find_terms(clause, FOOD_TERMS + ACTIVITY_TERMS):
                if ate:
                    d.just_ate.append(term)
                elif negative:
                    d.dislikes.append(term)
                else:
                    d.likes.append(term)
            if negative and ("อันนี้" in clause or "ร้านนี้" in clause):
                d.rejects_last_suggestion = True

        if any(term in d.likes for term in ACTIVITY_TERMS) and d.intent == "none":
            d.intent = "activity"
        elif d.likes and d.intent == "none":
            d.intent = "food"

        if m := _RADIUS.search(t):
            d.radius_km = float(m.group(1))
        elif m := _RADIUS_M.search(t):
            d.radius_km = round(int(m.group(1)) / 1000, 3)
        elif any(k in t for k in _FAR):
            d.radius_halve = True

        if m := re.search(r"งบ\s*(\d{2,5})", t):
            d.budget_max_thb = int(m.group(1))
        if m := re.search(r"(\d{1,2})[:.](\d{2})", t):
            d.when = f"{int(m.group(1)):02d}:{m.group(2)}"
        elif m := re.search(r"(\d{1,2})\s*ทุ่ม", t):
            d.when = f"{int(m.group(1)) + 18:02d}:00"

        if (not any(n in t for n in _NEGATIVE) and not looks_undecided(t)
                and any(k in t for k in _DECISION)):
            d.decision_detected = True
            if m := re.search(r"(?:ร้าน|อัน)ที่\s*([1-3])", t):
                d.pick_index = int(m.group(1))

        if mentioned:
            if "ประกาศ" in t:
                d.request = "announce"
            elif "โหวต" in t:
                d.request = "vote"
            elif "หยุด" in t or "พอแล้ว" in t:
                d.request = "stop"
            elif (d.intent != "none" or d.likes or d.area or "มี" in t or "หา" in t
                  or d.radius_km or d.radius_halve):
                d.request = "search"
            d.needs_answer = d.request == "search" or t.endswith(("ไหม", "มั้ย", "?"))
        return d


# ---------------------------------------------------------------- Gemini

SYSTEM_PROMPT = """You extract planning signals from ONE Thai LINE group-chat message.
Friends are deciding where to eat (food), what to do (activity) or when/where to meet (meetup).
Return ONLY JSON for the schema. Copy short Thai keywords; never copy the full message.
- likes/dislikes: cuisines, food types, activities, e.g. "ญี่ปุ่น", "บุฟเฟต์นานาชาติ", "โบว์ลิ่ง".
- just_ate: food the speaker just ate (so avoid it).
- area: a Bangkok area/landmark if named (the first one said). area2: only for "between X and Y"
  ("ระหว่าง X กับ Y"): the second place.
- radius_km: explicit max distance in km ("ไม่เกิน 5 กม.", "within 5 km"). radius_halve: "ไกลไป" (too far).
- rejects_last_suggestion: the speaker rejects the bot's last suggestions.
- decision_detected: the group settles on a place, e.g. "โอเค งั้นไปร้านนี้". pick_index if they say which (1-3).
  Questions ("ตกลงไปไหนกันแน่") and open answers ("ที่ไหนก็ได้") are NOT decisions.
- request (only if mentioned=true): search | announce | vote | stop | none.
- asks_bot: the message is addressed to the bot. needs_answer: the bot should reply.
"""


class GeminiExtractor:
    """Gemini JSON-mode extractor (temperature 0, schema-validated).

    Any failure or timeout falls back to RuleExtractor.
    """

    def __init__(self, api_key: str, model: str, fallback: RuleExtractor, timeout_s: float = 4.0):
        from google import genai  # lazy: keeps tests and cold starts light

        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._fallback = fallback
        self._timeout_s = timeout_s

    async def extract(self, text: str, *, mentioned: bool, context: dict[str, Any]) -> MessageDelta:
        """Call Gemini with a timeout; invalid JSON, schema errors and exceptions use the rule fallback."""
        from google.genai import types

        prompt = f"mentioned={str(mentioned).lower()}\ncontext={context}\nmessage:\n{text}"
        try:
            resp = await asyncio.wait_for(
                self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=MessageDelta,
                        temperature=0,
                        max_output_tokens=300,
                    ),
                ),
                timeout=self._timeout_s,
            )
            delta = MessageDelta.model_validate_json(resp.text or "{}")
            delta.asks_bot = delta.asks_bot or mentioned
            for field in ("likes", "dislikes", "just_ate"):  # spelling variants -> canonical terms
                setattr(delta, field, [canonical_term(x) for x in getattr(delta, field)])
            log.info("llm_call ok model=%s", self._model)  # cost tracking, no text
            return delta
        except Exception as exc:  # degrade gracefully, never block the reply
            log.warning("llm_call failed (%s); using rule fallback", type(exc).__name__)
            return self._fallback.extract_sync(text, mentioned=mentioned)
