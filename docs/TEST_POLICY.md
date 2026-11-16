# นโยบายการทดสอบ "ไปไหนดีวะ" (Test Policy) · v1 · 2026-11-16 · QA

## 1. "Deterministic" ของบอทนี้หมายถึงอะไร
**ลำดับ event เดิม + นาฬิกาเดิม + คำตอบของ fake เดิม ⇒ ได้ reply, state และ side effect เหมือนเดิมทุก byte**
- reply = JSON ที่ส่งเข้า LINE reply API (ข้อความ, flex, ปุ่ม, postback data)
- state = สิ่งที่อยู่ใน store (session, quota counter, event ที่เห็นแล้ว)
- side effect = จำนวนและเนื้อหาการเรียก LLM / Places / LINE
- ต้องไม่ขึ้นกับลำดับที่ dependency ส่งผลมา (เช่น Places ส่งร้านมาคนละลำดับ หรือ dict ชื่อสมาชิกเรียงต่างกัน) ถ้าความหมายเท่ากัน ผลต้องเท่ากัน

## 2. คุม LLM จริงที่ไม่ deterministic ยังไง
| ชั้น | กติกา |
|---|---|
| เรียก LLM | `temperature=0`, `max_output_tokens` จำกัด, timeout 4 วิ |
| ผลลัพธ์ | ต้องเป็น JSON ตาม schema `MessageDelta` (pydantic validate) ผิด schema / JSON เสีย / timeout ⇒ ใช้กฎออฟไลน์แทน และยังตอบได้ |
| สิ่งที่ LLM ทำได้ | แค่ "สกัดสัญญาณ" (ชอบ/ไม่เอา/ย่าน/ตัดสินใจ) ห้ามสร้างชื่อร้าน ระยะ หรือข้อความที่ส่งให้ผู้ใช้ |
| การตัดสินใจ | ทำในโค้ดเท่านั้น: เมื่อไรพูด, state machine, ใครต้องกด ✅, รัศมี, Haversine, จัดอันดับ, เพดานงบ |
| ใน CI | ห้ามเรียก LLM จริง ใช้กฎ หรือ GeminiExtractor ตัวจริงที่เปลี่ยน client เป็น "สคริปต์" คืน JSON ตาม input ความแม่นของ LLM จริงวัดแยกเป็น % ใน eval set (`scripts/eval_intents.py`) ไม่ใช่ pass/fail |

## 3. กติกา Sandbox (`make sandbox`, `tests/sandbox/`)
1. **ไม่มี network**: FakeLine, FakePlaces/fixture, MemoryStore, scripted LLM ไม่มี key จริง
2. **นาฬิกาแช่แข็ง**: เริ่มที่ `1_800_000_000` เดินเฉพาะ step `advance` เท่านั้น
3. **Randomness ต้อง seed**: uuid ของ session ถูกแทนด้วย generator ที่ seed ไว้ ลำดับที่เท่ากัน (tie) ต้องตัดสินด้วย key คงที่ (เช่น `place_id`) ไม่ใช่ลำดับที่ API ส่งมา
4. **Fake เท่านั้น**: event id, reply token สร้างแบบนับเลขต่อ run
5. **Determinism check**: ทุก scenario รัน 5 ครั้งใน engine ใหม่ + 5 ครั้งแบบสลับ setup ที่ความหมายเท่ากัน ต้องได้ transcript และ final state เหมือนกันทุก byte

## 4. ระดับความรุนแรง
| ระดับ | นิยาม | ตัวอย่าง |
|---|---|---|
| P0 | ผิดกฎหมาย/เงินรั่ว/ระบบล่ม | เก็บข้อความแชตดิบ, ส่งแชตเข้า Gemini ฟรี, เพดานงบไม่ทำงาน, event หาย |
| P1 | ผิดสัญญาหลักของ product | บอทพูดเองโดยไม่ถูกเรียก, ร้านเกินรัศมี, แผนออกก่อนทุกคนกด ✅ |
| P2 | ใช้งานได้แต่ผิดจากที่ผู้ใช้ขอ | ไม่สนงบ, เลือกร้านผิดลำดับ, ไม่ deterministic เมื่อ API สลับลำดับ |
| P3 | ข้อความ/ความสวยงาม/เครื่องมือ dev | ถ้อยคำผิดบริบท, ประกาศขาดข้อมูลเล็กน้อย |

## 5. เกณฑ์ผ่าน/ไม่ผ่าน สำหรับ pilot
- **Gate 0 (เข้ากลุ่มทดลองภายใน)**: `make test` และ `make sandbox` เขียว, determinism 100% ของ scenario ที่ไม่มีบั๊กเปิด, **P0 = 0, P1 = 0**, P2 ทุกตัวมีเจ้าของและกำหนดแก้
- **Gate 1 (กลุ่มเพื่อนจริง)**: ผ่าน Gate 0 + P2 ที่แตะความเชื่อใจ (งบ, เลือกร้าน, จุดอ้างอิง) ปิดหรือ product ยอมรับเป็นลายลักษณ์อักษร + เช็กมือกับ LINE จริง (Level 4 ใน TESTING.md) ผ่าน
- ไม่ผ่านทันทีถ้า: มีเคส `FAIL` ที่ไม่มีบั๊กผูก, มี `XPASS` ที่ยังไม่อัปเดต spec, หรือ determinism หลุด

## 6. นโยบาย regression
- **ทุกบั๊กต้องมีเทส**: เพิ่ม scenario ใน `tests/sandbox/scenarios/` (หรือ unit test) พร้อม `bug: BUG-xx` ⇒ pytest ทำเป็น `xfail(strict=True)` เพื่อให้ `make test` ยังเขียวแต่บั๊กถูกติดตาม
- เมื่อ dev แก้ เทสจะ **XPASS แล้วทำให้รันพัง** ⇒ dev ต้องลบ `bug:` ออกใน PR เดียวกัน เทสนั้นกลายเป็น regression test ถาวร
- ห้ามแก้ expectation ให้ตรงกับพฤติกรรมที่ผิดเพื่อให้เขียว ถ้า product เปลี่ยนสเปก ให้แก้ TEST_SPEC.md + scenario พร้อมอ้างอิงการตัดสินใจ
- QA ไม่แก้ production code ส่งบั๊กให้ web-dev พร้อม case ID ที่ทำซ้ำได้
