"""Slang/typo/English normalisation, radius phrases (rules + LLM-delta merge), .env loader."""

import pytest

from adapters.lexicon import normalize
from adapters.llm import RuleExtractor
from adapters.models import MessageDelta
from config import load_dotenv
from session.merge import apply_delta
from session.models import Session

r = RuleExtractor()


def _s(kind: str = "food") -> Session:
    return Session(session_id="s", group_id="g", started_at=0, expires_at=3600, kind=kind)


@pytest.mark.parametrize("text,likes", [
    ("อยากกิน japanese", ["ญี่ปุ่น"]),
    ("อยากกิน Japanese food", ["ญี่ปุ่น"]),
    ("ญี่ปุ่นดีกว่า", ["ญี่ปุ่น"]),
    ("เอาญป", ["ญี่ปุ่น"]),
    ("buffet ไหม", ["บุฟเฟต์"]),
    ("บุฟเฟ่ต์ดีไหม", ["บุฟเฟต์"]),
    ("บุฟเฟ่", ["บุฟเฟต์"]),
    ("international บุฟเฟ่ต์นานาชาติ", ["บุฟเฟต์นานาชาติ"]),
    ("korean bbq", ["เกาหลี", "ปิ้งย่าง"]),
    ("ไปโบลิ่งกัน", ["โบว์ลิ่ง"]),
])
def test_slang_typos_and_english(text, likes):
    assert r.extract_sync(text, mentioned=False).likes == likes


def test_negation_and_just_ate_work_with_variants():
    assert r.extract_sync("ไม่เอา japanese", mentioned=False).dislikes == ["ญี่ปุ่น"]
    assert r.extract_sync("เพิ่งกิน sushi มา", mentioned=False).just_ate == ["ซูชิ"]


def test_english_area_and_whole_word_only():
    assert r.extract_sync("@bot eat near siam", mentioned=True).area == "สยาม"
    assert normalize("thailand trip") == "thailand trip"  # "thai" must not match inside a word
    assert "เจอ" in normalize("เจอกัน")  # no accidental rewrites of ordinary words


def test_normalize_is_deterministic():
    assert normalize("Buffet บุฟเฟ่ JAPANESE") == normalize("buffet บุฟเฟ่ japanese") == "บุฟเฟต์ บุฟเฟต์ ญี่ปุ่น"


@pytest.mark.parametrize("text", ["ไม่เกิน 5 กม.", "ไม่เกิน 5 โล", "ไม่เกิน 5 กิโล", "within 5 km", "Within 5KM"])
def test_radius_set_phrases(text):
    d = r.extract_sync(text, mentioned=False)
    assert d.radius_km == 5.0 and not d.radius_halve


def test_far_phrase_halves():
    d = r.extract_sync("ไกลไปอะ", mentioned=False)
    assert d.radius_halve and d.radius_km is None


def test_mention_with_radius_requests_search():
    assert r.extract_sync("@bot ไกลไป", mentioned=True).request == "search"


def test_merge_halve_min_1_and_latest_wins():
    s = _s()
    apply_delta(s, "A", MessageDelta(radius_halve=True))
    assert s.radius_km == 1.5  # food default 3 -> 1.5
    apply_delta(s, "A", MessageDelta(radius_halve=True))
    assert s.radius_km == 1.0  # 0.75 -> floor at 1
    apply_delta(s, "B", MessageDelta(radius_km=5))
    assert s.radius_km == 5.0
    apply_delta(s, "A", MessageDelta(radius_halve=True))
    assert s.radius_km == 2.5
    apply_delta(s, "C", MessageDelta(radius_km=4))
    assert s.radius_km == 4.0


def test_merge_halve_uses_activity_default():
    s = _s("activity")
    apply_delta(s, "A", MessageDelta(radius_halve=True))
    assert s.radius_km == 2.5


def test_load_dotenv(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nFOO_A=1\nexport FOO_B="two words"\nFOO_C=x # note\nFOO_D=keep\n', encoding="utf-8")
    monkeypatch.setenv("FOO_D", "real")
    for k in ("FOO_A", "FOO_B", "FOO_C"):
        monkeypatch.delenv(k, raising=False)
    assert load_dotenv(f)
    import os
    assert (os.environ["FOO_A"], os.environ["FOO_B"], os.environ["FOO_C"]) == ("1", "two words", "x")
    assert os.environ["FOO_D"] == "real"  # real env wins
    for k in ("FOO_A", "FOO_B", "FOO_C"):
        os.environ.pop(k, None)
    assert not load_dotenv(tmp_path / "missing.env")
