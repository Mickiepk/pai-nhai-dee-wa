# tests/ : ชุดทดสอบทั้งหมด

ทุกเทสต์ **ไม่แตะเครือข่าย** ใช้ของปลอม (FakeLine, FakePlaces, RuleExtractor/ScriptedLLM, MemoryStore/Postgres ในเครื่อง/moto)
กลยุทธ์ภาพรวม: [docs/TEST_STRATEGY.md](../docs/TEST_STRATEGY.md) · นิยาม deterministic และระดับ P0-P3: [docs/TEST_POLICY.md](../docs/TEST_POLICY.md)

```bash
make test           # ทั้งชุด (STORE=memory)
make cov            # + coverage gate
make test-pg        # ทั้งชุดบน Postgres (STORE=postgres)
pytest tests/unit -q                       # เฉพาะชั้น
pytest tests/unit/test_worker_handler.py   # ไฟล์เดียว
pytest -k "poison"                         # ตามชื่อ
```
ค่า `asyncio_mode = "auto"` (`pyproject.toml`) เทสต์ `async def` รันได้เลย; **เทสต์ที่เรียก handler ของ Lambda (ใช้ `asyncio.run`) ต้องเป็น `def` ธรรมดา**

## ไฟล์ร่วม
| ไฟล์ | ทำอะไร |
|---|---|
| `conftest.py` | เพิ่ม root ของ repo ใน `sys.path` |
| `fakes.py` | `make_engine(**settings)` -> `(engine, FakeLine, CountingLLM, FakePlaces, Clock)`; `make_store()` (`STORE=postgres` สลับเป็น Postgres และ `reset()` ทุกเทสต์); `Clock` เดินเอง; `CountingLLM` นับการเรียก |
| `scripts/events.py` | ตัวสร้าง event LINE ปลอม ใช้ร่วมกับทุกชั้น |

## unit/ : ลอจิกย่อย เร็ว ไม่มี I/O
พิสูจน์: ฟังก์ชันตัดสินใจเล็กๆ ถูกต้อง · รันทุก PR
| ไฟล์ | โมดูลที่ครอบ |
|---|---|
| `test_prefilter.py` | `session/prefilter.py` |
| `test_merge.py` | `session/merge.py` |
| `test_ack.py` | `session/engine.all_acked` + confirmation rule |
| `test_extractor.py`, `test_lexicon_and_radius.py` | `adapters/llm.RuleExtractor`, `adapters/lexicon.py`, รัศมี |
| `test_geo.py` | `features/geo.py` |
| `test_round1_fixes.py` | regression ของบั๊กรอบ QA 1 (ดูไฟล์) |
| `test_webhook_handler.py` | `handlers/webhook.py` (signature, empty events, ขนาด, envelope, SQS) |
| `test_worker_handler.py` | `handlers/worker.py` (batch, partial failure, retry, DLQ จำลอง) |

## integration/ : หลายโมดูลต่อกัน
พิสูจน์: engine + fakes ทำงานตาม flow จริง · รันทุก PR
| ไฟล์ | ครอบ |
|---|---|
| `test_session_flow.py` | start -> prefs -> confirm -> plan, หลายคน |
| `test_caps.py` | เพดานงบ, kill switch, paid tier gate |
| `test_bugfixes.py` | regression ของบั๊กที่แก้แล้ว (+ `local_server.run_event`) |
| `test_webhook.py` | `process()` กับ event จริง |
| `test_aws.py` | `DynamoStore` + worker ผ่าน moto (ไม่ใช่ AWS จริง) |

## contract/ : พฤติกรรม Store ต้องเหมือนกัน
`test_store_contract.py` รัน **ชุดเดียว** กับ memory, Postgres, DynamoDB(moto) ถ้า Postgres ไม่ขึ้นจะ skip พร้อมข้อความ `run make pg-up first`
(ใน CI job Postgres ห้าม skip) พิสูจน์ว่าสลับ `STORE=` แล้วพฤติกรรมไม่เปลี่ยน รวม atomicity ภายใต้ thread (ยกเว้น moto)

## sandbox/ : บทสนทนาทั้งเรื่อง + determinism
- `scenarios/*.yaml` = เคสข้อมูล (`id`, `area`, `title`, `steps`: `say` / `tap` / `advance` / ... + `expect`) ตรงกับ [docs/TEST_SPEC.md](../docs/TEST_SPEC.md)
- `harness.py` สร้าง "โลก" ปลอมครบ: นาฬิกาแช่แข็ง (`1_800_000_000`), `ScriptedLLM` (ครอบ `GeminiExtractor` ด้วยสคริปต์ JSON), `SandboxPlaces`, uuid ที่ seed, `determinism()` (5 รอบ fresh + 5 รอบสลับ setup)
- `test_sandbox.py` ทำเป็น pytest; scenario ที่มี `bug: BUG-xx` = `xfail(strict=True)` (แก้แล้วจะ XPASS แล้วพัง -> ต้องลบ `bug:`)
- `run.py` = `make sandbox` พิมพ์ตารางและเขียน `reports/sandbox_report.md` (exit 1 เมื่อ FAIL / XPASS / determinism หลุด)
- **เพิ่มเคส**: เพิ่ม block ใน YAML ที่เหมาะสม + แถวใน TEST_SPEC.md (ดูหัวข้อ "วิธีเพิ่มเคส" ใน spec)

## eval/ : วัดความแม่น (ไม่ใช่ pass/fail ของโค้ด)
`utterances.jsonl` = ประโยคไทยที่ label แล้ว; รันด้วย `python -m scripts.eval_intents` (กฎ ฟรี) หรือ `--live` (Gemini เสียเงิน)
nightly ตรวจว่า intent accuracy >= 90% (ปรับได้ตอน manual run)

## Markers / skip / xfail ที่ใช้
| กลไก | ที่ไหน | ความหมาย |
|---|---|---|
| `skip` (Postgres ไม่ขึ้น) | contract | ต้องไม่เกิดใน CI job Postgres |
| `xfail(strict=True)` | sandbox `bug:` | บั๊กที่ track แล้ว ต้องลบเมื่อแก้ |
| `xfail(strict=False)` | `test_fallback_dedup_id_is_stable_across_processes` | ข้อบกพร่องที่รู้แล้ว ความเสี่ยงต่ำ (ดู handlers/README.md) |

## เขียนเทสต์ใหม่ให้ถูกที่
| ต้องการพิสูจน์ | วางที่ |
|---|---|
| ฟังก์ชันเดียว ไม่ต้องมี engine | `unit/` |
| ผู้ใช้พูดแล้วบอทตอบ/เงียบ/จำ state | scenario YAML ใน `sandbox/` (ได้ determinism ฟรี) หรือ `integration/` ถ้าต้อง assert ลึก |
| Store ใหม่/เปลี่ยนพฤติกรรม store | `contract/` |
| Lambda handler | `unit/` (ฉีด `_engine` / `_secret` / `_sqs` ด้วย `monkeypatch`) |
| ความแม่น LLM | `eval/utterances.jsonl` |
