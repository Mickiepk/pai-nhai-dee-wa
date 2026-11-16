"""Table-driven spelling normaliser for the offline rules (slang, typos, simple English).

`normalize(text)` rewrites known variants to the canonical Thai term the rules and the
Places fixtures use. One regex pass, longest variant first, so results are deterministic.
Latin variants only match as whole words ("thai" never matches inside "thailand").
Add a row to ALIASES to teach the bot a new spelling; no other code changes needed.
"""

from __future__ import annotations

import re

# canonical -> variants (all lowercase). The canonical spelling itself need not be listed.
ALIASES: dict[str, list[str]] = {
    # cuisines / food
    "ญี่ปุ่น": ["japanese", "japan", "ญีปุ่น", "ยี่ปุ่น", "ญี่ปุ่", "ญปน", "ญป", "jp food"],
    "เกาหลี": ["korean", "korea", "เกาหรี", "เกาลี"],
    "จีน": ["chinese", "china"],
    "ไทย": ["thai"],
    "อิตาเลียน": ["italian", "อิตาลี", "อิตาเลี่ยน"],
    "บุฟเฟต์": ["buffet", "บุฟเฟ่ต์", "บุฟเฟ่", "บุฟเฟต", "บุปเฟ่ต์", "บุปเฟ่", "บุฟเฟ", "บุฟ"],
    "ปิ้งย่าง": ["bbq", "yakiniku", "ยากินิกุ", "ปิ้งๆย่างๆ"],
    "หมูกระทะ": ["หมูกะทะ", "หมูกระทะ", "mookata", "moo kata"],
    "ชาบู": ["shabu", "ชาบูๆ"],
    "สุกี้": ["suki", "sukiyaki", "สุกี้ยากี้"],
    "ซูชิ": ["sushi", "สูชิ"],
    "ราเมน": ["ramen", "ราเมง", "ราเมน"],
    "ส้มตำ": ["somtam", "som tam", "ส้มตัม"],
    "ก๋วยเตี๋ยว": ["ก๊วยเตี๋ยว", "ก๋วยเตี้ยว", "ก๋วยเตี๊ยว", "ก๊วยเตี๊ยว", "noodle", "noodles"],
    "ซีฟู้ด": ["seafood", "ซีฟู๊ด", "อาหารทะเล"],
    "สเต๊ก": ["steak", "สเต็ก", "สเต็ค", "สเต๊ค"],
    "พิซซ่า": ["pizza", "พิซซา", "พิซซ่า", "พิชซ่า", "พิสซ่า"],
    "คาเฟ่": ["cafe", "café", "coffee", "คาเฟ", "กาแฟ"],
    "ของหวาน": ["dessert"],
    "มังสวิรัติ": ["vegetarian", "vegan"],
    "ฮาลาล": ["halal"],
    # activities
    "โบว์ลิ่ง": ["bowling", "โบลิ่ง", "โบว์ลิ้ง", "โบลิ้ง", "โบว์ลิง"],
    "คาราโอเกะ": ["karaoke", "คาราโอเก", "คาราโอเกะ", "คาราโอเค", "คาราโอเก้", "คาราโอเกะ"],
    "ดูหนัง": ["movie", "movies", "cinema", "ดูหนัง"],
    "พิพิธภัณฑ์": ["museum", "พิพิธภันฑ์"],
    "บอร์ดเกม": ["board game", "boardgame", "บอร์ดเกมส์", "บอร์ดเกม"],
    "ปีนผา": ["climbing", "ปีนหน้าผา"],
    # areas
    "อารีย์": ["ari", "อารีย", "อารี"],
    "สยาม": ["siam", "สยามฯ", "สยามสแควร์"],
    "สาทร": ["sathorn", "sathon"],
    "สีลม": ["silom"],
    "อโศก": ["asoke", "asok", "อโศกฯ"],
    "ทองหล่อ": ["thonglor", "thong lo", "thonglo", "ทองหลอ"],
    "เอกมัย": ["ekkamai", "ekamai", "เอกกมัย"],
    "พร้อมพงษ์": ["phrom phong", "phromphong", "พร้อมพงศ์"],
    "จตุจักร": ["chatuchak", "jatujak", "จตุจักรฯ", "จตุจักร"],
    "ลาดพร้าว": ["ladprao", "lat phrao"],
    "รัชดา": ["ratchada", "รัชดาฯ"],
}

# "บุฟ" alone is risky ("บุฟเฟต์" is matched first because longer variants win at a position).
_LATIN = re.compile(r"^[a-z0-9 ]+$")


def _build() -> tuple[re.Pattern[str], dict[str, str]]:
    lookup: dict[str, str] = {}
    for canon, variants in ALIASES.items():
        for v in [canon, *variants]:
            lookup[v.lower()] = canon
    parts = []
    for v in sorted(lookup, key=len, reverse=True):
        p = re.escape(v)
        if _LATIN.match(v):
            p = rf"(?<![a-z0-9]){p}(?![a-z0-9])"
        parts.append(p)
    return re.compile("|".join(parts)), lookup


_PATTERN, _LOOKUP = _build()


def normalize(text: str) -> str:
    """Lowercase and rewrite known spellings to canonical Thai terms."""
    return _PATTERN.sub(lambda m: _LOOKUP[m.group(0)], text.lower())


def canonical_term(term: str) -> str:
    """Canonical form of one extracted keyword (used on LLM output)."""
    return normalize(term).strip()
