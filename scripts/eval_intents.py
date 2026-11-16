"""Intent/extraction eval on a labelled Thai utterance set.

    python -m scripts.eval_intents                     # offline rules, free
    python -m scripts.eval_intents --live              # real Gemini (costs a little, needs .env)
    python -m scripts.eval_intents --places            # also run search and check distances (fake places)
    python -m scripts.eval_intents --live --places     # Gemini + real Places API (costs money)
    python -m scripts.eval_intents --file my.jsonl --verbose

Each JSONL line: {"id", "text", "mentioned", "intent", and optional "area", "request",
"likes", "dislikes", "just_ate", "decision", "pick", "rejects", "budget", "when", "note"}.
Only the labels present on a line are checked. Text is printed only on this local machine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from adapters.llm import GeminiExtractor, RuleExtractor
from adapters.models import MessageDelta
from config import load_settings
from features import search as search_mod
from features.geo import haversine_km
from session.merge import apply_delta
from session.models import Session

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "tests" / "eval" / "utterances.jsonl"

# label in file -> how to read it from the MessageDelta
FIELDS = {
    "intent": lambda d: d.intent,
    "area": lambda d: d.area,
    "request": lambda d: d.request,
    "decision": lambda d: d.decision_detected,
    "pick": lambda d: d.pick_index,
    "rejects": lambda d: d.rejects_last_suggestion,
    "budget": lambda d: d.budget_max_thb,
    "when": lambda d: d.when,
    "likes": lambda d: d.likes,
    "dislikes": lambda d: d.dislikes,
    "just_ate": lambda d: d.just_ate,
}
LIST_FIELDS = {"likes", "dislikes", "just_ate"}


def check(row: dict, d: MessageDelta) -> dict[str, tuple[object, object]]:
    """Return {field: (expected, got)} for every labelled field that is wrong."""
    wrong: dict[str, tuple[object, object]] = {}
    for field, get in FIELDS.items():
        if field not in row:
            continue
        exp, got = row[field], get(d)
        ok = set(exp) <= set(got) if field in LIST_FIELDS else exp == got
        if not ok:
            wrong[field] = (exp, got)
    return wrong


async def place_check(row: dict, d: MessageDelta, places) -> tuple[int, int, int] | None:
    """(suggestions, real, within_radius) for rows that should trigger a search."""
    if row.get("request") != "search" or not d.area:
        return None
    now = int(time.time())
    s = Session(session_id="eval", group_id="eval", started_at=now, expires_at=now + 3600)
    apply_delta(s, "U1", d)
    out = await search_mod.search(s, places)
    if out.error or s.area_center is None:
        return (0, 0, 0)
    real = sum(1 for x in out.suggestions if not x.place_id.startswith("fake-") and x.maps_url)
    within = sum(1 for x in out.suggestions if haversine_km(s.area_center, x.latlng) <= out.radius_km)
    return (len(out.suggestions), real, within)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--live", action="store_true", help="use real Gemini (needs GEMINI_API_KEY)")
    ap.add_argument("--places", action="store_true", help="also run search; with --live uses Google Places")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    rows = [json.loads(x) for x in args.file.read_text(encoding="utf-8").splitlines() if x.strip()]
    rules = RuleExtractor()
    s = load_settings()
    if args.live:
        if not s.gemini_api_key:
            print("GEMINI_API_KEY missing (set it in .env, then: set -a; . ./.env; set +a)")
            return 2
        llm = GeminiExtractor(s.gemini_api_key, s.gemini_model, rules)
    else:
        llm = rules
    places = None
    if args.places:
        from adapters.places import FakePlaces, GooglePlaces
        places = GooglePlaces(s.google_places_api_key) if args.live else FakePlaces()

    print(f"--- eval: {len(rows)} utterances, llm={'gemini' if args.live else 'rules'} ---")
    intent_ok = all_ok = 0
    per_field: dict[str, list[int]] = {}
    failures: list[str] = []
    n_sugg = n_real = n_within = 0
    for row in rows:
        d = await llm.extract(row["text"], mentioned=row.get("mentioned", False), context={})
        wrong = check(row, d)
        for f in FIELDS:
            if f in row:
                ok_bad = per_field.setdefault(f, [0, 0])
                ok_bad[0 if f not in wrong else 1] += 1
        intent_ok += "intent" not in wrong
        all_ok += not wrong
        mark = "PASS" if not wrong else "FAIL"
        if wrong:
            detail = "; ".join(f"{f}: want {e!r} got {g!r}" for f, (e, g) in wrong.items())
            note = f"  ({row['note']})" if row.get("note") else ""
            failures.append(f"  {row['id']} {row['text']!r} -> {detail}{note}")
        if args.verbose:
            print(f"{mark} {row['id']} {row['text']}")
        if places is not None:
            pc = await place_check(row, d, places)
            if pc:
                n_sugg, n_real, n_within = n_sugg + pc[0], n_real + pc[1], n_within + pc[2]

    n = len(rows)
    print(f"intent accuracy : {intent_ok}/{n} = {intent_ok / n:.0%}")
    print(f"all-fields exact: {all_ok}/{n} = {all_ok / n:.0%}")
    for f, (ok, bad) in per_field.items():
        print(f"  {f:<9} {ok}/{ok + bad}")
    if places is not None:
        if n_sugg:
            print(f"places: {n_sugg} suggestions, real-place {n_real / n_sugg:.0%}, "
                  f"within-radius {n_within / n_sugg:.0%}")
        else:
            print("places: no suggestions returned")
    if failures:
        print("failures:")
        print("\n".join(failures))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
