"""Session engine: one LINE event in, zero or more replies out.

States per group: (none) -> LISTENING <-> CONFIRMING -> (ended). See docs/ARCHITECTURE.md.
The bot SPEAKS only when @mentioned, on a decision, or on a button tap, always via that
event's reply token. Raw chat text is never stored or logged.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs

from adapters.line import LineGateway, Msg
from adapters.llm import Extractor, GeminiExtractor, RuleExtractor, looks_undecided
from adapters.models import MessageDelta
from adapters.places import Places
from config import Settings
from features import cards, search
from features.geo import format_radius
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
CANCELLED = "ยกเลิกการ์ดยืนยันเดิมแล้ว กลับมาหาร้านใหม่กันนะ"
STALE_CARD = "การ์ดยืนยันนี้ถูกยกเลิกแล้ว ดูการ์ดล่าสุดหรือเรียกเราใหม่ได้เลย"


def new_session_id() -> str:
    """Default id source: random in production. Tests inject a deterministic factory (BUG-20)."""
    return uuid.uuid4().hex[:8]


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
                 places: Places, clock: Callable[[], int] = lambda: int(time.time()),
                 id_factory: Callable[[], str] = new_session_id):
        self.s = settings
        self.store = store
        self.line = line
        self.llm = llm
        self.rules = RuleExtractor()
        self.places = places
        self.clock = clock
        self.id_factory = id_factory
        self._warned_unpaid = False

    # ------------------------------------------------------------ PDPA guard (Q-06, fail closed)
    def _uses_gemini(self) -> bool:
        return self.s.llm_provider == "gemini" or isinstance(self.llm, GeminiExtractor)

    def _gemini_allowed(self) -> bool:
        """Chat text may go to Gemini only on the paid tier: env GEMINI_PAID_TIER=true (or the legacy
        Settings flag). Anything else = fail closed."""
        if not self._uses_gemini():
            return True
        return os.environ.get("GEMINI_PAID_TIER", "").strip().lower() == "true" or bool(
            self.s.gemini_paid_tier_confirmed)

    def _chat_reading(self) -> bool:
        return self._gemini_allowed()  # offline rules always allowed; Gemini only when paid

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
        if not self._gemini_allowed():  # PDPA: never send chat text to Gemini without the paid tier
            if not self._warned_unpaid:
                self._warned_unpaid = True
                log.warning("GEMINI_PAID_TIER is not true: chat text is NOT sent to Gemini, offline rules only")
            return self.rules.extract_sync(text, mentioned=mentioned)
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
        return Session(session_id=self.id_factory(), group_id=gid, started_at=now,
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

        new_participant = False
        if not mentioned:
            readable = worth_reading(message.get("type", ""), message.get("text"))
            # Q-01/Q-02: a participant sent at least one non-prefiltered message (555/stickers don't count)
            if readable and uid not in session.participants:
                session.participants.append(uid)
                new_participant = True
            if not (self._chat_reading() and readable):
                replies0 = (await self._repost_confirm(session)
                            if new_participant and session.state == State.CONFIRMING else [])
                if replies0:
                    await self.line.reply(token, replies0)
                self.store.put_session(session)
                return
        elif uid not in session.participants:
            new_participant = True

        text = strip_mentions(message) if mentioned else message.get("text", "")
        delta = await self._extract(session, text, mentioned)
        if delta.decision_detected and looks_undecided(text):
            delta.decision_detected = False  # questions/open answers are never decisions, whatever the LLM said
        apply_delta(session, uid, delta)
        replies: list[Msg] = []

        if delta.decision_detected and session.suggestions and session.state == State.LISTENING:
            replies = await self._confirm(session, delta.pick_index)
        elif mentioned:
            replies = await self._answer_mention(session, delta)
        if (new_participant and session.state == State.CONFIRMING and session.candidate is not None
                and not any(_is_confirm_card(m) for m in replies)):
            replies += await self._repost_confirm(session)  # Q-03

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
            return await self._replan_search(session, session.group_id, self.clock(),
                                             exclude_last=delta.rejects_last_suggestion)
        return [cards.text("ฟังอยู่นะ อยากให้หาอะไรเพิ่มก็เรียกได้เลย")]

    def _cancel_confirming(self, session: Session) -> None:
        session.state, session.candidate, session.acks = State.LISTENING, None, []
        session.confirm_round += 1  # buttons on the old card are now dead

    async def _replan_search(self, session: Session, gid: str, now: int, *, exclude_last: bool = False) -> list[Msg]:
        """A new search during the ack wait cancels confirming and goes back to planning (Q-08)."""
        prefix: list[Msg] = []
        if session.state == State.CONFIRMING:
            self._cancel_confirming(session)
            prefix = [cards.text(CANCELLED)]
        return prefix + await self._search_replies(session, gid, now, exclude_last=exclude_last)

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
            return [cards.text(f"หาพิกัด{session.area_label}ไม่เจอ ลองเลือกย่านใกล้ๆ ดูนะ",
                               [(a, f"act=area&a={a}&sid={session.session_id}") for a in AREA_CHOICES])]
        if outcome.error == "places_failed":
            return [cards.text("ตอนนี้ค้นร้านไม่ได้ ลองเรียกใหม่อีกทีนะ")]
        if outcome.error == "not_found":
            reach = f"{format_radius(outcome.radius_km)} จาก{session.area_label}"
            return [cards.text(f"ใน {reach} ไม่เจอที่ตรงเงื่อนไขเลย ลองเปลี่ยนแบบดูไหม?")]
        session.suggestions = outcome.suggestions
        reach = f"{format_radius(outcome.radius_km)} จาก{session.area_label}"
        header = f"ได้ {len(outcome.suggestions)} ที่ละ ทุกที่ไม่เกิน {reach}"
        avoid = avoid_terms(session)
        if avoid:
            header += f"\n(ข้าม{'/'.join(sorted(avoid))}ให้ละ มีคนไม่เอาหรือเพิ่งกิน)"
        return cards.suggestions(session, outcome.suggestions, header)

    async def _confirm(self, session: Session, pick: int | None) -> list[Msg]:
        idx = (pick or 1) - 1
        if idx < 0 or idx >= len(session.suggestions):  # BUG-15: never confirm a different place silently
            n = len(session.suggestions)
            return [cards.text(f"ไม่มีร้านที่ {pick} นะ ตอนนี้มีให้เลือก {n} ที่ เลือกใหม่ได้เลย")]
        session.candidate = session.suggestions[idx]
        session.state = State.CONFIRMING
        session.acks = []
        session.confirm_round += 1
        return await self._repost_confirm(session)

    async def _repost_confirm(self, session: Session) -> list[Msg]:
        """(Re)post the confirmation card with the CURRENT participant list; acks are kept."""
        assert session.candidate is not None
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
            i = q.get("i", "1")
            replies = await self._confirm(session, int(i) if i.isdigit() else 0)
        elif act == "area":
            session.area, session.area2, session.area_center = q.get("a"), None, None
            replies = await self._replan_search(session, gid, now)
        elif act == "search":
            replies = await self._replan_search(session, gid, now)
        elif act == "ack":
            if "r" in q and q["r"] != str(session.confirm_round):
                replies = [cards.text(STALE_CARD)]  # card from a cancelled/older round (Q-08)
            elif session.state == State.CONFIRMING:
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
            self._cancel_confirming(session)
            return [cards.text("โอเค ยังไม่สรุป คุยกันต่อได้เลย อยากได้แบบไหนบอกมา")]
        if uid not in session.acks:
            session.acks.append(uid)
        if all_acked(session):
            cand = session.candidate
            assert cand is not None
            self._end(session)
            return [cards.plan(session, cand)]
        return [cards.text(f"✅ {len(session.acks)}/{len(session.participants)} คนตกลงแล้ว")]


def _is_confirm_card(msg: Msg) -> bool:
    return msg.get("type") == "flex" and str(msg.get("altText", "")).endswith("กดตกลงกันหน่อย")


def all_acked(session: Session) -> bool:
    return bool(session.participants) and set(session.participants) <= set(session.acks)
