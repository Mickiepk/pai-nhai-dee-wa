"""Runtime configuration, read from environment variables (see .env.example).

Every hard cost cap lives here so the pilot stays under the 1,000 THB/month budget.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

LOCAL_DATABASE_URL = "postgresql://pnd:pnd@localhost:54329/pnd"  # scripts/local_pg.sh / docker-compose.yml


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


class Settings(BaseModel):
    # Secrets (from env locally, SSM on AWS). Never commit real values.
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    gemini_api_key: str = ""
    google_places_api_key: str = ""

    # Providers: "fake" = offline, free, deterministic. Real ones cost money.
    llm_provider: Literal["fake", "gemini"] = "fake"
    places_provider: Literal["fake", "google"] = "fake"
    line_provider: Literal["fake", "real"] = "fake"
    store_provider: Literal["memory", "postgres", "dynamo"] = "memory"
    database_url: str = LOCAL_DATABASE_URL  # used when STORE=postgres (local env)
    table_name: str = "pai-nhai-dee-wa-dev"
    gemini_model: str = "gemini-2.5-flash-lite"

    # Privacy: Gemini free tier may use prompts for training. Reading group chat
    # with Gemini is only allowed when the paid tier is confirmed.
    gemini_paid_tier_confirmed: bool = False

    # Hard caps (budget guard).
    bot_enabled: bool = True  # kill switch
    session_minutes: int = Field(60, ge=5, le=120)
    max_llm_calls_per_session: int = 40
    max_searches_per_group_per_day: int = 10
    max_places_calls_per_day: int = 300  # global, all groups
    default_radius_km: float = 3.0

    @property
    def chat_reading_enabled(self) -> bool:
        """May the bot read non-@mention messages during a session?"""
        if self.llm_provider == "fake":
            return True  # offline rules: nothing leaves the process
        return self.gemini_paid_tier_confirmed

    def problems(self) -> list[str]:
        """Human-readable config problems, printed at startup."""
        out: list[str] = []
        if self.line_provider == "real" and not (
            self.line_channel_secret and self.line_channel_access_token
        ):
            out.append("LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN missing")
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            out.append("GEMINI_API_KEY missing")
        if self.places_provider == "google" and not self.google_places_api_key:
            out.append("GOOGLE_PLACES_API_KEY missing")
        if not self.chat_reading_enabled:
            out.append(
                "GEMINI_PAID_TIER_CONFIRMED is not true: chat reading is DISABLED "
                "(bot only reacts to @mentions and buttons)"
            )
        if not self.bot_enabled:
            out.append("BOT_ENABLED=false: kill switch is ON, bot stays silent")
        return out


def load_dotenv(path: str | Path = ".env") -> bool:
    """Minimal .env loader (KEY=VALUE, # comments, optional quotes). Never overrides real env vars."""
    p = Path(path)
    if not p.is_file():
        return False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if val[:1] in "\"'" and val[-1:] == val[:1] and len(val) >= 2:
            val = val[1:-1]
        else:
            val = val.split(" #", 1)[0].strip()  # inline comment
        os.environ.setdefault(key.strip().removeprefix("export ").strip(), val)
    return True


def load_settings() -> Settings:
    e = os.environ.get
    return Settings(
        line_channel_secret=e("LINE_CHANNEL_SECRET", ""),
        line_channel_access_token=e("LINE_CHANNEL_ACCESS_TOKEN", ""),
        gemini_api_key=e("GEMINI_API_KEY", ""),
        google_places_api_key=e("GOOGLE_PLACES_API_KEY", ""),
        llm_provider=e("LLM_PROVIDER", "fake"),  # type: ignore[arg-type]
        places_provider=e("PLACES_PROVIDER", "fake"),  # type: ignore[arg-type]
        line_provider=e("LINE_PROVIDER", "fake"),  # type: ignore[arg-type]
        store_provider=e("STORE") or e("STORE_PROVIDER", "memory"),  # type: ignore[arg-type]
        database_url=e("DATABASE_URL") or LOCAL_DATABASE_URL,
        table_name=e("TABLE_NAME", "pai-nhai-dee-wa-dev"),
        gemini_model=e("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        gemini_paid_tier_confirmed=_bool("GEMINI_PAID_TIER_CONFIRMED"),
        bot_enabled=_bool("BOT_ENABLED", True),
        session_minutes=_int("SESSION_MINUTES", 60),
        max_llm_calls_per_session=_int("MAX_LLM_CALLS_PER_SESSION", 40),
        max_searches_per_group_per_day=_int("MAX_SEARCHES_PER_GROUP_PER_DAY", 10),
        max_places_calls_per_day=_int("MAX_PLACES_CALLS_PER_DAY", 300),
    )
