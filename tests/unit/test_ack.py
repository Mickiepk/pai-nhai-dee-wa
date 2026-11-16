from adapters.models import LatLng
from scripts.events import postback_event
from session.engine import all_acked
from session.models import Session, State, Suggestion
from tests.fakes import make_engine

CAND = Suggestion(place_id="p1", name="ร้าน A", latlng=LatLng(lat=13.78, lng=100.54), distance_km=0.5,
                  maps_url="https://maps.example/p1")


def _confirming(engine) -> Session:
    s = Session(session_id="sid1", group_id="G", started_at=engine.clock(),
                expires_at=engine.clock() + 3600, participants=["A", "B"], state=State.CONFIRMING,
                suggestions=[CAND], candidate=CAND, area="อารีย์")
    engine.store.put_session(s)
    return s


def test_all_acked():
    s = Session(session_id="x", group_id="g", started_at=0, expires_at=1, participants=["A", "B"])
    assert not all_acked(s)
    s.acks = ["B", "A"]
    assert all_acked(s)
    s.participants = []
    assert not all_acked(s)


async def test_plan_only_after_everyone_acks():
    engine, line, *_ = make_engine()
    _confirming(engine)
    await engine.handle(postback_event("G", "A", "act=ack&v=yes&sid=sid1"))
    await engine.handle(postback_event("G", "A", "act=ack&v=yes&sid=sid1"))  # double tap
    assert engine.store.get_session("G").acks == ["A"]
    await engine.handle(postback_event("G", "B", "act=ack&v=yes&sid=sid1"))
    assert line.replies[-1][1][0]["altText"] == "แผน: ร้าน A"
    assert engine.store.get_session("G") is None


async def test_not_yet_returns_to_listening():
    engine, line, *_ = make_engine()
    _confirming(engine)
    await engine.handle(postback_event("G", "A", "act=ack&v=yes&sid=sid1"))
    await engine.handle(postback_event("G", "B", "act=ack&v=no&sid=sid1"))
    s = engine.store.get_session("G")
    assert s.state == State.LISTENING and s.acks == [] and s.candidate is None


async def test_stale_card_is_ignored():
    engine, line, *_ = make_engine()
    _confirming(engine)
    await engine.handle(postback_event("G", "A", "act=ack&v=yes&sid=OLD"))
    assert engine.store.get_session("G").acks == []
    assert "หมดเวลา" in line.replies[-1][1][0]["text"]
