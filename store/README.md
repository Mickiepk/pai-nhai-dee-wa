# store/ : การเก็บ state (memory, Postgres, DynamoDB)

## หน้าที่
เก็บ 3 อย่างเท่านั้น: **session** ของกลุ่ม (สัญญาณที่สกัดแล้ว), **event ที่เห็นแล้ว** (idempotency), **ตัวนับโควตารายวัน**
ทุกอย่างมี TTL ไม่เก็บถาวร (PDPA)

| ไฟล์ | ใช้เมื่อ | หมายเหตุ |
|---|---|---|
| `base.py` | - | `Store` Protocol + ค่าคงที่ `EVENT_TTL_S` (24 ชม.), `COUNTER_TTL_S` (2 วัน) |
| `memory.py` | เทสต์, simulate, local | thread-safe ด้วย lock; เก็บ session เป็น JSON เหมือน Dynamo; `dump()` ไว้ assert ว่าไม่มีข้อความดิบ |
| `postgres.py` | local / CI (`STORE=postgres`) | 3 ตาราง (`store/schema.sql`) สร้างเองซ้ำได้; purge ทุก 200 เขียน หรือ `purge_expired(now)`; `reset()` สำหรับเทสต์ |
| `dynamo.py` | AWS (`STORE=dynamo`) | single table `pk`/`sk`, TTL attribute `ttl`; conditional write สำหรับ dedup |

## Public interface (`store/base.Store`)
```python
seen_event(event_id, now) -> bool     # True = เคยเห็นแล้ว (ซ้ำ); ถ้าไม่เคย ทำเครื่องหมายทันที (atomic)
forget_event(event_id) -> None        # ยกเลิก seen_event เมื่อประมวลผลล้มเหลว เพื่อให้ SQS retry ไม่ถูกข้าม
get_session(group_id) -> Session | None
put_session(session) -> None
delete_session(group_id) -> None
incr(key, now) -> int                 # นับ +1 แบบ atomic คืนค่าใหม่ เช่น QUOTA#GROUP#g#20261116
```
ทุกเมธอดรับเวลา `now` (epoch วินาที) จากข้างนอก ไม่เรียกนาฬิกาเอง ทำให้เทสต์ TTL ได้แบบ deterministic

## Data flow
`SessionEngine` -> `Store` เท่านั้น (ไม่แตะ DB ตรง) · `wiring.build_engine` เลือกตัวจาก `Settings.store_provider` ·
`seen_event` อยู่หน้าสุดของ `engine.handle`; `forget_event` ถูกเรียกเมื่อ `_dispatch` โยน exception

## Invariants
1. **ทุก store ประพฤติเหมือนกัน** (พิสูจน์ด้วย `tests/contract/test_store_contract.py`)
2. `seen_event` / `incr` เป็น atomic ภายใต้การเรียกพร้อมกัน (memory: lock, Postgres: `ON CONFLICT`, Dynamo: conditional/update expression)
3. หมดอายุ: event ถือว่าซ้ำเมื่อ `expires_at >= now` (ขอบเขตเดียวกับ DynamoDB `ttl < now` = หมดอายุ); TTL ของตัวนับตั้งตอนนับครั้งแรก
4. `get_session` **ไม่ซ่อน** session ที่หมดอายุแต่ยังไม่ถูกลบ (เหมือน DynamoDB) engine เช็ก `Session.is_expired` เอง
5. ห้ามเก็บข้อความแชตดิบ (`Session.model_dump_json()` มีแต่สัญญาณ; `Session.ended` ถูก `exclude`)
6. `psycopg` อยู่ใน `requirements-dev.txt` เท่านั้น ไม่เข้า Lambda (import แบบ lazy ใน `wiring`)

## How to extend: เพิ่ม store ใหม่ (เช่น Redis, SQLite)
1. สร้าง `store/<name>.py` ให้ครบ 7 เมธอดของ `Store` (ไม่ต้อง inherit; Protocol เป็น structural) ใช้ `EVENT_TTL_S` / `COUNTER_TTL_S`
2. ทำ `seen_event` และ `incr` ให้ atomic จริง (อย่า read-then-write)
3. เพิ่มค่าใน `Literal` ของ `Settings.store_provider` และ branch ใน `wiring.build_engine` (import แบบ lazy)
4. **เพิ่ม param ใน fixture `store` ของ `tests/contract/test_store_contract.py`** แล้วรันให้ผ่านทั้งชุด นี่คือเกณฑ์ว่า store ใช้ได้
5. ถ้ามี DB จริง: เพิ่ม service ใน `docker-compose.yml` และ `.github/workflows/ci.yml` (ดูตัวอย่าง Postgres) แล้วเขียนลงตาราง "อะไรพิสูจน์ที่ไหน" ใน `docs/ENVIRONMENTS.md`
6. ถ้าเปลี่ยน schema Postgres: แก้ `schema.sql` ให้ idempotent (`IF NOT EXISTS`) ห้ามทำลายข้อมูลเดิมแบบเงียบๆ

## เทสต์ที่ครอบ
| ไฟล์ | ครอบ |
|---|---|
| `tests/contract/test_store_contract.py` | dedup, forget, session roundtrip, TTL ด้วย `now` ที่ฉีด, counter, thread-safety (memory/Postgres), ครบ 3 store |
| `tests/integration/test_aws.py` | DynamoStore + worker ผ่าน moto |
| `tests/sandbox/scenarios/04_lifecycle.yaml` (SBX-46..48) | webhook ซ้ำ, crash แล้ว retry |
| `STORE=postgres make test-pg` | เทสต์ทั้งชุดบน Postgres |
| ยังไม่ได้ครอบ | DynamoDB TTL ลบจริง, throughput, IAM (AWS เท่านั้น) ดู docs/ENVIRONMENTS.md |
