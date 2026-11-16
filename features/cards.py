"""LINE message builders. Casual friend voice, short, always with a button."""

from __future__ import annotations

from typing import Any

from adapters.line import Msg
from features.geo import format_km
from session.models import Session, Suggestion

ATTRIBUTION = "ข้อมูลร้านจาก Google Maps"


def text(t: str, quick: list[tuple[str, str]] | None = None) -> Msg:
    msg: Msg = {"type": "text", "text": t}
    if quick:
        msg["quickReply"] = {"items": [
            {"type": "action", "action": {"type": "postback", "label": label, "data": data,
                                           "displayText": label}}
            for label, data in quick
        ]}
    return msg


def _postback(label: str, data: str, style: str = "secondary") -> dict[str, Any]:
    return {"type": "button", "style": style, "height": "sm",
            "action": {"type": "postback", "label": label, "data": data, "displayText": label}}


def _uri(label: str, uri: str) -> dict[str, Any]:
    return {"type": "button", "style": "link", "height": "sm",
            "action": {"type": "uri", "label": label, "uri": uri}}


def _t(s: str, **kw: Any) -> dict[str, Any]:
    return {"type": "text", "text": s, "wrap": True, **kw}


def _bubble(body: list[dict[str, Any]], footer: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "bubble", "size": "kilo",
            "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": body},
            "footer": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": footer}}


def flex(alt: str, contents: dict[str, Any]) -> Msg:
    return {"type": "flex", "altText": alt[:400], "contents": contents}


def listening_notice(session: Session, minutes: int) -> Msg:
    body = [
        _t("👂 เปิดโหมดช่วยคิดละ", weight="bold"),
        _t(f"เราจะอ่านแชตกลุ่มนี้ไม่เกิน {minutes} นาที เพื่อจำว่าใครอยากกินอะไร "
           "ไม่เก็บข้อความ เก็บแค่สรุปความชอบ", size="sm", color="#666666"),
    ]
    return flex(f"เราจะฟังแชตกลุ่มนี้ไม่เกิน {minutes} นาที กด หยุดฟัง ได้ตลอด",
                _bubble(body, [_postback("หยุดฟัง", f"act=stop&sid={session.session_id}")]))


def suggestions(session: Session, items: list[Suggestion], header: str) -> list[Msg]:
    area = session.area or "จุดที่บอก"
    bubbles = []
    for i, s in enumerate(items, start=1):
        body = [
            _t(f"{i}. {s.name}", weight="bold", size="md"),
            _t(f"{format_km(s.distance_km)} จาก{area}", size="sm", color="#1DB446"),
            _t(ATTRIBUTION, size="xxs", color="#999999"),
        ]
        footer = [
            _uri("แผนที่", s.maps_url),
            _postback("เอาร้านนี้", f"act=pick&i={i}&sid={session.session_id}", "primary"),
        ]
        bubbles.append(_bubble(body, footer))
    alt = header + " " + " / ".join(s.name for s in items)
    return [text(header), flex(alt, {"type": "carousel", "contents": bubbles})]


def confirm(session: Session, cand: Suggestion, names: list[str]) -> Msg:
    sid = session.session_id
    body = [
        _t("สรุปว่าไปที่นี่นะ?", weight="bold"),
        _t(cand.name, size="lg", weight="bold"),
        _t(f"{format_km(cand.distance_km)} จาก{session.area or 'จุดที่บอก'}", size="sm", color="#1DB446"),
        _t("รอทุกคนกดตกลง: " + ", ".join(names), size="sm", color="#666666"),
    ]
    footer = [_postback("ตกลง ✅", f"act=ack&v=yes&sid={sid}", "primary"),
              _postback("ยังก่อน", f"act=ack&v=no&sid={sid}")]
    return flex(f"ไป {cand.name} ไหม? กดตกลงกันหน่อย", _bubble(body, footer))


def plan(session: Session, cand: Suggestion) -> Msg:
    body = [
        _t("🎉 จบ! ได้ที่ไปละ", weight="bold"),
        _t(cand.name, size="lg", weight="bold"),
        _t(f"{format_km(cand.distance_km)} จาก{session.area or 'จุดที่บอก'} (ระยะเส้นตรง)", size="sm"),
        _t(f"เวลา: {session.when}" if session.when else "เวลา: ยังไม่ได้นัด ตกลงกันในแชตเลย", size="sm"),
        _t(ATTRIBUTION, size="xxs", color="#999999"),
    ]
    return flex(f"แผน: {cand.name}", _bubble(body, [_uri("เปิดแผนที่", cand.maps_url)]))


def announcement(session: Session, names: dict[str, str]) -> Msg:
    lines = ["📣 สรุปตอนนี้"]
    if session.area:
        lines.append(f"ย่าน: {session.area}")
    if session.group_wants:
        lines.append("อยากได้: " + ", ".join(session.group_wants[-3:]))
    for uid, p in session.prefs.items():
        bits = []
        if p.likes:
            bits.append("ชอบ " + ", ".join(p.likes[-2:]))
        if p.dislikes:
            bits.append("ไม่เอา " + ", ".join(p.dislikes[-2:]))
        if p.just_ate:
            bits.append("เพิ่งกิน " + ", ".join(p.just_ate[-2:]))
        if bits:
            lines.append(f"• {names.get(uid, 'เพื่อน')}: " + " · ".join(bits))
    if session.candidate:
        lines.append(f"ตัวเต็ง: {session.candidate.name}")
    return text("\n".join(lines), [("หาร้านให้หน่อย", f"act=search&sid={session.session_id}")])


def vote_stub(session: Session) -> Msg:
    return text("โหวตใช้โพลของ LINE ได้เลยนะ (กด + แล้วเลือก โพล) ไวกว่า 😎 "
                "หรือกด เอาร้านนี้ ใต้การ์ดร้านก็ได้")
