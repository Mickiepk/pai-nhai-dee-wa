"""Session state stored in GROUP#<id> / SESSION#active. Extracted state only, never chat text."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from adapters.models import LatLng


class State(StrEnum):
    """Conversation state of a group session: LISTENING or CONFIRMING."""

    LISTENING = "listening"
    CONFIRMING = "confirming"


class UserPrefs(BaseModel):
    """One person's extracted preferences (likes, dislikes, just ate, budget). Never raw text."""

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
    """Everything stored per group while the bot is listening; expires after the configured minutes."""

    session_id: str
    group_id: str
    kind: str = "food"  # food | activity | meetup
    state: State = State.LISTENING
    started_at: int  # epoch seconds
    expires_at: int  # epoch seconds, also the DynamoDB TTL
    area: str | None = None
    area2: str | None = None  # "ระหว่าง area กับ area2": anchor = midpoint of the two
    area_center: LatLng | None = None
    group_wants: list[str] = Field(default_factory=list)  # most recent last
    when: str | None = None
    radius_km: float | None = None  # None = default for the kind (food 3 km, activity 5 km)
    prefs: dict[str, UserPrefs] = Field(default_factory=dict)  # userId -> prefs
    participants: list[str] = Field(default_factory=list)  # userIds who spoke, in order
    llm_calls: int = 0
    suggestions: list[Suggestion] = Field(default_factory=list)
    candidate: Suggestion | None = None
    acks: list[str] = Field(default_factory=list)  # userIds who tapped ตกลง
    confirm_round: int = 0  # bumped whenever a confirmation card is posted or cancelled (stale buttons die)
    ended: bool = Field(False, exclude=True)  # runtime flag, never stored

    @property
    def area_label(self) -> str | None:
        """Human label of the anchor: "อารีย์" or "กึ่งกลางสยามกับอารีย์"."""
        if self.area and self.area2:
            return f"กึ่งกลาง{self.area}กับ{self.area2}"
        return self.area

    def is_expired(self, now: int) -> bool:
        """True once `now` (epoch seconds) reaches expires_at."""
        return now >= self.expires_at
