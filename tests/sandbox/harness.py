"""Sandbox harness: data-driven scenarios run against the real SessionEngine with fakes only.

Sandbox rules (docs/TEST_POLICY.md):
- no network: FakeLine, FakePlaces (or a scenario fixture), MemoryStore
- frozen clock: starts at FROZEN_NOW and moves only on an explicit `advance` step
- seeded randomness: the engine's session-id source (`id_factory`) is a seeded generator
- LLM: either the offline RuleExtractor (`llm: rules`) or the REAL GeminiExtractor code path with
  a scripted fake client that returns canned JSON per input (`llm: scripted`). The scripted path
  therefore exercises the production schema validation and rule fallback.

A scenario is a dict (loaded from YAML):
  id, area, title, bug (optional: "BUG-xx" -> xfail strict), settings, llm, script, places,
  geocode, names, shuffle (bool, default true), steps: [ {<event>, expect: {...}} ]
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from adapters.line import FakeLine
from adapters.llm import GeminiExtractor, RuleExtractor
from adapters.models import LatLng, MessageDelta, PlaceCandidate
from adapters.places import FAKE_PLACES, FakePlaces
from config import Settings
from scripts.render import render
from session.engine import SessionEngine
from store.memory import MemoryStore

FROZEN_NOW = 1_800_000_000  # 2027-01-15 08:00 UTC (15:00 Bangkok)
SCENARIO_DIR = Path(__file__).parent / "scenarios"
DEFAULT_NAMES = {"A": "เอ", "B": "บี", "C": "ซี", "D": "ดี", "E": "อี"}
BOT_TAG = "@bot"


# ---------------------------------------------------------------- loading

def load_scenarios() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(SCENARIO_DIR.glob("*.yaml")):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            case["_file"] = path.name
            cases.append(case)
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate scenario ids: {dupes}"
    return cases


# ---------------------------------------------------------------- fakes

class SandboxClock:
    def __init__(self, now: int = FROZEN_NOW):
        self.now = now

    def __call__(self) -> int:
        return self.now


class SandboxLine(FakeLine):
    """FakeLine that can be told to crash on the next reply (simulates an expired token / 5xx)."""

    def __init__(self, names: dict[str, str]):
        super().__init__(names=names)
        self.fail_next = False

    async def reply(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("sandbox: reply failed")
        await super().reply(reply_token, messages)


class CountingRules(RuleExtractor):
    def __init__(self) -> None:
        self.calls = 0
        self.unscripted: list[str] = []

    async def extract(self, text: str, *, mentioned: bool, context: dict[str, Any]) -> MessageDelta:
        self.calls += 1
        return self.extract_sync(text, mentioned=mentioned)


class _Resp:
    def __init__(self, text: str):
        self.text = text


class _ScriptedModels:
    def __init__(self, owner: ScriptedLLM):
        self.owner = owner

    async def generate_content(self, *, model: str, contents: str, config: Any) -> _Resp:
        # contents = "mentioned=..\ncontext=..\nmessage:\n<text>"
        text = contents.split("message:\n", 1)[1]
        self.owner.calls += 1
        self.owner.configs.append(config)
        if text not in self.owner.script:
            self.owner.unscripted.append(text)
            raise KeyError("unscripted input")
        canned = self.owner.script[text]
        if canned == "TIMEOUT":
            raise TimeoutError
        return _Resp(canned if isinstance(canned, str) else json.dumps(canned, ensure_ascii=False))


class ScriptedLLM(GeminiExtractor):
    """The production GeminiExtractor with its network client swapped for a canned script."""

    def __init__(self, script: dict[str, Any]):  # noqa: D107 - do not call super(): no SDK client
        self._model = "scripted-fake"
        self._fallback = RuleExtractor()
        self._timeout_s = 4.0
        self.script = script
        self.calls = 0
        self.configs: list[Any] = []
        self.unscripted: list[str] = []
        self._client = type("C", (), {"aio": type("A", (), {"models": _ScriptedModels(self)})()})()


class SandboxPlaces(FakePlaces):
    def __init__(self, places: list[PlaceCandidate], geocode: dict[str, LatLng]):
        super().__init__(places)
        self.geo = geocode

    async def geocode(self, name: str) -> LatLng | None:
        self.calls.append(f"geocode:{name}")
        return self.geo.get(name)


def _places_from(spec: Any) -> list[PlaceCandidate]:
    if spec in (None, "default"):
        return [p.model_copy(deep=True) for p in FAKE_PLACES]
    if spec == "none":
        return []
    out = []
    for p in spec:
        out.append(PlaceCandidate(place_id=p["id"], name=p["name"], latlng=LatLng(lat=p["lat"], lng=p["lng"]),
                                  types=p.get("tags", []), rating=p.get("rating"), rating_count=100,
                                  price_level=p.get("price_level")))
    return out


# ---------------------------------------------------------------- run

@dataclass
class World:
    engine: SessionEngine
    store: MemoryStore
    line: SandboxLine
    llm: Any
    places: SandboxPlaces
    clock: SandboxClock
    seq: int = 0
    last_event: dict[str, Any] | None = None
    sids: dict[str, list[str]] = field(default_factory=dict)  # group -> every sid seen, in order
    texts: list[str] = field(default_factory=list)


@dataclass
class Result:
    case_id: str
    failures: list[str]
    transcript: list[str]
    final_state: str

    @property
    def passed(self) -> bool:
        return not self.failures


def _build(case: dict[str, Any], rng: random.Random | None, seed: int = 1234) -> World:
    cfg = dict(case.get("settings") or {})
    if case.get("llm") == "scripted":  # the scripted path models a PAID Gemini deployment unless a case says otherwise
        cfg.setdefault("gemini_paid_tier_confirmed", True)
    settings = Settings(**cfg)
    names = dict(case.get("names") or DEFAULT_NAMES)
    places = _places_from(case.get("places"))
    if rng is not None:  # shuffled-but-equivalent setup
        rng.shuffle(places)
        items = list(names.items())
        rng.shuffle(items)
        names = dict(items)
    geo = {k: LatLng(lat=v[0], lng=v[1]) for k, v in (case.get("geocode") or {}).items()}
    llm: Any = ScriptedLLM(case.get("script") or {}) if case.get("llm") == "scripted" else CountingRules()
    store, line, clock = MemoryStore(), SandboxLine(names), SandboxClock()
    pl = SandboxPlaces(places, geo)
    ids = random.Random(seed)  # injected session-id source (BUG-20): no monkeypatching of uuid
    engine = SessionEngine(settings, store, line, llm, pl, clock=clock,
                           id_factory=lambda: f"{ids.getrandbits(32):08x}")
    return World(engine, store, line, llm, pl, clock)


def _event(w: World, etype: str, group: str, user: str | None) -> dict[str, Any]:
    w.seq += 1
    src: dict[str, Any] = {"type": "group", "groupId": group}
    if user:
        src["userId"] = user
    return {"type": etype, "webhookEventId": f"sbx{w.seq:04d}", "replyToken": f"rt{w.seq:04d}",
            "timestamp": 0, "mode": "active", "source": src}


def _sid(w: World, group: str, which: str) -> str:
    sess = w.store.get_session(group)
    if sess and sess.session_id not in w.sids.setdefault(group, []):
        w.sids[group].append(sess.session_id)
    if which == "current":
        return sess.session_id if sess else "nosession"
    if which == "stale":  # the previous (ended) session's id
        seen = w.sids.get(group, [])
        cur = sess.session_id if sess else None
        old = [s for s in seen if s != cur]
        return old[-1] if old else "stale"
    return which


_ACTS = {"ack_yes": "act=ack&v=yes", "ack_no": "act=ack&v=no", "stop": "act=stop", "search": "act=search"}


def _make_event(w: World, step: dict[str, Any], group: str) -> dict[str, Any] | None:
    if "say" in step:
        user, text = step["say"]
        ev = _event(w, "message", group, user)
        msg: dict[str, Any] = {"type": "text", "id": ev["webhookEventId"], "text": text}
        if text.startswith(BOT_TAG):
            msg["mention"] = {"mentionees": [{"index": 0, "length": len(BOT_TAG), "type": "user",
                                              "userId": "Ubot", "isSelf": True}]}
        ev["message"] = msg
        w.texts.append(text)
        return ev
    if "sticker" in step:
        ev = _event(w, "message", group, step["sticker"])
        ev["message"] = {"type": "sticker", "id": "s", "packageId": "1", "stickerId": "1"}
        return ev
    if "image" in step:
        ev = _event(w, "message", group, step["image"])
        ev["message"] = {"type": "image", "id": "i"}
        return ev
    if "tap" in step:
        t = step["tap"]
        act = t["act"]
        if act.startswith("pick:"):
            data = f"act=pick&i={act.split(':')[1]}"
        elif act.startswith("area:"):
            data = f"act=area&a={act.split(':', 1)[1]}"
        else:
            data = _ACTS[act]
        data += f"&sid={_sid(w, group, t.get('sid', 'current'))}"
        if act.startswith("ack"):  # like the real card: carry the confirmation round
            sess = w.store.get_session(group)
            rnd = (sess.confirm_round if sess else 0) - (1 if t.get("round") == "stale" else 0)
            data += f"&r={rnd}"
        ev = _event(w, "postback", group, t["user"])
        ev["postback"] = {"data": data}
        return ev
    if "join" in step:
        return _event(w, "join", group, None)
    if "leave" in step:
        return _event(w, "leave", group, None)
    if step.get("dup") or step.get("retry"):
        return w.last_event
    return None


def _snapshot(w: World) -> str:
    sessions = {g: json.loads(raw) for g, raw in sorted(w.store.sessions.items())}
    state = {
        "sessions": sessions,
        "counters": {k: v[0] for k, v in sorted(w.store.counters.items())},
        "events_seen": sorted(w.store.events),
        "places_calls": w.places.calls,
        "llm_calls": w.llm.calls,
    }
    return json.dumps(state, ensure_ascii=False, sort_keys=True)


def _check(w: World, group: str, new: list[tuple[str, list[dict[str, Any]]]], exp: dict[str, Any],
           crashed: bool, where: str) -> list[str]:
    f: list[str] = []
    rendered = "\n".join(render(m) for _t, msgs in new for m in msgs)
    msgs = [m for _t, ms in new for m in ms]
    if exp.get("silent") and new:
        f.append(f"{where}: expected silence, bot said: {rendered[:160]!r}")
    if exp.get("reply") and not new:
        f.append(f"{where}: expected a reply, bot was silent")
    if "n_messages" in exp and len(msgs) != exp["n_messages"]:
        f.append(f"{where}: expected {exp['n_messages']} messages, got {len(msgs)}")
    for s in exp.get("contains", []):
        if s not in rendered:
            f.append(f"{where}: reply should contain {s!r}; got {rendered[:200]!r}")
    for s in exp.get("not_contains", []):
        if s in rendered:
            f.append(f"{where}: reply must NOT contain {s!r}")
    for b in exp.get("buttons", []):
        if f"[{b}]" not in rendered:
            f.append(f"{where}: missing button [{b}]")
    if "crash" in exp and bool(exp["crash"]) != crashed:
        f.append(f"{where}: crash expected={exp['crash']} actual={crashed}")

    sess = w.store.get_session(group)
    if "state" in exp:
        actual = sess.state.value if sess else "none"
        if actual != exp["state"]:
            f.append(f"{where}: state expected {exp['state']}, got {actual}")
    if sess is not None:
        for key in ("area", "kind", "when"):
            if key in exp and getattr(sess, key) != exp[key]:
                f.append(f"{where}: {key} expected {exp[key]!r}, got {getattr(sess, key)!r}")
        for key in ("participants", "acks"):
            if key in exp and getattr(sess, key) != exp[key]:
                f.append(f"{where}: {key} expected {exp[key]}, got {getattr(sess, key)}")
        if "suggestions" in exp:
            names = [s.name for s in sess.suggestions]
            want = exp["suggestions"]
            if len(names) != len(want) or not all(a in n for a, n in zip(want, names, strict=False)):
                f.append(f"{where}: suggestions expected {want}, got {names}")
        if "max_distance_km" in exp and any(s.distance_km > exp["max_distance_km"] for s in sess.suggestions):
            f.append(f"{where}: a suggestion is beyond {exp['max_distance_km']} km: "
                     f"{[(s.name, s.distance_km) for s in sess.suggestions]}")
        if "candidate" in exp:
            got = sess.candidate.name if sess.candidate else None
            if exp["candidate"] is None and got is not None or exp["candidate"] and (
                    not got or exp["candidate"] not in got):
                f.append(f"{where}: candidate expected {exp['candidate']!r}, got {got!r}")
        for uid, pexp in (exp.get("prefs") or {}).items():
            p = sess.prefs.get(uid)
            for k, v in pexp.items():
                got = getattr(p, k) if p else None
                if got != v:
                    f.append(f"{where}: prefs[{uid}].{k} expected {v}, got {got}")
        if "llm_calls_session" in exp and sess.llm_calls != exp["llm_calls_session"]:
            f.append(f"{where}: session.llm_calls expected {exp['llm_calls_session']}, got {sess.llm_calls}")
    else:
        for key in ("area", "participants", "acks", "suggestions", "candidate", "prefs"):
            if key in exp:
                f.append(f"{where}: expected session field {key} but there is no session")
    if "llm_calls" in exp and w.llm.calls != exp["llm_calls"]:
        f.append(f"{where}: LLM calls expected {exp['llm_calls']}, got {w.llm.calls}")
    if "places_calls" in exp and len(w.places.calls) != exp["places_calls"]:
        f.append(f"{where}: Places calls expected {exp['places_calls']}, got {len(w.places.calls)} {w.places.calls}")
    if exp.get("places_quota_matches_calls"):
        quota = sum(v[0] for k, v in w.store.counters.items() if k.startswith("QUOTA#PLACES#"))
        if quota != len(w.places.calls):
            f.append(f"{where}: QUOTA#PLACES={quota} but Places was called {len(w.places.calls)} times")
    if exp.get("no_raw_text"):
        blob = json.dumps({k: v for k, v in w.store.sessions.items()}, ensure_ascii=False)
        blob += json.dumps(list(w.store.counters), ensure_ascii=False)
        blob = json.loads(json.dumps(blob))  # unescape
        for t in w.texts:
            body = t[len(BOT_TAG):].strip() if t.startswith(BOT_TAG) else t
            if len(body) >= 6 and body in blob:
                f.append(f"{where}: raw chat text stored: {body!r}")
    if exp.get("group_data_deleted") and (w.store.get_session(group) is not None):
        f.append(f"{where}: session data for {group} still stored after leave")
    if exp.get("temperature_zero"):
        temps = {getattr(c, "temperature", None) for c in getattr(w.llm, "configs", [])}
        if temps != {0}:
            f.append(f"{where}: LLM temperatures {temps}, expected {{0}}")
    return f


async def _run(case: dict[str, Any], seed: int, shuffle_rng: random.Random | None) -> Result:
    w = _build(case, shuffle_rng, seed)
    failures: list[str] = []
    transcript: list[str] = []
    for i, step in enumerate(case["steps"], start=1):
        group = step.get("group", "G1")
        where = f"step {i}"
        if "advance" in step:
            w.clock.now += int(step["advance"])
            transcript.append(f"{i} advance {step['advance']}")
        if step.get("fail_next_reply"):
            w.line.fail_next = True
        if "settings" in step:  # flip a setting mid-scenario (kill switch)
            for k, v in step["settings"].items():
                setattr(w.engine.s, k, v)
        ev = _make_event(w, step, group)
        before = len(w.line.replies)
        crashed = False
        if ev is not None:
            w.last_event = ev
            try:
                await w.engine.handle(ev)
            except Exception as exc:  # noqa: BLE001 - recorded, may be expected
                crashed = True
                transcript.append(f"{i} CRASH {type(exc).__name__}")
        new = w.line.replies[before:]
        label = {k: v for k, v in step.items() if k not in ("expect",)}
        transcript.append(f"{i} {json.dumps(label, ensure_ascii=False, sort_keys=True)}")
        for token, msgs in new:
            transcript.append(f"  -> {token} {json.dumps(msgs, ensure_ascii=False, sort_keys=True)}")
        if crashed and "crash" not in (step.get("expect") or {}):
            failures.append(f"{where}: engine raised unexpectedly")
        failures += _check(w, group, new, step.get("expect") or {}, crashed, where)
    if w.llm.unscripted:
        failures.append(f"scripted LLM got unscripted input(s): {w.llm.unscripted}")
    return Result(case["id"], failures, transcript, _snapshot(w))


def run_case(case: dict[str, Any], *, seed: int = 1234, shuffle_seed: int | None = None) -> Result:
    rng = random.Random(shuffle_seed) if shuffle_seed is not None else None
    return asyncio.run(_run(case, seed, rng))


def run_unseeded_twice(case: dict[str, Any]) -> tuple[Result, Result]:
    """Without the sandbox uuid seed: shows whether production code is deterministic on its own."""
    async def go() -> Result:
        w = _build(case, None)
        transcript: list[str] = []
        for step in case["steps"]:
            group = step.get("group", "G1")
            if "advance" in step:
                w.clock.now += int(step["advance"])
            if step.get("fail_next_reply"):
                w.line.fail_next = True
            ev = _make_event(w, step, group)
            before = len(w.line.replies)
            if ev is not None:
                w.last_event = ev
                try:
                    await w.engine.handle(ev)
                except Exception:  # noqa: BLE001
                    transcript.append("CRASH")
            for token, msgs in w.line.replies[before:]:
                transcript.append(f"{token} {json.dumps(msgs, ensure_ascii=False, sort_keys=True)}")
        return Result(case["id"], [], transcript, _snapshot(w))
    return asyncio.run(go()), asyncio.run(go())


def determinism(case: dict[str, Any], runs: int = 5) -> list[str]:
    """Return problems: transcripts/state must be byte-identical across fresh engines and shuffles."""
    problems: list[str] = []
    base = run_case(case)
    for n in range(1, runs):
        r = run_case(case)
        if r.transcript != base.transcript:
            problems.append(f"run {n + 1}: transcript differs")
        if r.final_state != base.final_state:
            problems.append(f"run {n + 1}: final state differs")
    if case.get("shuffle", True):
        for s in range(runs):
            r = run_case(case, shuffle_seed=s)
            if r.transcript != base.transcript:
                problems.append(f"shuffle seed {s}: transcript differs")
            if r.final_state != base.final_state:
                problems.append(f"shuffle seed {s}: final state differs")
    return problems
