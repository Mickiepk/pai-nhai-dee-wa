# QA Report สุดท้าย (Final Gate ก่อน Gate 0) · ถึงคุณ Mickie

วันที่ 2026-11-16 · ฐาน commit `a305c06` + งานรอบนี้ · ออฟไลน์ล้วน (ไม่มี key จริง, ไม่มี AWS) · วนครบ 1 รอบก็เขียวทั้งหมด (ไม่ต้องรอบ 2-4)

## 1. ผลต่อหัวข้อ
| รายการ | ผล |
|---|---|
| `make ci` (ruff + pytest พร้อม coverage + sandbox + sam validate --lint + cfn-lint) | PASS · coverage 93.8% (เกณฑ์ 85%) |
| `make test-pg` (ทั้งชุดบน Postgres จริงในเครื่อง) | PASS · 367 passed, 4 skipped, 0 xfail |
| `make sandbox` | PASS · **72/72 เคส** (เดิม 62 + ใหม่ 10) |
| Determinism | **72/72 เหมือนกันทุก byte** ใน 5 รันใหม่ + 5 รันที่สลับลำดับ Places/ชื่อสมาชิก · session_id ไม่ seed ก็เท่ากัน · รายงานที่สร้างซ้ำ `diff` เหมือนกันทั้งไฟล์ |
| `scripts/eval_intents.py` (กฎออฟไลน์) | 27/27 = 100% ทุกฟิลด์ |
| `make simulate-pg` | PASS (จบที่ session ended) |
| `make template-lint` / `make lint-actions` | PASS / PASS |
| ทั้งชุดบน Postgres + `GEMINI_PAID_TIER=true` ค้างใน shell | PASS (พิสูจน์ว่า env ไม่รั่วแล้ว) |

## 2. สิ่งที่แก้ตามที่ตั้งไว้
- **ruff E501 x2 (engine.py)**: แก้แล้ว ตอนนี้ `ruff check .` สะอาด
- **test_caps ล้มบน Postgres full run**: root cause = **env รั่วจาก shell/เทสก่อนหน้า** `GEMINI_PAID_TIER=true` ทำให้ engine เห็นว่าเป็น paid tier (engine อ่าน env ตอนเรียก) ทำให้เทส "ไม่ paid" และ SBX-43 ล้ม (ทำซ้ำได้ด้วย `GEMINI_PAID_TIER=true make test-pg`) แก้ที่ต้นเหตุ: `tests/conftest.py` มี autouse fixture ล้าง env ที่กระทบ behaviour (GEMINI_PAID_TIER, BOT_ENABLED, *_PROVIDER ...) ทุกเทส และ sandbox harness ล้างเองด้วย (กรณีรัน `make sandbox` ตรงๆ) ไม่ได้ผ่อนเงื่อนไขของเทส
- **webhook dedup fallback**: เปลี่ยนจาก `hash()` (เปลี่ยนทุก process) เป็น sha256 ของ canonical JSON (`fallback_dedup_id`) เทส xfail กลายเป็น passing (รันข้าม PYTHONHASHSEED จริง) + เทสลำดับ key ต่างกันได้ id เดียวกัน
- **JSON เสียหลัง signature ถูก** -> 400 (ไม่ raise ไม่ retry) รวมกรณี `[1,2]`, `null`, `events` ไม่ใช่ list, bytes ไม่ใช่ UTF-8
- **max body 256 KB -> 413** เช็กก่อน HMAC/parse + เทสขอบ (พอดี 256 KB ผ่าน, +1 byte = 413)
- BatchSize note ยังอยู่ใน `handlers/README.md` (อัปเดตข้อสังเกตเรื่อง size/dedup ที่แก้แล้ว)

## 3. QA exploratory: 10 เคส adversarial ใหม่ (SBX-63..72) พบบั๊ก 3 ตัว แก้แล้ว
| เคส | หัวข้อ | ผลรอบแรก |
|---|---|---|
| 63 | prompt injection (EN/TH) | ผ่าน ไม่เปิด session ไม่หลุดข้อมูลภายใน |
| 64 | ข้อความ 20,000 ตัวอักษร | ผ่าน |
| 65 | อีโมจิล้วน/สแลง | **พบ BUG-21 (P3)**: "5555555555 🤣" หลุด prefilter -> เรียก LLM และถูกนับเป็นผู้ร่วม (ต้องกดตกลงด้วย) แก้ `session/prefilter.py` ตัดอีโมจิก่อนเช็กหัวเราะ/filler + เทส unit |
| 66 | สองกลุ่ม ack สลับกัน | ผ่าน |
| 67 | webhook ซ้ำกลางการ ack | ผ่าน |
| 68 | reply ล้ม (token หมดอายุ) ตอน ack คนสุดท้าย | **พบ BUG-22 (P1)**: engine ลบ session ก่อนส่ง reply ถ้า reply ล้ม retry ได้ "หมดเวลาแล้ว" แผนหาย แก้: `_end` แค่ mark, ลบหลัง reply สำเร็จ (`_persist`) |
| 69 | สมาชิกออกจากกลุ่ม | **พบ BUG-23 (P2)**: ไม่มี handler `memberLeft` และ webhook กรองทิ้ง -> รอ ack คนที่ออกไปแล้วจนหมด 60 นาที แก้: ถอดจากผู้ร่วม/ack/prefs (PDPA), กรอง `memberLeft` เข้าคิว |
| 70 | @ ในแชต 1:1 | ผ่าน (ตอบชวนเข้ากลุ่ม ไม่เรียก LLM/Places) |
| 71 | Gemini ล่ม/JSON เสีย/timeout ทั้งทาง | ผ่าน ได้แผนครบด้วยกฎออฟไลน์ |
| 72 | Places 0 ร้าน | ผ่าน |

ข้อสังเกต: ตอนเขียนเคสมี 3 จุดที่เป็นความผิดของ "เคสที่ผมเขียน" (เดาข้อความแผนผิด, วลี "@bot ลองใหม่" ไม่ใช่คำค้น, คาดว่า "จุ๊บๆ" ถูกกรอง) แก้ที่ input/ข้อความ ไม่ได้ลดเงื่อนไขที่ตรวจ ส่วนบั๊กจริงทั้ง 3 ตัวแก้ที่โค้ด

## 4. Docstring
เพิ่มให้ public interface ทุกตัวใน `session/ features/ adapters/ store/ handlers/` (ตรวจด้วย ruff D1xx = 0 รายการ) ไม่เปลี่ยน behaviour

## 5. ความเสี่ยงที่ยังเหลือ
1. **memberLeft ตอนทุกคนที่เหลือกดตกลงแล้ว**: ไม่มี replyToken ในอีเวนต์นี้ จึงปิดงานเองไม่ได้ ต้องมีคนกดตกลงอีกครั้ง (ไม่ค้างตลอดไป แต่ไม่อัตโนมัติ) ยังเป็น P3
2. **prefilter กรองตามความยาว/filler เท่านั้น**: คำสแลงไทยสั้นๆ เช่น "จุ๊บๆ" ยังถูกอ่านและนับเป็นผู้ร่วม (ผลกระทบ: ต้องกดตกลงเพิ่ม 1 คน)
3. reply ที่ล้มถาวร (token หมดอายุจริง ไม่ใช่ชั่วคราว) จะ retry 3 ครั้งแล้วเข้า DLQ ผู้ใช้ไม่เห็นผล; session ยังอยู่จนหมดเวลา
4. engine อ่าน `GEMINI_PAID_TIER` จาก env ตอนรัน (fail closed) ถ้าตั้งผิดใน Lambda ผลคือไม่อ่านแชต ไม่ใช่รั่วข้อมูล
5. Prompt injection: ทดสอบเฉพาะทางกฎ + schema validation (ผลของ LLM ถูกบังคับเป็น JSON schema, การตัดสินใจอยู่ในโค้ด) ไม่ได้ลอง jailbreak กับ Gemini จริง

## 6. สิ่งที่พิสูจน์ได้เฉพาะของจริง (ออฟไลน์พิสูจน์ไม่ได้)
- **AWS**: DynamoDB atomic `incr`/`seen_event` ภายใต้ concurrency (moto ไม่ thread-atomic: 2 เคสถูก skip), TTL ลบจริง, IAM least-privilege, FIFO ordering/DLQ redrive/visibility timeout, Function URL limit/cold start, `sam deploy`
- **Gemini จริง**: ความแม่นของ intent ภาษาไทย (eval 100% เป็นของกฎออฟไลน์ ไม่ใช่ Gemini; ใช้ `--live`), latency/timeout 4 วิ, JSON mode จริง, paid tier ว่าไม่ใช้ข้อมูลเทรน
- **Google Places จริง**: คุณภาพ/ลำดับผล, ฟิลด์ `price_level` ที่มักว่าง, geocode ชื่อย่านที่ไม่อยู่ใน AREA_CENTERS, ค่าใช้จ่ายจริงเทียบเพดาน
- **LINE จริง**: ลายเซ็น webhook จริง, อายุ reply token จริง, รูปแบบ `memberLeft`/mention จริง, การแสดงผล Flex บนมือถือ, ข้อจำกัดของ Verify

## 7. สรุป
พร้อมเข้า Gate 0 ในขอบเขตที่ทดสอบออฟไลน์ได้: ไม่มีเคสล้ม ไม่มี xfail ค้าง ไม่มี P0/P1 ที่เปิดอยู่ (BUG-22 P1 แก้แล้วพร้อมเคสถาวร) ขั้นต่อไปคือ smoke บน dev stack จริง (AWS + LINE + Gemini/Places key) ตาม `docs/LAUNCH_CHECKLIST.md`
