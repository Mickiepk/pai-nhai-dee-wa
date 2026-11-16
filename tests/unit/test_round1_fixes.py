"""Permanent regression tests for QA round 1 (BUG-11..20) and the owner's product rules."""

from __future__ import annotations

import pytest

from adapters.llm import RuleExtractor
from adapters.models import LatLng, PlaceCandidate
from features.search import rank
from session.engine import SessionEngine
from session.merge import apply_delta, current_radius, max_price_level
from session.models import Session
from tests.fakes import make_engine

R = RuleExtractor()
CENTER = LatLng(lat=13.78, lng=100.545)


def ext(text: str, mentioned: bool = False):
    return R.extract_sync(text, mentioned=mentioned)


@pytest.mark.parametrize("text", ["ตกลงไปไหนกันแน่", "จบที่ไหนก็ได้", "ไปร้านนี้ไหม", "ไปร้านนี้ป่ะ?", "ร้านไหนดี"])
def test_bug11_questions_are_not_decisions(text):
    assert not ext(text).decision_detected


@pytest.mark.parametrize("text,pick", [("โอเค ไปร้านนี้แหละ", None), ("เอาร้านที่ 2", 2), ("ตกลงไปร้านที่ 3", 3)])
def test_bug11_real_decisions_still_work(text, pick):
    d = ext(text)
    assert d.decision_detected and d.pick_index == pick


@pytest.mark.parametrize("text,km", [("ไม่เกิน 400 ม.", 0.4), ("ภายใน 500 เมตร", 0.5), ("ไม่เกิน 2 กม.", 2.0),
                                      ("within 300 m", 0.3)])
def test_bug13_radius_units(text, km):
    assert ext("หาร้านแถวอารีย์ " + text, True).radius_km == km


def test_bug13_small_radius_is_not_clamped_up():
    s = Session(session_id="x", group_id="g", started_at=0, expires_at=9)
    apply_delta(s, "A", ext("ไม่เกิน 400 ม.", True))
    assert current_radius(s) == 0.4


def test_bug14_between_two_areas_keeps_both():
    d = ext("กินไรดี ตรงกลางระหว่างสยามกับอารีย์", True)
    assert (d.area, d.area2) == ("สยาม", "อารีย์")


def test_bug18_or_picks_first_said_and_no_midpoint():
    d = ext("แถวอโศกหรือสยามก็ได้", True)
    assert (d.area, d.area2) == ("อโศก", None)


@pytest.mark.parametrize("budget,level", [(80, 1), (100, 1), (200, 2), (400, 3), (500, 3), (900, 4)])
def test_bug12_budget_to_price_level(budget, level):
    assert max_price_level(budget) == level


def _cand(pid, price=None, rating=4.5, lat=13.78, lng=100.545):
    return PlaceCandidate(place_id=pid, name=pid, latlng=LatLng(lat=lat, lng=lng), rating=rating, price_level=price)


def test_bug12_budget_filters_but_keeps_unknown_price():
    out = rank([_cand("lux", 4), _cand("mid", 3), _cand("unknown", None)], CENTER, 3, set(), set(), 400)
    assert sorted(c.place_id for c in out) == ["mid", "unknown"]
    assert {c.place_id for c in rank([_cand("lux", 4)], CENTER, 3, set(), set(), None)} == {"lux"}


def test_bug17_ties_break_on_place_id_regardless_of_input_order():
    a, b, c = _cand("a"), _cand("b"), _cand("c")
    for order in ([a, b, c], [c, b, a], [b, c, a]):
        assert [x.place_id for x in rank(order, CENTER, 3, set(), set())] == ["a", "b", "c"]


async def test_bug15_pick_beyond_suggestions_is_refused():
    from scripts.events import text_event
    engine, line, *_ = make_engine()
    await engine.handle(text_event("G", "A", "@bot ไปไหนดีแถวอารีย์ โบว์ลิ่ง"))  # 1 place
    await engine.handle(text_event("G", "B", "เอาร้านที่ 3"))
    sess = engine.store.get_session("G")
    assert sess.candidate is None and sess.state.value == "listening"
    assert "ไม่มีร้านที่ 3" in line.replies[-1][1][0]["text"]


async def test_bug20_session_id_comes_from_injected_factory_and_defaults_to_random():
    from scripts.events import text_event
    ids = iter(["aaaa0001", "aaaa0002"])
    engine, *_ = make_engine()
    engine.id_factory = lambda: next(ids)
    await engine.handle(text_event("G", "A", "@bot กินไรดีแถวอารีย์"))
    assert engine.store.get_session("G").session_id == "aaaa0001"
    e1, *_ = make_engine()
    e2, *_ = make_engine()
    assert isinstance(e1, SessionEngine) and e1.id_factory() != e2.id_factory()


async def test_q02_noise_does_not_make_a_participant_but_real_text_does():
    from scripts.events import text_event
    engine, *_ = make_engine()
    await engine.handle(text_event("G", "A", "@bot กินไรดีแถวอารีย์"))
    for uid, t in (("B", "555"), ("C", "โอเค"), ("D", "https://maps.app.goo.gl/x")):
        await engine.handle(text_event("G", uid, t))
    await engine.handle(text_event("G", "E", "อยากกินชาบูอะ"))
    assert engine.store.get_session("G").participants == ["A", "E"]
