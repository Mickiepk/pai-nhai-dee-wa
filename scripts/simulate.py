"""Terminal group-chat simulator. Offline fakes by default (free).

    python -m scripts.simulate                       # plays scripts/scenarios/ari_buffet.txt
    python -m scripts.simulate --script my.txt
    python -m scripts.simulate --interactive         # type "A: @bot กินไรดีแถวสยาม"
    python -m scripts.simulate --live                # real Gemini + Places (costs money, needs .env)
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from adapters.line import FakeLine
from config import Settings, load_dotenv, load_settings
from scripts.events import postback_event, text_event
from scripts.render import render
from session.engine import SessionEngine
from store.memory import MemoryStore
from wiring import build_engine

GROUP = "Csimgroup"
DEFAULT_SCRIPT = Path(__file__).parent / "scenarios" / "ari_buffet.txt"
NAMES = {"A": "เอ", "B": "บี", "C": "ซี", "D": "ดี"}
_BUTTON = re.compile(r"^\[(.+?)(?:\s+(\d))?\]$")


def make_sim(live: bool) -> tuple[SessionEngine, FakeLine]:
    if live:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")  # keys live in .env, no `source` needed
    settings = load_settings() if live else Settings()
    if live:
        settings = settings.model_copy(update={"llm_provider": "gemini", "places_provider": "google"})
    line = FakeLine(names={u: n for u, n in NAMES.items()})
    return build_engine(settings, store=MemoryStore(), line=line), line


def events_for(engine: SessionEngine, user: str, text: str) -> list[dict]:
    m = _BUTTON.match(text.strip())
    if not m:
        return [text_event(GROUP, user, text)]
    session = engine.store.get_session(GROUP)
    sid = session.session_id if session else "none"
    label, num = m.group(1), m.group(2)
    data = {"ตกลง": f"act=ack&v=yes&sid={sid}", "ยังก่อน": f"act=ack&v=no&sid={sid}",
            "หยุดฟัง": f"act=stop&sid={sid}", "เอาร้านนี้": f"act=pick&i={num or 1}&sid={sid}"}.get(label)
    if data is None:
        print(f"  (unknown button [{label}])")
        return []
    users = (session.participants if session else []) if user == "*" else [user]
    return [postback_event(GROUP, u, data) for u in users]


async def play_line(engine: SessionEngine, line: FakeLine, raw: str) -> None:
    if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
        return
    user, text = (x.strip() for x in raw.split(":", 1))
    print(f"\n{NAMES.get(user, user)} ({user}): {text}")
    for ev in events_for(engine, user, text):
        before = len(line.replies)
        await engine.handle(ev)
        for _token, msgs in line.replies[before:]:
            for msg in msgs:
                print("  🤖 " + render(msg).replace("\n", "\n     "))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--live", action="store_true", help="use real Gemini + Places (costs money)")
    args = ap.parse_args()
    engine, line = make_sim(args.live)
    print(f"--- simulator (llm={engine.s.llm_provider}, places={engine.s.places_provider}) ---")
    if args.interactive:
        print('พิมพ์ "A: @bot กินไรดีแถวสยาม" (Ctrl-D เพื่อออก)')
        for raw in sys.stdin:
            await play_line(engine, line, raw)
    else:
        for raw in args.script.read_text(encoding="utf-8").splitlines():
            await play_line(engine, line, raw)
    session = engine.store.get_session(GROUP)
    print("\n--- session:", "ended" if session is None else session.state.value, "---")


if __name__ == "__main__":
    asyncio.run(main())
