import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


import pytest  # noqa: E402

# Process env that changes engine/config behaviour. A developer shell (or an earlier test) must not leak these in:
# GEMINI_PAID_TIER=true exported in the shell made the "unpaid tier" tests and SBX-43 fail on full runs.
_ISOLATED_ENV = ("GEMINI_PAID_TIER", "GEMINI_PAID_TIER_CONFIRMED", "BOT_ENABLED", "LLM_PROVIDER", "LINE_PROVIDER",
                 "PLACES_PROVIDER")


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    for name in _ISOLATED_ENV:
        monkeypatch.delenv(name, raising=False)
