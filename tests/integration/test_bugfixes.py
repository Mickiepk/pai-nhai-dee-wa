"""Regression tests for the pre-ship bug list (radius, ack rule, wording, logs, geocode cap)."""

import logging

from adapters.models import MessageDelta
from scripts.events import postback_event, text_event
from scripts.render import render
from session.models import State
from tests.fakes import make_engine

G = "Cbug"


def _last(line) -> str:
    return "".join(render(m) for m in line.replies[-1][1])


async def test_radius_phrases_end_to_end_latest_wins():
    engine, line, _, places, _ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", "ไม่เกิน 5 โล"))
    assert engine.store.get_session(G).radius_km == 5.0
    await engine.handle(text_event(G, "A", "@bot ไกลไป"))
    assert engine.store.get_session(G).radius_km == 2.5
    assert "ไม่เกิน 2.5 กม." in _last(line)
    await engine.handle(text_event(G, "C", "within 1 km"))
    await engine.handle(text_event(G, "A", "ไกลไป"))
    assert engine.store.get_session(G).radius_km == 1.0  # min 1 km


async def test_radius_via_llm_delta_path_and_distance_filter():
    engine, line, llm, *_ = make_engine()

    class DeltaLLM:
        async def extract(self, text, *, mentioned, context):
            return MessageDelta(intent="food", area="อารีย์", radius_km=1, asks_bot=True, request="search")

    engine.llm = DeltaLLM()
    await engine.handle(text_event(G, "A", "@bot whatever"))
    s = engine.store.get_session(G)
    assert s.radius_km == 1.0 and all(x.distance_km <= 1 for x in s.suggestions)

    class HalveLLM(DeltaLLM):
        async def extract(self, text, *, mentioned, context):
            return MessageDelta(radius_halve=True)

    engine.llm = HalveLLM()
    await engine.handle(text_event(G, "B", "far"))
    assert engine.store.get_session(G).radius_km == 1.0  # floor


async def _confirming(engine):
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", "โอเค ไปร้านนี้แหละ"))
    return engine.store.get_session(G).session_id


async def test_stranger_tapping_not_yet_is_registered_then_cancels():
    engine, line, *_ = make_engine()
    sid = await _confirming(engine)
    assert "Z" not in engine.store.get_session(G).participants
    await engine.handle(postback_event(G, "Z", f"act=ack&v=no&sid={sid}"))
    s = engine.store.get_session(G)
    assert s.state == State.LISTENING and "Z" in s.participants


async def test_stranger_tapping_yes_is_registered_and_required():
    engine, line, *_ = make_engine()
    sid = await _confirming(engine)
    await engine.handle(postback_event(G, "Z", f"act=ack&v=yes&sid={sid}"))
    s = engine.store.get_session(G)
    assert "Z" in s.participants and s.acks == ["Z"]
    assert "1/3" in _last(line)  # A, B, Z now all needed
    for u in ("A", "B"):
        await engine.handle(postback_event(G, u, f"act=ack&v=yes&sid={sid}"))
    assert engine.store.get_session(G) is None  # plan done


async def test_notice_wording_follows_intent():
    engine, line, *_ = make_engine()
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    assert "ใครอยากกินอะไร" in render(line.replies[-1][1][0])
    engine2, line2, *_ = make_engine()
    await engine2.handle(text_event(G, "A", "@bot ไปทำไรดีแถวอารีย์"))
    notice = render(line2.replies[-1][1][0])
    assert "ใครอยากทำอะไร" in notice and "กินอะไร" not in notice


async def test_geocode_counts_against_places_cap():
    # บางนา is not in AREA_CENTERS -> geocode (1 call) then, if allowed, search_text
    engine, line, _, places, _ = make_engine(max_places_calls_per_day=1)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวบางนา"))
    assert places.calls == ["geocode:บางนา"]  # geocode used the only call
    engine2, line2, _, places2, _ = make_engine(max_places_calls_per_day=2)
    await engine2.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))  # known area: 1 call
    await engine2.handle(text_event(G, "A", "@bot กินไรดีแถวบางนา"))  # geocode = call 2
    assert places2.calls[-1] == "geocode:บางนา"
    await engine2.handle(text_event(G, "A", "@bot กินไรดีแถวบางนา"))  # cap reached
    assert "โควตา" in _last(line2) and len(places2.calls) == 2


async def test_geocode_cap_blocks_before_any_call():
    engine, line, _, places, _ = make_engine(max_places_calls_per_day=0)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวบางนา"))
    assert places.calls == [] and "โควตา" in _last(line)


def test_local_server_error_log_has_no_chat_text(caplog):
    from scripts import local_server

    class Boom:
        async def handle(self, ev):
            raise ValueError("bad input: เบอร์ฉัน0812345678")

    secret = "เบอร์ฉัน0812345678"
    with caplog.at_level(logging.DEBUG):
        ok = local_server.run_event(Boom(), text_event(G, "A", secret))
    assert ok is False
    out = caplog.text
    assert secret not in out and "0812345678" not in out and "Traceback" not in out
    assert "ValueError" in out


def test_worker_error_log_has_no_chat_text(caplog, monkeypatch):
    import json

    from handlers import worker

    class Boom:
        async def handle(self, ev):
            raise ValueError("เบอร์ฉัน0812345678")

    monkeypatch.setattr(worker, "_engine", Boom())
    ev = text_event(G, "A", "เบอร์ฉัน0812345678")
    with caplog.at_level(logging.DEBUG):
        res = worker.handler({"Records": [{"messageId": "m1", "body": json.dumps(ev, ensure_ascii=False)}]}, None)
    assert res == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert "0812345678" not in caplog.text


def test_no_log_call_in_source_interpolates_text():
    """Static guard: handlers/, session/, adapters/, scripts/local_server.py never log text-like names."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    files = [*root.glob("handlers/*.py"), *root.glob("session/*.py"), *root.glob("adapters/*.py"),
             *root.glob("features/*.py"), root / "scripts" / "local_server.py"]
    bad = re.compile(r"(?:log|logger)\.\w+\(\s*[\"'][^\"']*[\"']\s*,[^)]*\b(?:text|msg|message|body|payload)\b|"
                     r"\.exception\(|exc_info")
    hits = [f"{f.name}: {m.group(0)}" for f in files for m in bad.finditer(f.read_text(encoding="utf-8"))]
    assert not hits, hits
