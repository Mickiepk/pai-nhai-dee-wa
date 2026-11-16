# adapters/ : ขอบเขตกับโลกภายนอก (LLM, Places, LINE)

## หน้าที่
ทุกอย่างที่ออกนอก process อยู่หลัง Protocol ที่นี่ ทุกตัวมี **ของจริง** และ **ของปลอมที่ deterministic** ให้ engine เลือกผ่าน `wiring.build_engine`

| ไฟล์ | Protocol | ของจริง | ของปลอม |
|---|---|---|---|
| `llm.py` | `Extractor.extract(text, *, mentioned, context) -> MessageDelta` | `GeminiExtractor` (google-genai, timeout 4 วิ, fallback เป็นกฎ) | `RuleExtractor` (กฎออฟไลน์ ใช้เป็น fallback ใน production ด้วย) |
| `places.py` | `Places.search_text(query, center, radius_km)`, `Places.geocode(name)` | `GooglePlaces` (Places API New, field mask) | `FakePlaces` (fixture, นับการเรียก) |
| `line.py` | `LineGateway.reply(token, msgs)`, `member_name(gid, uid)` + `verify_signature()` | `RealLine` (line-bot-sdk v3 async) | `FakeLine` (เก็บ reply ในลิสต์) |
| `models.py` | - | - | data contract: `MessageDelta`, `PlaceCandidate`, `LatLng` |
| `lexicon.py` | - | - | ตาราง slang/typo/อังกฤษ -> ไทยมาตรฐาน (`normalize`, `canonical_term`) |

## Public interface
```python
class Extractor(Protocol):
    async def extract(self, text: str, *, mentioned: bool, context: dict) -> MessageDelta: ...
class Places(Protocol):
    async def search_text(self, query: str, center: LatLng, radius_km: float) -> list[PlaceCandidate]: ...
    async def geocode(self, name: str) -> LatLng | None: ...
class LineGateway(Protocol):
    async def reply(self, reply_token: str, messages: list[Msg]) -> None: ...
    async def member_name(self, group_id: str, user_id: str) -> str: ...
```

## Data flow
`ข้อความ` -> `lexicon.normalize` -> (Gemini | rules) -> `MessageDelta` (pydantic validate) -> `session.merge.apply_delta`
Gemini timeout / JSON เสีย / ผิด schema -> `RuleExtractor` ตอบแทน (บอทยังตอบได้)

## Invariants
1. **`MessageDelta` ไม่มีข้อความดิบ** และ LLM ห้ามสร้างชื่อร้าน ระยะ หรือข้อความที่ส่งให้ผู้ใช้ (docs/TEST_POLICY.md ข้อ 2)
2. LLM: `temperature=0`, output จำกัด, timeout 4 วิ, ผลต้องผ่าน schema `MessageDelta` ไม่งั้น fallback
3. `distance_km` ใน `PlaceCandidate` เติมโดยโค้ด (Haversine) ไม่ใช่ adapter
4. `verify_signature` **fail closed**: secret ว่างหรือไม่มี signature = `False`; เทียบด้วย `hmac.compare_digest`
5. `RealLine.reply` ส่งสูงสุด 5 messages; ห้ามเพิ่ม push
6. Import ของ SDK หนัก (`google.genai`, `linebot`) เป็น lazy เพื่อให้เทสต์และ cold start เบา
7. ไม่ log payload/ข้อความ (log แค่จำนวนและชนิด)

## How to extend

### เพิ่ม LLM provider ใหม่ (เช่น OpenAI, Claude)
1. เขียนคลาสใน `adapters/llm.py` (หรือไฟล์ใหม่) ที่มี `async def extract(...) -> MessageDelta` รับ `fallback: RuleExtractor` ใน constructor
2. เรียก API แบบ `temperature=0`, timeout สั้น, ขอ JSON ตาม schema, `MessageDelta.model_validate` แล้ว `except Exception: return fallback.extract_sync(...)`
3. เพิ่มค่าใน `Literal` ของ `Settings.llm_provider` (`config.py`) และ key ใหม่ (`<X>_API_KEY` + `handlers/ssm.py` `_SECRETS` + `template.yaml` Parameters/Policies/`.env.example`)
4. เพิ่ม branch ใน `wiring.build_engine`
5. **PDPA**: ตัดสินใจว่า provider นี้ใช้ prompt ฝึกโมเดลหรือไม่ แล้วปรับ `Settings.chat_reading_enabled` ให้สอดคล้อง (ค่าเริ่มต้นต้องปลอดภัย = ไม่อ่านแชต)
6. เทสต์: ใช้รูปแบบเดียวกับ `tests/sandbox/harness.ScriptedLLM` (ครอบ client ด้วยสคริปต์ที่ตอบ JSON) ห้ามเรียกเครือข่ายจริงใน CI; วัดความแม่นจริงด้วย `scripts/eval_intents.py --live`

### เพิ่ม Places provider
Implement `Places` (2 เมธอด) คืน `PlaceCandidate` ที่มี `place_id`, `latlng` ถูกต้อง แล้วต่อ `Settings.places_provider` + `wiring.py` ทุก call ที่เสียเงินต้องถูกนับโดย caller ผ่าน `spend()` อยู่แล้ว ไม่ต้องนับเอง

### เพิ่มคำสแลง/พิมพ์ผิด (ทางที่ถูกที่สุด)
เพิ่มแถวใน `lexicon.ALIASES` (deterministic) + เคสใน `tests/unit/test_lexicon_and_radius.py` + utterance ใน `tests/eval/utterances.jsonl`

## เทสต์ที่ครอบ
| ไฟล์ | ครอบ |
|---|---|
| `tests/unit/test_extractor.py` | `RuleExtractor` ทุก intent/ฟิลด์ |
| `tests/unit/test_lexicon_and_radius.py` | lexicon + รัศมี |
| `tests/integration/test_webhook.py`, `tests/unit/test_webhook_handler.py` | `verify_signature` ผ่าน webhook |
| `tests/sandbox/scenarios/06_robustness.yaml` (SBX-50..52) | Gemini ล้ม/JSON เสีย/ช้า ผ่าน `ScriptedLLM` |
| `tests/eval/utterances.jsonl` + `scripts/eval_intents.py` | ความแม่นของการสกัด (เป็น %) |
| ยังไม่ได้ครอบ | `RealLine`, `GooglePlaces`, `GeminiExtractor` กับเครือข่ายจริง (พิสูจน์ได้เฉพาะด้วย key จริง, Level 3-4 ใน docs/TESTING.md) |
