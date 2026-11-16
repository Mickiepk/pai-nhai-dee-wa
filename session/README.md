# session/ : หัวใจของบอท (state machine ต่อกลุ่ม)

## หน้าที่
รับ LINE event ทีละอัน (หนึ่ง event เข้า, ศูนย์ถึงหลาย reply ออก) แล้วตัดสินใจว่า **บอทควรทำอะไร**: เริ่ม session, จำความชอบ,
ค้นร้าน, ยืนยันแผน, จบ session ทุกการตัดสินใจอยู่ในโค้ดที่นี่ ไม่ใช่ใน LLM (LLM แค่สกัดสัญญาณ ดู [adapters/README.md](../adapters/README.md))

| ไฟล์ | ทำอะไร |
|---|---|
| `engine.py` | `SessionEngine` (state machine, quota, ack), `self_mentioned()`, `strip_mentions()`, `all_acked()` |
| `models.py` | `Session`, `State` (`LISTENING` / `CONFIRMING`), `UserPrefs`, `Suggestion` ข้อมูลที่ persist ได้ทั้งหมด |
| `merge.py` | `apply_delta()` รวม `MessageDelta` เข้า `Session` (latest statement wins ต่อหัวข้อ), `avoid_terms()`, `group_budget()`, รัศมี |
| `prefilter.py` | `worth_reading()` กฎถูกๆ ตัดข้อความขยะ ("555", "ok", สติกเกอร์, ลิงก์ล้วน, สั้นกว่า 3 ตัว) ก่อนเสียเงินเรียก LLM |

## Public interface

```python
engine = SessionEngine(settings, store, line, llm, places, clock=lambda: int(time.time()))
await engine.handle(event)   # event = dict ของ LINE webhook event; คืน None; reply ผ่าน line.reply(token, msgs)
```
- สร้างด้วย `wiring.build_engine(settings)` (ที่เดียวที่เลือก real vs fake) ใน test ใช้ `tests/fakes.make_engine()`
- `clock` ฉีดได้ ทำให้เทสต์เดินเวลาเองได้ (sandbox ใช้นาฬิกาแช่แข็ง)
- `handle()` โยน exception ออกมาเมื่อล้มเหลว **หลัง** เรียก `store.forget_event()` เพื่อให้ SQS retry ได้ (worker จับแล้วรายงาน `batchItemFailures`)

## Data flow

```
event -> handle(): bot_enabled? -> store.seen_event(eid)? (ซ้ำ = ทิ้ง) -> _dispatch
  join      -> reply GREETING
  leave     -> store.delete_session(gid)            (PDPA: ลบทุกอย่างของกลุ่ม)
  message   -> _on_message: ไม่มี session + ไม่ @ = ไม่อ่าน
                มี session -> prefilter -> _extract (LLM หรือกฎฟรีถ้าเกิน cap) -> apply_delta
                -> ตัดสินใจ? _confirm | @ถาม? _answer_mention | เงียบ -> put_session
  postback  -> _on_postback: act = stop | pick | area | search | ack (เช็ก sid ตรงกับ session)
_search_replies: quota กลุ่ม/วัน -> features.search.search(spend=quota Places) -> cards
```
สถานะ: `(ไม่มี) -> LISTENING <-> CONFIRMING -> จบ` แผนภาพใน [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)

## Invariants (ห้ามทำให้พัง)
1. **ไม่มี session = ไม่อ่านแชต** ข้อความที่ไม่ได้ @ ถูกทิ้งทั้งหมด
2. **บอทพูดเฉพาะ** @mention, การตัดสินใจ (decision), และการกดปุ่ม และตอบด้วย reply token ของ event นั้นเท่านั้น (ไม่ push)
3. `Session` เก็บเฉพาะ **สัญญาณที่สกัดแล้ว** ไม่มีข้อความดิบ; ห้าม log ข้อความหรือ traceback (log แค่ชื่อ exception)
4. Idempotency: `webhookEventId` เดิม = ประมวลผลครั้งเดียว; ล้มเหลว = `forget_event` เพื่อให้ retry ได้
5. Confirmation rule: ใครกดปุ่มก็ถูกบันทึกเป็น participant **ก่อน** (ทั้ง ตกลง และ ยังก่อน) แผนออกเมื่อ `participants` ทุกคนอยู่ใน `acks`
6. เพดานงบ: LLM ต่อ session, ค้นต่อกลุ่มต่อวัน, Places รวมต่อวัน (ทุกการเรียก รวม geocode), kill switch `BOT_ENABLED`
7. `apply_delta` เป็นฟังก์ชันล้วน: input เดิม = ผลเดิม (deterministic) ลำดับที่เท่ากันตัดสินด้วย key คงที่
8. `postback` ที่ `sid` ไม่ตรง/session หมดอายุ -> ตอบ "หมดเวลาแล้ว" ไม่ error

## How to extend
- **เพิ่มชนิดงาน (เช่น `meetup` เต็มรูปแบบ)**: เพิ่มโมดูลคำค้น/รัศมีใน `features/` (ดู `food.py`), เพิ่มคำใน `adapters/llm.py`,
  ปรับ `merge.current_radius` และ `search.build_query`, เพิ่ม scenario ใน `tests/sandbox/scenarios/`
- **เพิ่ม field ที่ LLM สกัด**: เพิ่มใน `adapters/models.MessageDelta` (ต้อง default ได้ เพื่อ schema เก่ายังผ่าน), รวมใน `merge.apply_delta`, เพิ่ม unit test ใน `tests/unit/test_merge.py`
- **เพิ่มปุ่ม/postback ใหม่**: เพิ่ม `act` ใน `_on_postback` + การ์ดใน `features/cards.py` + step `tap` ใน sandbox harness (`_ACTS`)
- **เพิ่มเพดานงบใหม่**: field ใน `config.Settings` + `load_settings` + `.env.example` + ตาราง cost guards ใน README + scenario ใน `05_caps_privacy.yaml`
- ห้ามเพิ่ม side effect ภายนอกที่ไม่ผ่าน `Store`/`LineGateway`/`Places`/`Extractor` (เทสต์จะฉีดของปลอมไม่ได้)

## เทสต์ที่ครอบ
| ไฟล์ / scenario | ครอบอะไร |
|---|---|
| `tests/unit/test_prefilter.py` | `worth_reading` |
| `tests/unit/test_merge.py`, `test_lexicon_and_radius.py` | `apply_delta`, รัศมี, avoid |
| `tests/unit/test_ack.py` | `all_acked`, confirmation rule |
| `tests/integration/test_session_flow.py` | flow เต็ม start -> confirm -> plan |
| `tests/integration/test_caps.py` | LLM cap, search cap, Places cap, kill switch, paid tier |
| `tests/integration/test_bugfixes.py`, `tests/unit/test_round1_fixes.py` | regression ของบั๊กที่แก้แล้ว |
| `tests/sandbox/scenarios/01..07_*.yaml` | บทสนทนาเต็มเรื่อง + determinism |
| `tests/unit/test_worker_handler.py` | engine + retry/idempotency ผ่าน worker |
