"""Session state stored in GROUP#<id> / SESSION#active. Extracted state only, never chat text."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from adapters.models import LatLng


class State(StrEnum):
    LISTENING = "listening"
    CONFIRMING = "confirming"


class UserPrefs(BaseModel):
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    just_ate: list[str] = Field(default_factory=list)
    budget_max_thb: int | None = None


class Suggestion(BaseModel):
    """Only what we need to confirm a plan. Lives <= session TTL (60 min)."""

    place_id: str
    name: str
    latlng: LatLng
    distance_km: float
    maps_url: str = ""


class Session(BaseModel):
    session_id: str
    group_id: str
    kind: str = "food"  # food | activity | meetup
    state: State = State.LISTENING
    started_at: int  # epoch seconds
    expires_at: int  # epoch seconds, also the DynamoDB TTL
    area: str | None = None
    area_center: LatLng | None = None
    group_wants: list[str] = Field(default_factory=list)  # most recent last
    when: str | None = None
    prefs: dict[str, UserPrefs] = Field(default_factory=dict)  # userId -> prefs
    participants: list[str] = Field(default_factory=list)  # userIds who spoke, in order
    llm_calls: int = 0
    suggestions: list[Suggestion] = Field(default_factory=list)
    candidate: Suggestion | None = None
    acks: list[str] = Field(default_factory=list)  # userIds who tapped ตกลง
    ended: bool = Field(False, exclude=True)  # runtime flag, never stored

    def is_expired(self, now: int) -> bool:
        return now >= self.expires_at
