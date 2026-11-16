"""Merge an LLM MessageDelta into the session. Plain code, deterministic."""

from __future__ import annotations

from adapters.models import MessageDelta
from features import activity, food
from session.models import Session, UserPrefs

MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 50.0


def clamp_radius(km: float) -> float:
    return min(MAX_RADIUS_KM, max(0.5, km))


def current_radius(session: Session) -> float:
    if session.radius_km:
        return session.radius_km
    return activity.RADIUS_KM if session.kind == "activity" else food.RADIUS_KM


def _add(items: list[str], new: list[str]) -> None:
    for x in new:
        if x in items:
            items.remove(x)
        items.append(x)  # most recent last


def _drop(items: list[str], gone: list[str]) -> None:
    for x in gone:
        if x in items:
            items.remove(x)


def apply_delta(session: Session, user_id: str, delta: MessageDelta) -> Session:
    """Latest statement wins per topic; different topics accumulate."""
    if user_id not in session.participants:
        session.participants.append(user_id)
    prefs = session.prefs.setdefault(user_id, UserPrefs())

    _add(prefs.likes, delta.likes)
    _drop(prefs.likes, delta.dislikes + delta.just_ate)
    _add(prefs.dislikes, delta.dislikes)
    _drop(prefs.dislikes, delta.likes)
    _add(prefs.just_ate, delta.just_ate)
    if delta.budget_max_thb:
        prefs.budget_max_thb = delta.budget_max_thb

    _add(session.group_wants, delta.likes)
    _drop(session.group_wants, delta.dislikes + delta.just_ate)
    if delta.area:
        if delta.area != session.area:
            session.area_center = None
        session.area = delta.area
    if delta.when:
        session.when = delta.when
    if delta.radius_km:  # latest statement wins: explicit value, or halve the current one
        session.radius_km = clamp_radius(delta.radius_km)
    elif delta.radius_halve:
        session.radius_km = max(MIN_RADIUS_KM, round(current_radius(session) / 2, 2))
    if delta.intent in ("food", "activity") and not session.suggestions:
        session.kind = delta.intent
    return session


def avoid_terms(session: Session) -> set[str]:
    """Things someone disliked or just ate, unless someone else in the group wants it now."""
    avoid: set[str] = set()
    for p in session.prefs.values():
        avoid.update(p.dislikes)
        avoid.update(p.just_ate)
    latest_want = session.group_wants[-1:] if session.group_wants else []
    return avoid - set(latest_want)


def group_budget(session: Session) -> int | None:
    budgets = [p.budget_max_thb for p in session.prefs.values() if p.budget_max_thb]
    return min(budgets) if budgets else None
