# สารบัญเอกสารโมดูล

ภาพรวมระบบ: [README.md](../../README.md) · สถาปัตยกรรม: [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
README ของโมดูลเก็บไว้ **ข้างโค้ด** เพื่อให้แก้พร้อมกัน; ไฟล์นี้เป็นแค่สารบัญ

| โมดูล | หน้าที่ (หนึ่งบรรทัด) | เอกสาร | เทสต์หลัก |
|---|---|---|---|
| `session/` | state machine ต่อกลุ่ม, merge preference, prefilter | [session/README.md](../../session/README.md) | `tests/unit/test_merge.py`, `tests/integration/test_session_flow.py`, sandbox |
| `features/` | ค้นหา + Haversine + จัดอันดับ, การ์ด LINE, geo | [features/README.md](../../features/README.md) | `tests/unit/test_geo.py`, sandbox 02 |
| `adapters/` | LLM (Gemini + rules), Places, LINE, lexicon, data contract | [adapters/README.md](../../adapters/README.md) | `tests/unit/test_extractor.py`, sandbox 06, eval |
| `store/` | memory / Postgres / DynamoDB ภายใต้ `Store` Protocol | [store/README.md](../../store/README.md) | `tests/contract/`, `tests/integration/test_aws.py` |
| `handlers/` | Lambda webhook + worker + SSM | [handlers/README.md](../../handlers/README.md) | `tests/unit/test_webhook_handler.py`, `test_worker_handler.py` |
| `scripts/` | simulate, local server, smoke, eval, local Postgres | [scripts/README.md](../../scripts/README.md) | ใช้ร่วมกับเทสต์ (`events.py`) |
| `tests/` | โครงชุดทดสอบทุกชั้น | [tests/README.md](../../tests/README.md) | - |
| `config.py`, `wiring.py` | Settings/env vars, การประกอบ engine | ตาราง env ใน [README.md](../../README.md#config--environment-variables) | `tests/integration/test_caps.py` |
| `template.yaml` | AWS SAM: Lambda, SQS FIFO + DLQ, DynamoDB, alarms, budget | [docs/DEPLOY.md](../DEPLOY.md) | `make template-lint`, CI job `template` |

## เอกสารระดับโปรเจกต์
| เอกสาร | เรื่อง |
|---|---|
| [ARCHITECTURE.md](../ARCHITECTURE.md) | flow, state machine, cost guards, failure modes |
| [ENVIRONMENTS.md](../ENVIRONMENTS.md) | local (Postgres) vs AWS; ตารางว่าอะไรพิสูจน์ที่ไหน |
| [DEPLOY.md](../DEPLOY.md) · [LAUNCH_CHECKLIST.md](../LAUNCH_CHECKLIST.md) | deploy และ go/no-go |
| [TEST_STRATEGY.md](../TEST_STRATEGY.md) | pyramid, PR vs nightly vs release, coverage, flaky policy, DoD |
| [TEST_POLICY.md](../TEST_POLICY.md) · [TEST_SPEC.md](../TEST_SPEC.md) · [TESTING.md](../TESTING.md) | นโยบาย, ตารางเคส, คอร์สเทส |
| [BACKLOG.md](../BACKLOG.md) | งานค้าง (เจ้าของคือทีมอื่น) |

## กติกาดูแลเอกสารโมดูล
- เปลี่ยน public interface, invariant หรือเพิ่มไฟล์ในโมดูล -> แก้ README ของโมดูลนั้นใน PR เดียวกัน (อยู่ใน PR checklist)
- README โมดูลมี 6 หัวข้อเสมอ: หน้าที่, Public interface, Data flow, Invariants, How to extend, เทสต์ที่ครอบ
- docstring ในโค้ดจะเติมทีหลัง; README ไม่ซ้ำเนื้อหา docstring แต่ชี้ไปหา
