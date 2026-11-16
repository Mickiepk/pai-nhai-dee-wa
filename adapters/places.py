"""Google Places API (New) over REST, plus an offline fake.

Places terms: only place_id and lat/lng may be cached (<= 30 days). Names, ratings
and photos must be fetched fresh, so this adapter has no long-lived cache.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from adapters.models import LatLng, PlaceCandidate

log = logging.getLogger(__name__)

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    "places." + f
    for f in ("id", "displayName", "location", "types", "rating", "userRatingCount",
              "priceLevel", "googleMapsUri", "businessStatus")
)
_PRICE = {"PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
          "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}


class Places(Protocol):
    """Places provider interface: text search around a point, and geocoding of an area name."""

    async def search_text(self, query: str, center: LatLng, radius_km: float) -> list[PlaceCandidate]:
        """Search places for a text query within radius_km of center."""
        ...
    async def geocode(self, name: str) -> LatLng | None:
        """Coordinates of an area name, or None if unknown."""
        ...


class GooglePlaces:
    """Google Places API (New) client. Network and HTTP errors propagate; the search layer contains them."""

    def __init__(self, api_key: str, timeout_s: float = 5.0):
        self._api_key = api_key
        self._timeout_s = timeout_s

    async def _post(self, body: dict) -> list[dict]:
        headers = {"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": FIELD_MASK}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(SEARCH_URL, json=body, headers=headers)
            resp.raise_for_status()
        log.info("places_call searchText")  # cost tracking
        return resp.json().get("places", [])

    async def search_text(self, query: str, center: LatLng, radius_km: float) -> list[PlaceCandidate]:
        """Text Search restricted to a circle around center; maps results to PlaceCandidate."""
        body = {
            "textQuery": query,
            "languageCode": "th",
            "regionCode": "TH",
            "pageSize": 10,
            "locationBias": {"circle": {
                "center": {"latitude": center.lat, "longitude": center.lng},
                "radius": min(radius_km * 1000, 50000.0),
            }},
        }
        return [p for raw in await self._post(body) if (p := _parse(raw))]

    async def geocode(self, name: str) -> LatLng | None:
        """Resolve an area name to coordinates via a one-result Text Search; None when nothing is found."""
        raw = await self._post({"textQuery": f"{name} กรุงเทพ", "languageCode": "th", "pageSize": 1})
        if not raw or "location" not in raw[0]:
            return None
        loc = raw[0]["location"]
        return LatLng(lat=loc["latitude"], lng=loc["longitude"])


def _parse(raw: dict) -> PlaceCandidate | None:
    if raw.get("businessStatus", "OPERATIONAL") != "OPERATIONAL" or "location" not in raw:
        return None
    return PlaceCandidate(
        place_id=raw["id"],
        name=raw.get("displayName", {}).get("text", "?"),
        latlng=LatLng(lat=raw["location"]["latitude"], lng=raw["location"]["longitude"]),
        types=raw.get("types", []),
        rating=raw.get("rating"),
        rating_count=raw.get("userRatingCount"),
        price_level=_PRICE.get(raw.get("priceLevel", "")),
        maps_url=raw.get("googleMapsUri", ""),
    )


# ---------------------------------------------------------------- offline fake

def _fp(pid: str, name: str, lat: float, lng: float, tags: list[str], rating: float) -> PlaceCandidate:
    return PlaceCandidate(place_id=pid, name=name, latlng=LatLng(lat=lat, lng=lng), types=tags,
                          rating=rating, rating_count=120, price_level=2)


FAKE_PLACES: list[PlaceCandidate] = [
    _fp("fake-ari-1", "[ตัวอย่าง] ซูชิอารีย์", 13.7801, 100.5446, ["ญี่ปุ่น", "ซูชิ", "restaurant"], 4.5),
    _fp("fake-ari-2", "[ตัวอย่าง] ปิ้งย่างโซล", 13.7795, 100.5432, ["เกาหลี", "ปิ้งย่าง", "restaurant"], 4.3),
    _fp("fake-ari-3", "[ตัวอย่าง] ข้าวมันไก่ซอยอารีย์", 13.7812, 100.5459, ["ไทย", "restaurant"], 4.2),
    _fp("fake-ari-4", "[ตัวอย่าง] เวิลด์บุฟเฟต์ พหลโยธิน", 13.7838, 100.5468,
        ["บุฟเฟต์นานาชาติ", "บุฟเฟต์", "restaurant"], 4.4),
    _fp("fake-ari-5", "[ตัวอย่าง] ราเมนคุมะ", 13.7776, 100.5420, ["ญี่ปุ่น", "ราเมน", "restaurant"], 4.1),
    _fp("fake-ari-6", "[ตัวอย่าง] บุฟเฟต์ไกลบางนา", 13.6680, 100.6340, ["บุฟเฟต์นานาชาติ", "บุฟเฟต์"], 4.9),
    _fp("fake-ari-7", "[ตัวอย่าง] โบว์ลิ่งอารีย์", 13.7790, 100.5440, ["โบว์ลิ่ง", "activity"], 4.0),
    _fp("fake-ari-8", "[ตัวอย่าง] คาราโอเกะพหลฯ", 13.7820, 100.5470, ["คาราโอเกะ", "activity"], 4.2),
]


class FakePlaces:
    """Returns fixture places whose tags match words in the query. Counts calls."""

    def __init__(self, places: list[PlaceCandidate] | None = None):
        self.places = places if places is not None else FAKE_PLACES
        self.calls: list[str] = []

    async def search_text(self, query: str, center: LatLng, radius_km: float) -> list[PlaceCandidate]:
        """Offline: places whose tags occur in the query (activity places only if asked); records the query."""
        self.calls.append(query)
        matched = [p for p in self.places if any(tag in query for tag in p.types)]
        if not matched:
            matched = [p for p in self.places if "activity" not in p.types]
        return [p.model_copy(deep=True) for p in matched]

    async def geocode(self, name: str) -> LatLng | None:
        """Offline: always None (unknown area); records the call."""
        self.calls.append(f"geocode:{name}")
        return None
