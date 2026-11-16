from adapters.models import MessageDelta
from session.merge import apply_delta, avoid_terms, group_budget
from session.models import Session


def _s() -> Session:
    return Session(session_id="s", group_id="g", started_at=0, expires_at=3600)


def test_tracks_participants_in_order():
    s = _s()
    apply_delta(s, "B", MessageDelta())
    apply_delta(s, "A", MessageDelta())
    apply_delta(s, "B", MessageDelta())
    assert s.participants == ["B", "A"]


def test_latest_wins_per_user():
    s = _s()
    apply_delta(s, "A", MessageDelta(likes=["ญี่ปุ่น"]))
    apply_delta(s, "A", MessageDelta(dislikes=["ญี่ปุ่น"]))
    assert s.prefs["A"].likes == [] and s.prefs["A"].dislikes == ["ญี่ปุ่น"]


def test_just_ate_is_avoided_and_removed_from_group_wants():
    s = _s()
    apply_delta(s, "A", MessageDelta(likes=["ญี่ปุ่น"]))
    apply_delta(s, "B", MessageDelta(just_ate=["ญี่ปุ่น"], likes=["เกาหลี"]))
    apply_delta(s, "C", MessageDelta(likes=["บุฟเฟต์นานาชาติ"]))
    assert s.group_wants == ["เกาหลี", "บุฟเฟต์นานาชาติ"]
    assert avoid_terms(s) == {"ญี่ปุ่น"}


def test_latest_group_want_is_not_avoided():
    s = _s()
    apply_delta(s, "A", MessageDelta(dislikes=["ชาบู"]))
    apply_delta(s, "B", MessageDelta(likes=["ชาบู"]))
    assert avoid_terms(s) == set()


def test_area_change_resets_center_and_budget_is_min():
    s = _s()
    apply_delta(s, "A", MessageDelta(area="สยาม", budget_max_thb=500))
    s.area_center = None
    apply_delta(s, "B", MessageDelta(area="อารีย์", budget_max_thb=300))
    assert s.area == "อารีย์" and group_budget(s) == 300
