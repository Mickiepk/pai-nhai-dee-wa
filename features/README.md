# features/ : ฟีเจอร์ที่เป็นโค้ดล้วน (ค้นหา, การ์ด, ระยะทาง)

## หน้าที่
สิ่งที่ผู้ใช้เห็นและตัวเลขที่ผู้ใช้เชื่อใจ **ทั้งหมดคำนวณที่นี่ ไม่ใช่โดย LLM**: ร้านไหน, ห่างกี่กม., ข้อความและปุ่มบนการ์ด

| ไฟล์ | ทำอะไร |
|---|---|
| `search.py` | pipeline: anchor (`resolve_center`) -> `Places.search_text` -> กรองด้วย Haversine -> ตัดของที่ avoid -> `rank` เหลือ 3 ที่ -> `SearchOutcome` |
| `cards.py` | สร้าง LINE message (`text`, `flex`): `listening_notice`, `suggestions`, `confirm`, `plan`, `announcement`, `vote_stub` |
| `geo.py` | `haversine_km`, `AREA_CENTERS` (ย่านยอดฮิตมีพิกัดในโค้ด ไม่เสีย geocode), `format_km`, `maps_link` |
| `food.py`, `activity.py` | ค่าประจำชนิดงาน: `BASE_QUERY`, `RADIUS_KM` (food 3 กม., activity 5 กม.) |
| `meetup.py` | ที่ว่างสำหรับชนิดงาน meetup (ยังไม่มีลอจิก) |

## Public interface
```python
outcome = await search.search(session, places, exclude_last=False, spend=callable_or_None)
# SearchOutcome(suggestions: list[Suggestion], radius_km: float, error: None|"no_area"|"not_found"|"places_failed"|"cap")
msgs = cards.suggestions(session, outcome.suggestions, header)   # list[Msg] พร้อมส่ง line.reply
```
`spend()` คือ callback จอง 1 ครั้งของโควตา Places รายวัน (engine ส่งมา); คืน `False` = ชนเพดาน -> `error="cap"`

## Data flow
`Session` (area, group_wants, radius, prefs) -> `build_query` -> `resolve_center` (AREA_CENTERS หรือ geocode ที่นับโควตา) ->
`PlaceCandidate[]` -> เติม `distance_km` ด้วย Haversine -> กรองนอกรัศมี/avoid/เกินงบ -> `rank` -> `Suggestion[]` -> `cards`

## Invariants
1. **ทุกร้านที่เสนอต้องอยู่ในรัศมี** (ระยะเส้นตรง Haversine) ระยะที่แสดงมาจากโค้ด ไม่ใช่จาก LLM/Places
2. ทุก Places call (search **และ** geocode) ต้องผ่าน `spend()` เมื่อมี
3. ผลลัพธ์ deterministic: ลำดับที่เท่ากันตัดด้วย `place_id` ไม่ขึ้นกับลำดับที่ API ส่งมา
4. การ์ดต้องมี attribution "ข้อมูลร้านจาก Google Maps" และมีปุ่ม **[หยุดฟัง]** ใน listening notice (PDPA)
5. `search()` ไม่โยน exception เรื่อง Places ใช้ `error=` แทน (engine แปลงเป็นข้อความ)
6. ไม่มีข้อความแชตดิบเข้า/ออกจากโมดูลนี้

## How to extend
- **ย่านใหม่ที่ไม่ต้องเสีย geocode**: เพิ่มใน `geo.AREA_CENTERS` และเพิ่มชื่อใน `adapters/llm.AREAS` (หรือ `adapters/lexicon.py` ถ้าเป็นคำสะกดแปลก)
- **ชนิดงานใหม่**: เพิ่ม `features/<kind>.py` (`BASE_QUERY`, `RADIUS_KM`) แล้วต่อใน `session/merge.current_radius` และ `search.build_query`
- **เปลี่ยนวิธีจัดอันดับ**: แก้ `rank()` เท่านั้น เพิ่ม unit test ที่ทดสอบลำดับเท่ากัน (tie) และ sandbox determinism
- **การ์ดใหม่**: ฟังก์ชันใน `cards.py` คืน `Msg`; LINE รับสูงสุด 5 message ต่อ reply

## เทสต์ที่ครอบ
| ไฟล์ | ครอบ |
|---|---|
| `tests/unit/test_geo.py` | Haversine, format, AREA_CENTERS |
| `tests/integration/test_session_flow.py` | search + cards ใน flow จริง |
| `tests/sandbox/scenarios/02_prefs_geo.yaml` | รัศมี, ย่าน, geocode, จุดอ้างอิง, ข้าม avoid |
| `scripts/eval_intents.py --places` | ร้านจริง/ในรัศมี (ฟรีกับ FakePlaces) |
