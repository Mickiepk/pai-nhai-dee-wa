"""Budget guards and privacy switches."""

from scripts.events import text_event
from tests.fakes import make_engine

G = "Cgroup2"


async def test_llm_cap_per_session_falls_back_to_free_rules():
    engine, line, llm, *_ = make_engine(max_llm_calls_per_session=3)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    for i in range(5):
        await engine.handle(text_event(G, "B", f"อยากกินชาบู รอบ {i}"))
    assert llm.calls == 3
    assert engine.store.get_session(G).prefs["B"].likes == ["ชาบู"]  # rules still worked


async def test_daily_search_cap_per_group():
    engine, line, _, places, _ = make_engine(max_searches_per_group_per_day=2)
    for _i in range(3):
        await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    assert len(places.calls) == 2
    assert "ครบ 2 ครั้ง" in line.replies[-1][1][0]["text"]


async def test_global_places_cap():
    engine, line, _, places, _ = make_engine(max_places_calls_per_day=1)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event("Cother", "A", "@bot กินไรดีแถวอารีย์"))
    assert len(places.calls) == 1 and "โควตา" in line.replies[-1][1][-1]["text"]


async def test_kill_switch_silences_bot():
    engine, line, llm, *_ = make_engine(bot_enabled=False)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    assert line.replies == [] and llm.calls == 0


async def test_gemini_without_paid_tier_never_sends_chat_text(monkeypatch, caplog):
    """Q-06 (PDPA, fail closed): not the paid tier -> no text to Gemini at all, not even @mentions."""
    monkeypatch.delenv("GEMINI_PAID_TIER", raising=False)
    engine, line, llm, *_ = make_engine(llm_provider="gemini", gemini_paid_tier_confirmed=False)
    assert not engine.s.chat_reading_enabled
    with caplog.at_level("WARNING"):
        await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
        await engine.handle(text_event(G, "B", "อยากกินชาบูมาก"))
        await engine.handle(text_event(G, "A", "@bot มีร้านเกาหลีไหม"))
    assert llm.calls == 0  # nothing went to the (fake) Gemini
    assert "ได้ 3 ที่ละ" in line.replies[0][1][1]["text"]  # offline rules still answer the @mention
    assert "B" in engine.store.get_session(G).participants  # still counted as participant
    warns = [r for r in caplog.records if "GEMINI_PAID_TIER" in r.getMessage()]
    assert len(warns) == 1  # one-line warning, logged once


async def test_gemini_paid_tier_env_must_be_exactly_true(monkeypatch):
    for value in ("false", "1", "yes", ""):
        monkeypatch.setenv("GEMINI_PAID_TIER", value)
        engine, _line, llm, *_ = make_engine(llm_provider="gemini")
        await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
        assert llm.calls == 0, value
    monkeypatch.setenv("GEMINI_PAID_TIER", "true")
    engine, _line, llm, *_ = make_engine(llm_provider="gemini")
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    assert llm.calls == 1


async def test_offline_rules_provider_is_not_gated(monkeypatch):
    monkeypatch.delenv("GEMINI_PAID_TIER", raising=False)
    engine, _line, llm, *_ = make_engine()  # llm_provider=fake: nothing leaves the process
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    assert llm.calls == 1


async def test_gemini_with_paid_tier_reads_chat():
    engine, line, llm, *_ = make_engine(llm_provider="gemini", gemini_paid_tier_confirmed=True)
    await engine.handle(text_event(G, "A", "@bot กินไรดีแถวอารีย์"))
    await engine.handle(text_event(G, "B", "อยากกินชาบูมาก"))
    assert llm.calls == 2
