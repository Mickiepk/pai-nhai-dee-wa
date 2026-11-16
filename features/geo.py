"""Distance and map links. Plain math, never the LLM."""

from __future__ import annotations

import math
from urllib.parse import quote

from adapters.models import LatLng

EARTH_RADIUS_KM = 6371.0088

# Known Bangkok area centres: saves a Places call for the most common anchors.
AREA_CENTERS: dict[str, LatLng] = {
    "อารีย์": LatLng(lat=13.7797, lng=100.5446),
    "สยาม": LatLng(lat=13.7457, lng=100.5343),
    "สาทร": LatLng(lat=13.7210, lng=100.5294),
    "สีลม": LatLng(lat=13.7290, lng=100.5340),
    "อโศก": LatLng(lat=13.7370, lng=100.5603),
    "ทองหล่อ": LatLng(lat=13.7244, lng=100.5783),
    "เอกมัย": LatLng(lat=13.7196, lng=100.5851),
    "พร้อมพงษ์": LatLng(lat=13.7305, lng=100.5697),
    "อนุสาวรีย์": LatLng(lat=13.7650, lng=100.5383),
    "ชิดลม": LatLng(lat=13.7440, lng=100.5430),
    "จตุจักร": LatLng(lat=13.7999, lng=100.5504),
}


def haversine_km(a: LatLng, b: LatLng) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def format_km(km: float) -> str:
    return f"~{km * 1000:.0f} ม." if km < 1 else f"~{km:.1f} กม."


def format_radius(km: float) -> str:
    """Radius for headers: "3 กม." or, below 1 km, "400 ม." (BUG-13)."""
    return f"{km * 1000:g} ม." if km < 1 else f"{km:g} กม."


def maps_link(name: str, place_id: str) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={quote(name)}&query_place_id={quote(place_id)}"
