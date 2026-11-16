"""Search pipeline: anchor -> Places text search -> Haversine filter -> avoid -> rank top 3."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from adapters.models import LatLng, PlaceCandidate
from adapters.places import Places
from features import activity, food
from features.geo import AREA_CENTERS, haversine_km, maps_link
from session.merge import avoid_terms
from session.models import Session, Suggestion

log = logging.getLogger(__name__)


@dataclass
class SearchOutcome:
    suggestions: list[Suggestion]
    radius_km: float
    error: str | None = None  # "no_area" | "not_found" | "places_failed"


def build_query(session: Session) -> str:
    base = activity.BASE_QUERY if session.kind == "activity" else food.BASE_QUERY
    want = session.group_wants[-1] if session.group_wants else ""
    return " ".join(x for x in (want or base, session.area or "") if x)


async def resolve_center(session: Session, places: Places) -> LatLng | None:
    if session.area_center:
        return session.area_center
    if not session.area:
        return None
    center = AREA_CENTERS.get(session.area) or await places.geocode(session.area)
    session.area_center = center
    return center


def _avoided(place: PlaceCandidate, avoid: set[str]) -> bool:
    text = " ".join(place.types) + " " + place.name
    return any(term in text for term in avoid)


def rank(cands: list[PlaceCandidate], center: LatLng, radius_km: float,
         avoid: set[str], exclude_ids: set[str]) -> list[PlaceCandidate]:
    kept: list[PlaceCandidate] = []
    for c in cands:
        c.distance_km = round(haversine_km(center, c.latlng), 2)
        if c.distance_km <= radius_km and c.place_id not in exclude_ids and not _avoided(c, avoid):
            kept.append(c)
    # rating first, then closer
    kept.sort(key=lambda c: (-(c.rating or 0), c.distance_km or 0))
    return kept[:3]


async def search(session: Session, places: Places, *, exclude_last: bool = False) -> SearchOutcome:
    radius = activity.RADIUS_KM if session.kind == "activity" else food.RADIUS_KM
    center = await resolve_center(session, places)
    if center is None:
        return SearchOutcome([], radius, "no_area")
    exclude = {s.place_id for s in session.suggestions} if exclude_last else set()
    try:
        cands = await places.search_text(build_query(session), center, radius)
    except Exception as exc:
        log.warning("places failed (%s)", type(exc).__name__)
        return SearchOutcome([], radius, "places_failed")
    top = rank(cands, center, radius, avoid_terms(session), exclude)
    if not top:
        return SearchOutcome([], radius, "not_found")
    return SearchOutcome(
        [Suggestion(place_id=c.place_id, name=c.name, latlng=c.latlng,
                    distance_km=c.distance_km or 0.0,
                    maps_url=c.maps_url or maps_link(c.name, c.place_id)) for c in top],
        radius,
    )
