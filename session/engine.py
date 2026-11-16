"""Session engine: one LINE event in, zero or more replies out.

States per group: (none) -> LISTENING <-> CONFIRMING -> (ended). See docs/ARCHITECTURE.md.
The bot SPEAKS only when @mentioned, on a decision, or on a button tap, always via that
event's reply token. Raw chat text is never stored or logged.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from adapters.line import LineGateway, Msg
from adapters.llm import Extractor, RuleExtractor
from adapters.models import MessageDelta
from adapters.places import Places
from config import Settings
from features import cards, search
from session.merge import apply_delta, avoid_terms
from session.models import Session, State
from session.prefilter import worth_reading
from store.base import Store

log = logging.getLogger(__name__)

GREETING = ("หวัดดีแก๊ง เราคือ ไปไหนดีวะ 👋\n"
            "เรียก @ไปไหนดีวะ แล้วบอกย่าน เช่น \"กินไรดีแถวอารีย์\"\n"
            "เราอ่านแชตเฉพาะตอนเปิดโหมดช่วยคิด (ไม่เกิน 60 นาที) และไม่เก็บข้อความ")
HELP = "เรียกเราแล้วบอกว่าอยากกิน/อยากไปไหน เช่น \"กินไรดีแถวอารีย์\" ได้เลย"
ASK_AREA = "จะไปแถวไหนกันอะ?"
AREA_CHOICES = ["สยาม", "อารีย์", "สาทร", "อโศก"]


def _bkk_day(now: int) -> str:
    return (datetime.fromtimestamp(now, UTC) + timedelta(hours=7)).strftime("%Y%m%d")


def self_mentioned(message: dict[str, Any]) -> bool:
    mentionees = (message.get("mention") or {}).get("mentionees", [])
    return any(m.get("isSelf") for m in mentionees)


def strip_mentions(message: dict[str, Any]) -> str:
    text: str = message.get("text") or ""
    mentionees = (message.get("mention") or {}).get("mentionees", [])
    for m in sorted(mentionees, key=lambda m: m.get("index", 0), reverse=True):
        i, n = m.get("index", 0), m.get("length", 0)
        text = text[:i] + text[i + n:]
    return text.strip()


class SessionEngine:
    def __init__(self, settings: Settings, store: Store, line: LineGateway, llm: Extractor,
                 places: Places, clock: Callable[[], int] = lambda: int(time.time())):
        self.s = settings
        self.store = store
        self.line = line
        self.llm = llm
        self.rules = RuleExtractor()
        self.places = places
        self.clock = clock

    # ------------------------------------------------------------ entry point
    async def handle(self, event: dict[str, Any]) -> None:
        if not self.s.bot_enabled:
            return
        now = self.clock()
        eid = event.get("webhookEventId")
        if eid and self.store.seen_event(eid, now):
            return  # duplicate delivery
        try:
            await self._dispatch(event, now)
        except Exception:
            if eid:  # let the SQS retry process it again instead of dropping it
                self.store.forget_event(eid)
            raise

    async def _dispatch(self, event: dict[str, Any], now: int) -> None:
        src = event.get("source", {})
        gid = src.get("groupId") or src.get("roomId")
        etype = event.get("type")
        token = event.get("replyToken", "")
        if gid is None:
            if etype == "message":
                await self.line.reply(token, [cards.text("ชวนเราเข้ากลุ่มเพื่อนก่อนนะ แล้ว @ เรียกในกลุ่มได้เลย")])
            return
        if etype == "join":
            await self.line.reply(token, [cards.text(GREETING)])
        elif etype == "leave":  # PDPA: delete everything for this group
            self.store.delete_session(gid)
        elif etype == "message":
            await self._on_message(gid, src.get("userId", "unknown"), token, event["message"], now)
        elif etype == "postback":
            await self._on_postback(gid, src.get("userId", "unknown"), token,
                                    event.get("postback", {}).get("data", ""), now)

    # ------------------------------------------------------------ helpers
    def _active(self, gid: str, now: int) -> Session | None:
        session = self.store.get_session(gid)
        if session and session.is_expired(now):
            self.store.delete_session(gid)
            return None
        return session

    async def _extract(self, session: Session | None, text: str, mentioned: bool) -> MessageDelta:
        if session is not None and session.llm_calls >= self.s.max_llm_calls_per_session:
            return self.rules.extract_sync(text, mentioned=mentioned)  # free fallback
        if session is not None:
            session.llm_calls += 1
        ctx = {}
        if session:
            ctx = {"area": session.area, "wants": session.group_wants[-3:],
                   "suggestions": [s.name for s in session.suggestions]}
        return await self.llm.extract(text, mentioned=mentioned, context=ctx)

    def _new_session(self, gid: str, now: int) -> Session:
        return Session(session_id=uuid.uuid4().hex[:8], group_id=gid, started_at=now,
                       expires_at=now + self.s.session_minutes * 60)

    async def _names(self, gid: str, user_ids: list[str]) -> dict[str, str]:
        return {u: await self.line.member_name(gid, u) for u in user_ids}

    # ------------------------------------------------------------ messages
    async def _on_message(self, gid: str, uid: str, token: str, message: dict[str, Any], now: int) -> None:
        mentioned = message.get("type") == "text" and self_mentioned(message)
        session = self._active(gid, now)

        if session is None:
            if mentioned:
                await self._start(gid, uid, token, strip_mentions(message), now)
            return  # no session: never read the chat

        if not mentioned:
            if message.get("type") == "text" and uid not in session.participants:
                session.participants.append(uid)
            if not (self.s.chat_reading_enabled and worth_reading(message.get("type", ""), message.get("text"))):
                self.store.put_session(session)
                return

        text = strip_mentions(message) if mentioned else message.get("text", "")
        delta = await self._extract(session, text, mentioned)
        apply_delta(session, uid, delta)
        replies: list[Msg] = []

        if delta.decision_detected and session.suggestions and session.state == State.LISTENING:
            replies = await self._confirm(session, delta.pick_index)
        elif mentioned:
            replies = await self._answer_mention(session, delta)

        if replies:
            await self.line.reply(token, replies)
        if not session.ended:
            self.store.put_session(session)

    async def _start(self, gid: str, uid: str, token: str, text: str, now: int) -> None:
        delta = await self._extract(None, text, True)
        if delta.intent == "none" and delta.request != "search":
            await self.line.reply(token, [cards.text(HELP)])
            return
        session = self._new_session(gid, now)
        session.llm_calls = 1
        apply_delta(session, uid, delta)
        replies: list[Msg] = [cards.listening_notice(session, self.s.session_minutes)]
        replies += await self._search_replies(session, gid, now)
        await self.line.reply(token, replies)
        self.store.put_session(session)

    async def _answer_mention(self, session: Session, delta: MessageDelta) -> list[Msg]:
        if delta.request == "stop":
            self._end(session)
            return [cards.text("โอเค หยุดฟังละ เรียกใหม่ได้ตลอดนะ")]
        if delta.request == "announce":
            names = await self._names(session.group_id, list(session.prefs))
            return [cards.announcement(session, names)]
        if delta.request == "vote":
            return [cards.vote_stub(session)]
        if delta.request == "search" or delta.needs_answer or delta.radius_km or delta.radius_halve:
            return await self._search_replies(session, session.group_id, self.clock(),
                                              exclude_last=delta.rejects_last_suggestion)
        return [cards.text("ฟังอยู่นะ อยากให้หาอะไรเพิ่มก็เรียกได้เลย")]

    async def _search_replies(self, session: Session, gid: str, now: int, *, exclude_last: bool = False) -> list[Msg]:
        if not session.area:
            return [cards.text(ASK_AREA, [(a, f"act=area&a={a}&sid={session.session_id}") for a in AREA_CHOICES])]
        day = _bkk_day(now)
        if self.store.incr(f"QUOTA#GROUP#{gid}#{day}", now) > self.s.max_searches_per_group_per_day:
            return [cards.text(f"วันนี้กลุ่มนี้ค้นครบ {self.s.max_searches_per_group_per_day} ครั้งแล้ว พรุ่งนี้มาใหม่นะ")]

        def spend() -> bool:  # every Places call (geocode and text search) counts against the cap
            return self.store.incr(f"QUOTA#PLACES#{day}", now) <= self.s.max_places_calls_per_day

        outcome = await search.search(session, self.places, exclude_last=exclude_last, spend=spend)
        if outcome.error == "cap":
            log.warning("global places cap hit")
            return [cards.text("วันนี้คนใช้เยอะจนเต็มโควตาละ พรุ่งนี้มาใหม่นะ 🙏")]
        if outcome.error == "no_area":  # area not in AREA_CENTERS and geocode failed
            return [cards.text(f"หาพิกัด{session.area}ไม่เจอ ลองเลือกย่านใกล้ๆ ดูนะ",
                               [(a, f"act=area&a={a}&sid={session.session_id}") for a in AREA_CHOICES])]
        if outcome.error == "places_failed":
            return [cards.text("ตอนนี้ค้นร้านไม่ได้ ลองเรียกใหม่อีกทีนะ")]
        if outcome.error == "not_found":
            return [cards.text(f"ใน {outcome.radius_km:g} กม. จาก{session.area} ไม่เจอที่ตรงเงื่อนไขเลย ลองเปลี่ยนแบบดูไหม?")]
        session.suggestions = outcome.suggestions
        header = f"ได้ {len(outcome.suggestions)} ที่ละ ทุกที่ไม่เกิน {outcome.radius_km:g} กม. จาก{session.area}"
        avoid = avoid_terms(session)
        if avoid:
            header += f"\n(ข้าม{'/'.join(sorted(avoid))}ให้ละ มีคนไม่เอาหรือเพิ่งกิน)"
        return cards.suggestions(session, outcome.suggestions, header)

    async def _confirm(self, session: Session, pick: int | None) -> list[Msg]:
        idx = (pick or 1) - 1
        if idx >= len(session.suggestions):
            idx = 0
        session.candidate = session.suggestions[idx]
        session.state = State.CONFIRMING
        session.acks = []
        names = await self._names(session.group_id, session.participants)
        return [cards.confirm(session, session.candidate, [names[u] for u in session.participants])]

    def _end(self, session: Session) -> None:
        self.store.delete_session(session.group_id)
        session.ended = True

    # ------------------------------------------------------------ postbacks
    async def _on_postback(self, gid: str, uid: str, token: str, data: str, now: int) -> None:
        q = {k: v[0] for k, v in parse_qs(data).items()}
        session = self._active(gid, now)
        if session is None or q.get("sid") != session.session_id:
            if q.get("act") in ("ack", "pick", "search", "area"):
                await self.line.reply(token, [cards.text("อันนี้หมดเวลาแล้ว เรียกเราใหม่ได้เลย")])
            return
        act = q.get("act")
        replies: list[Msg] = []
        if act == "stop":
            self._end(session)
            replies = [cards.text("โอเค หยุดฟังละ เรียกใหม่ได้ตลอดนะ")]
        elif act == "pick" and session.state == State.LISTENING:
            if uid not in session.participants:
                session.participants.append(uid)
            replies = await self._confirm(session, int(q.get("i", "1")))
        elif act == "area":
            session.area, session.area_center = q.get("a"), None
            replies = await self._search_replies(session, gid, now)
        elif act == "search":
            replies = await self._search_replies(session, gid, now)
        elif act == "ack" and session.state == State.CONFIRMING:
            replies = self._on_ack(session, uid, q.get("v") == "yes")
        if replies:
            await self.line.reply(token, replies)
        if not session.ended:
            self.store.put_session(session)

    def _on_ack(self, session: Session, uid: str, yes: bool) -> list[Msg]:
        # Rule: any group member may tap, but is registered as a participant FIRST, for both
        # ตกลง and ยังก่อน, so everyone who can affect the confirmation is also counted in it.
        if uid not in session.participants:
            session.participants.append(uid)
        if not yes:
            session.state, session.candidate, session.acks = State.LISTENING, None, []
            return [cards.text("โอเค ยังไม่สรุป คุยกันต่อได้เลย อยากได้แบบไหนบอกมา")]
        if uid not in session.acks:
            session.acks.append(uid)
        if all_acked(session):
            cand = session.candidate
            assert cand is not None
            self._end(session)
            return [cards.plan(session, cand)]
        return [cards.text(f"✅ {len(session.acks)}/{len(session.participants)} คนตกลงแล้ว")]


def all_acked(session: Session) -> bool:
    return bool(session.participants) and set(session.participants) <= set(session.acks)
