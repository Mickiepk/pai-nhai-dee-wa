"""End-to-end session behaviour with fakes (no network, no money)."""

from scripts.events import postback_event, sticker_event, text_event
from session.models import State
from tests.fakes import make_engine

G = "Cgroup1"


def _texts(line) -> list[str]:
    """Flatten every reply into searchable text."""
    from scripts.render import render

    return [render(m) for _t, msgs in line.replies for m in msgs]


async def test_ari_buffet_scenario():
    engine, line, llm, places, _ = make_engine()

    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    first = line.replies[-1][1]
    assert "60 นาที" in first[0]["altText"] and "หยุดฟัง" in str(first[0])  # PDPA notice
    session = engine.store.get_session(G)
    assert session.area == "อารีย์" and len(session.suggestions) == 3
    assert all(s.distance_km <= 3 for s in session.suggestions)  # Haversine filter

    n_replies = len(line.replies)
    await engine.handle(text_event(G, "A", "ไม่เอาอันนี้ อยากกินญี่ปุ่น"))
    await engine.handle(text_event(G, "B", "เพิ่งกินญี่ปุ่นมา เอาเกาหลีได้ไหม"))
    await engine.handle(sticker_event(G, "B"))
    await engine.handle(text_event(G, "B", "555"))
    await engine.handle(text_event(G, "C", "ไปบุฟเฟต์นานาชาติกันดีกว่า"))
    assert len(line.replies) == n_replies  # bot stays silent while listening
    assert llm.calls == 4  # start + 3 real messages; sticker and 555 filtered

    await engine.handle(text_event(G, "C", "@bot แถวอารีย์มีบุฟเฟต์นานาชาติไหม"))
    session = engine.store.get_session(G)
    assert session.prefs["A"].likes == ["ญี่ปุ่น"] and session.prefs["B"].just_ate == ["ญี่ปุ่น"]
    names = [s.name for s in session.suggestions]
    assert names == ["[ตัวอย่าง] เวิลด์บุฟเฟต์ พหลโยธิน"]  # buffet near Ari, far Bangna one dropped
    assert "บุฟเฟต์นานาชาติ อารีย์" in places.calls[-1]  # searched with accumulated state
    assert "ข้ามญี่ปุ่น" in _texts(line)[-2]  # notes A/B's Japanese preference conflict

    await engine.handle(text_event(G, "B", "โอเค ไปร้านนี้แหละ"))
    confirm = _texts(line)[-1]
    assert "เอ, บี, ซี" in confirm and "ตกลง ✅" in confirm and "ยังก่อน" in confirm
    assert engine.store.get_session(G).state == State.CONFIRMING

    sid = engine.store.get_session(G).session_id
    for user in ("A", "B"):
        await engine.handle(postback_event(G, user, f"act=ack&v=yes&sid={sid}"))
    assert engine.store.get_session(G) is not None  # C has not confirmed yet
    await engine.handle(postback_event(G, "C", f"act=ack&v=yes&sid={sid}"))
    plan = _texts(line)[-1]
    assert "เวิลด์บุฟเฟต์" in plan and "~510 ม. จากอารีย์" in plan
    assert "เปิดแผนที่" in plan
    assert engine.store.get_session(G) is None  # session ended


async def test_not_yet_lets_session_continue():
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", "โอเค ไปร้านนี้แหละ"))
    sid = engine.store.get_session(G).session_id
    await engine.handle(postback_event(G, "B", f"act=ack&v=no&sid={sid}"))
    assert engine.store.get_session(G).state == State.LISTENING
    await engine.handle(text_event(G, "A", "@bot อยากกินเกาหลี"))
    assert "ปิ้งย่างโซล" in _texts(line)[-1]


async def test_stop_button_and_expiry():
    engine, line, llm, _, clock = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    sid = engine.store.get_session(G).session_id
    await engine.handle(postback_event(G, "A", f"act=stop&sid={sid}"))
    assert engine.store.get_session(G) is None
    calls = llm.calls
    await engine.handle(text_event(G, "B", "อยากกินชาบูมาก"))
    assert llm.calls == calls  # no session -> chat is not read

    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวสยาม"))
    clock.now += 61 * 60
    await engine.handle(text_event(G, "B", "อยากกินชาบูมาก"))
    assert engine.store.get_session(G) is None and llm.calls == calls + 1


async def test_no_session_without_planning_intent():
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot หวัดดี"))
    assert engine.store.get_session(G) is None and "เรียกเรา" in _texts(line)[-1]


async def test_asks_area_when_missing():
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดี"))
    assert "แถวไหน" in _texts(line)[-1]
    sid = engine.store.get_session(G).session_id
    await engine.handle(postback_event(G, "A", f"act=area&a=อารีย์&sid={sid}"))
    assert len(engine.store.get_session(G).suggestions) == 3


async def test_duplicate_event_is_processed_once():
    engine, line, *_ = make_engine()
    ev = text_event(G, "A", "@bot กินไรดีแถวอารีย์")
    await engine.handle(ev)
    await engine.handle(ev)
    assert len(line.replies) == 1


async def test_announce_and_vote_are_on_request_only():
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", "ไม่อยากกินชาบู"))
    await engine.handle(text_event(G, "A", "@bot ประกาศหน่อย"))
    assert "📣" in _texts(line)[-1] and "บี: ไม่เอา ชาบู" in _texts(line)[-1]
    await engine.handle(text_event(G, "A", "@bot โหวตหน่อย"))
    assert "โพล" in _texts(line)[-1]


async def test_raw_chat_text_is_never_stored():
    engine, *_ = make_engine()
    secret_line = "ไม่เอาอันนี้ อยากกินญี่ปุ่น เบอร์ฉัน0812345678"
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", secret_line))
    stored = engine.store.sessions[G]
    assert "0812345678" not in stored and secret_line not in stored


async def test_unknown_area_asks_again_instead_of_empty_card():
    """QA regression: area the rules know but AREA_CENTERS lacks (บางนา) + geocode miss."""
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวบางนา"))
    last = _texts(line)[-1]
    assert "หาพิกัดบางนาไม่เจอ" in last
    assert "ได้ 0 ที่" not in "".join(_texts(line))
