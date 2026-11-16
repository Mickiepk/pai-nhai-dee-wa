"""Shared data contracts between bot core (web-dev-1) and integrations (web-dev-2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["food", "activity", "meetup", "none"]
Request = Literal["search", "announce", "vote", "stop", "none"]


class LatLng(BaseModel):
    lat: float
    lng: float


class MessageDelta(BaseModel):
    """What the small LLM extracts from ONE chat message. Never contains raw text."""

    intent: Intent = "none"
    request: Request = "none"  # what the speaker wants the bot to do (if anything)
    area: str | None = None  # e.g. "อารีย์"
    likes: list[str] = Field(default_factory=list)  # e.g. ["ญี่ปุ่น"], ["บุฟเฟต์นานาชาติ"]
    dislikes: list[str] = Field(default_factory=list)
    just_ate: list[str] = Field(default_factory=list)
    budget_max_thb: int | None = Field(None, gt=0, le=20000)
    when: str | None = None  # free-form time, e.g. "19:00" or "พรุ่งนี้เย็น"
    radius_km: float | None = Field(None, gt=0, le=50)  # explicit "ไม่เกิน 5 กม." / "within 5 km"
    radius_halve: bool = False  # "ไกลไป": halve the current radius (min 1 km)
    rejects_last_suggestion: bool = False
    decision_detected: bool = False  # "โอเค ไปร้านนี้แหละ"
    pick_index: int | None = Field(None, ge=1, le=3)  # "ร้านที่ 2"
    asks_bot: bool = False
    needs_answer: bool = False


class PlaceCandidate(BaseModel):
    place_id: str
    name: str
    latlng: LatLng
    types: list[str] = Field(default_factory=list)
    rating: float | None = None
    rating_count: int | None = None
    price_level: int | None = None
    maps_url: str = ""
    distance_km: float | None = None  # filled by bot core (Haversine), never by the LLM
