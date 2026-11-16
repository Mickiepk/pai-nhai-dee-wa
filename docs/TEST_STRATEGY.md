# กลยุทธ์การทดสอบ "ไปไหนดีวะ" (Test Strategy) · v1 · 2026-11-16

เอกสารนี้ตอบว่า **ทดสอบอะไร ที่ชั้นไหน เมื่อไร และอะไรคือ "เสร็จ"** ส่วนนิยามคำว่า deterministic, กติกา sandbox, ระดับความรุนแรง P0-P3 และ Gate 0/1
อยู่ใน [docs/TEST_POLICY.md](TEST_POLICY.md) (ไม่ซ้ำที่นี่) · ตารางเคส: [TEST_SPEC.md](TEST_SPEC.md) · คอร์สลงมือ: [TESTING.md](TESTING.md) · โค้ดเทสต์: [tests/README.md](../tests/README.md)

## 1. หลักคิด 4 ข้อ
1. **ทุกอย่างที่ตัดสินใจเป็นโค้ด เทสต์ด้วย `assert` ได้เป๊ะ** LLM ทำหน้าที่สกัดสัญญาณเท่านั้น ความแม่นของ LLM วัดเป็น % แยกต่างหาก (eval) ไม่ใช่ pass/fail
2. **CI ไม่แตะเครือข่ายและไม่ใช้ key จริง** ใช้ของปลอมที่ deterministic ทั้งหมด (ไม่เสียเงิน ไม่ flaky เพราะ API)
3. **การ "ไม่พูด" เป็นผลลัพธ์ที่ต้องเทสต์** บอทที่พูดเองโดยไม่ถูกเรียกคือ P1
4. **สิ่งที่พิสูจน์ได้เฉพาะบน AWS ต้องบอกตรงๆ ว่ายังไม่พิสูจน์** (ดู 7) ห้ามเขียนว่า "เทสต์แล้ว" ถ้าเทสต์ด้วย moto หรือ fake เท่านั้น

## 2. Test pyramid ของโปรเจกต์นี้

```
            /\        Smoke (หลัง deploy, ~3 requests)                 scripts/smoke.py
           /  \       Intent eval (วัดความแม่น %, nightly)               scripts/eval_intents.py
          /----\      Sandbox scenarios (บทสนทนาเต็มเรื่อง 60+ เคส)      tests/sandbox/
         /------\     Contract (Store x3 behave the same)               tests/contract/
        /--------\    Integration (engine + fakes, moto, caps)          tests/integration/
       /----------\   Unit (prefilter, merge, rules, geo, handlers)     tests/unit/
```

| ชั้น | อยู่ที่ | พิสูจน์อะไร | ไม่พิสูจน์อะไร | ความเร็ว (ประมาณ) |
|---|---|---|---|---|
| **Unit** | `tests/unit/` | ฟังก์ชัน/กฎเล็กๆ ถูกต้อง รวม handler ของ Lambda (`webhook`, `worker`) ด้วย fake SQS/engine: signature fail-closed, partial batch failure, retry/forget_event, poison -> DLQ (จำลอง) | การเชื่อมต่อกันของหลายโมดูล | วินาที |
| **Integration** | `tests/integration/` | `SessionEngine` + FakeLine/FakePlaces/Store ทำงานตาม flow, เพดานงบ, kill switch, paid-tier gate, regression ของบั๊ก, `DynamoStore` ผ่าน moto | IAM, เครือข่ายจริง, ขีดจำกัดของ AWS | วินาที |
| **Contract** | `tests/contract/` | memory, Postgres, DynamoDB(moto) ประพฤติเหมือนกัน: dedup, forget, session, counter, TTL (ฉีด `now`), atomicity ภายใต้ thread | DynamoDB จริง (TTL ลบเบื้องหลัง, throttling) | ~10 วินาที (Postgres) |
| **Sandbox scenarios** | `tests/sandbox/`, `make sandbox` | พฤติกรรมของผลิตภัณฑ์ตามสเปกทั้งบทสนทนา และ **determinism ทุก byte** (5 รอบ fresh + 5 รอบสลับ setup + uuid ไม่ seed) | ภาษาจริงของผู้ใช้, LLM จริง | ~10 วินาที |
| **Intent eval** | `tests/eval/utterances.jsonl` + `scripts/eval_intents.py` | % ที่ rules/Gemini สกัด intent/ย่าน/ชอบ/ไม่เอา ถูก | ว่าโค้ดถูก (นั่นคือหน้าที่ของชั้นล่าง) | วินาที (rules); `--live` เสียเงิน |
| **Smoke** | `scripts/smoke.py` | หลัง deploy: Function URL ตอบ 200 (signature ถูก) และ 401 (ผิด/ไม่มี) ผ่านเครือข่ายจริง | ลอจิก product (ไม่ส่ง event จริง ไม่เรียก LINE/Gemini/Places) | วินาที |
| **Manual (Level 4)** | LINE จริง + ngrok | ปุ่ม/การ์ดแสดงผลถูกบนมือถือ, reply token จริง | - | ก่อน Gate 1 เท่านั้น ([TESTING.md](TESTING.md)) |

### เมื่อบั๊กถูกพบ ให้ใส่ที่ชั้นต่ำสุดที่จับได้
บั๊กของฟังก์ชันเดียว -> unit · บั๊กในบทสนทนา -> scenario YAML (ได้ determinism ฟรี) · บั๊กของ Store -> contract · ทุกบั๊กต้องมีเทสต์ก่อนแก้ ([TEST_POLICY.md](TEST_POLICY.md) ข้อ 6)

## 3. อะไรรันเมื่อไร

| ชุด | ทุก PR / push `main` (`ci.yml`) | Nightly (`regression.yml`) | Pre-release (ก่อน deploy / Gate) |
|---|:-:|:-:|:-:|
| `ruff check .` | x | | x |
| Unit + integration บน `STORE=memory` | x | | x |
| Contract + ทั้งชุดบน Postgres 16 + coverage gate (>= 85%) | x | x | x |
| `make sandbox` (determinism x5) | x | x (x5 `PYTHONHASHSEED`) | x |
| `sam validate --lint`, `cfn-lint`, `sam build` | x | | x |
| `actionlint` (workflow ถูกต้อง) | x | | |
| Intent eval (rules) เกณฑ์ >= 90% | | x | x |
| Intent eval `--live` (Gemini จริง, เสียเงิน) | | | x (มือ, ก่อนเปลี่ยน prompt/โมเดล) |
| เช็กมือกับ LINE จริง (Level 4) | | | x (Gate 1) |
| Smoke บน stack ที่ deploy | | | x (หลัง `deploy.yml`/`make deploy-dev` ทุกครั้ง) |
| ตรวจ DLQ ว่าง, alarm ปกติ, budget | | | x ([LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)) |

เหตุผลของ nightly: หลาย hash seed จับบั๊กที่ขึ้นกับลำดับ set/dict ซึ่ง PR รอบเดียวอาจรอดได้, และตรวจว่าของที่ไม่ได้แตะโค้ดไม่เน่า (เช่น dependency ใหม่, Postgres image ใหม่)
ถ้า nightly พัง workflow เปิด/อัปเดต issue ชื่อ `Nightly regression failing` (label `nightly-regression`) -> ถือเป็น blocker ของ PR ถัดไปที่แตะโค้ดส่วนนั้น

## 4. Coverage
- เครื่องมือ: `pytest-cov`; ขอบเขตวัด = โค้ด production (`handlers session features adapters store wiring config`) ไม่รวม `scripts/` และ `tests/` (ตั้งใน `pyproject.toml`)
- **เกณฑ์ปัจจุบัน `fail_under = 85`** วัดได้จริง 2026-11-16: ~94% เมื่อรันบน Postgres (ทั้งชุด), ~90% บน memory อย่างเดียว (เกณฑ์ = ค่าที่วัดได้ลบประมาณ 5-9 จุด เพื่อให้ PR ปกติผ่านแต่การเพิ่มโค้ดก้อนใหญ่ที่ไม่มีเทสต์จะไม่ผ่าน)
- gate บังคับในงาน Postgres ของ CI (ที่ทุกอย่างรันครบ) และใน `make cov` / `make ci`
- **ห้ามลดเกณฑ์เพื่อให้เขียว** ถ้าต่ำกว่าให้เพิ่มเทสต์; ปรับ **ขึ้น** ได้เมื่อค่าวัดได้เพิ่มถาวร (ปรับทีละน้อย ให้เหลือส่วนต่าง 3-5 จุด)
- ช่องว่างที่รู้แล้ว (ยอมรับชั่วคราว): `adapters/line.py` `RealLine`, `adapters/places.py` `GooglePlaces`, `GeminiExtractor` ต้องใช้ key จริง; `handlers/ssm.py` ส่วนเรียก boto3 จริง; `scripts/` ไม่นับ
- coverage ไม่ได้แปลว่าถูก: scenario ใน sandbox มี assertion ของ product (ข้อความ, state, จำนวนการเรียก) ซึ่งสำคัญกว่าตัวเลข

## 5. Flaky-test policy
เทสต์ทุกตัวต้อง deterministic (นิยามใน [TEST_POLICY.md](TEST_POLICY.md) ข้อ 1) ดังนั้น **flaky = บั๊กของเทสต์หรือของโค้ด ไม่ใช่ "โชคร้าย"**
1. **ห้าม retry อัตโนมัติ** (`pytest-rerunfailures`, `--reruns`, `retry` ใน workflow) เพราะซ่อน non-determinism ที่ sandbox ตั้งใจจับ
2. พบเทสต์ที่ผลไม่คงที่: เปิด issue label `flaky` ภายในวันเดียวกัน ระบุคำสั่งที่ทำซ้ำได้ (`PYTHONHASHSEED`, seed, ลำดับการรัน)
3. ภายใน 2 วันทำการ ต้อง **แก้** หรือ **quarantine**: ใส่ `@pytest.mark.xfail(strict=False, reason="FLAKY #<issue>: ...")` พร้อมเลข issue (ห้าม `skip` เงียบ, ห้ามลบเทสต์) เพื่อให้เห็นใน output
4. quarantine ค้างได้ไม่เกิน 14 วัน แล้วต้องแก้หรือเปลี่ยนเป็นเทสต์ที่แน่นอนกว่า; ผู้เปิด issue เป็นเจ้าของจนกว่าจะส่งต่อ
5. สาเหตุที่พบบ่อยในโปรเจกต์นี้ และวิธีแก้ที่ถูก: เวลา (ใช้ `Clock`/`SandboxClock` ห้าม `time.time()`), uuid (ฉีด/seed), ลำดับ set/dict (เรียงด้วย key คงที่ เช่น `place_id`), thread race (ใช้ lock/atomic ใน store), port ชน (Postgres 54329), ลำดับ import ของ global state ใน handler (reset ด้วย `monkeypatch`)
6. เทสต์ Postgres ที่ถูก **skip** ใน CI ถือว่าเป็นความล้มเหลว (workflow ตรวจให้)
7. `xfail(strict=True)` ของ sandbox `bug:` ไม่ใช่ flaky: เป็นบั๊กที่ track อยู่ เมื่อ XPASS ต้องลบ `bug:` ใน PR เดียวกับการแก้

## 6. วิธีเพิ่มเทสต์
1. เลือกชั้นให้ต่ำสุดที่พิสูจน์ได้ (ตาราง "เขียนเทสต์ใหม่ให้ถูกที่" ใน [tests/README.md](../tests/README.md))
2. ใช้ `tests/fakes.make_engine()` และ `scripts/events.py`; ห้ามเรียกเครือข่าย/นาฬิกาจริง/สุ่มที่ไม่ seed
3. ตั้งชื่อ `test_<พฤติกรรม>_<เงื่อนไข>` ให้อ่านแล้วรู้ว่าสเปกคืออะไร; หนึ่งเทสต์ = หนึ่งพฤติกรรม
4. Lambda handler: ฟังก์ชัน `def` ธรรมดา (ไม่ใช่ `async def`) เพราะ worker ใช้ `asyncio.run`; ฉีด `handlers.worker._engine`, `handlers.webhook._secret/_sqs` ด้วย `monkeypatch.setattr` และคืนค่าเดิมหลังเทสต์
5. Scenario ใหม่: เพิ่มใน `tests/sandbox/scenarios/*.yaml` + แถวใน [TEST_SPEC.md](TEST_SPEC.md); บั๊กที่ยังไม่แก้ใส่ `bug: BUG-xx`
6. Store ใหม่/เปลี่ยนพฤติกรรม: เพิ่มเคสใน `tests/contract/test_store_contract.py` (รันกับทุก store)
7. รัน `pytest <ไฟล์> -q` ก่อน แล้ว `make ci` (และ `make test-pg` ถ้าแตะ store)
8. ถ้าเทสต์ต้องการพฤติกรรมที่ยังไม่ถูกต้อง ให้เขียนตามสเปกที่ถูก แล้วใส่ `xfail(strict=True, reason="BUG-xx")` อย่าเขียนให้ตรงกับพฤติกรรมที่ผิด

## 7. สิ่งที่ยังพิสูจน์ไม่ได้ (ต้องรอ AWS / key จริง)
อ้างอิงตารางเต็มใน [ENVIRONMENTS.md](ENVIRONMENTS.md) · สรุป: IAM ของ Lambda, SQS redrive/DLQ/visibility timeout จริง, Function URL + signature ผ่านเครือข่าย, cold start/timeout/memory, DynamoDB TTL ลบจริง,
ค่าใช้จ่ายจริง/budget alarm, พฤติกรรม Gemini/Places/LINE จริง และ **GitHub Actions ทั้งสามไฟล์ยังไม่เคยรันบน GitHub** (ตรวจด้วย actionlint + YAML เท่านั้น)
งานที่ครอบด้วยเทสต์ปัจจุบันเป็นการ **จำลอง** (เช่น `redrive()` ใน `test_worker_handler.py` จำลอง maxReceiveCount=3) ไม่ใช่ AWS จริง
ไม่มี EventBridge/scheduled/cleanup Lambda ในระบบ (ลบข้อมูลด้วย DynamoDB TTL) จึงไม่มีเทสต์ของงานตามเวลา; ถ้าเพิ่มต้องเขียนเทสต์ตาม "How to extend" ใน [handlers/README.md](../handlers/README.md)

## 8. Definition of Done (ต่อ PR)
- [ ] `make ci` เขียว (ruff, เทสต์ + coverage >= เกณฑ์, sandbox, template lint); แตะ store: `make ci-full`
- [ ] พฤติกรรมใหม่มีเทสต์; บั๊กที่แก้มี regression test; `bug:` ของ scenario ที่แก้แล้วถูกลบ
- [ ] ไม่มีเทสต์ที่ถูก skip/xfail ใหม่โดยไม่มีเหตุผลและเลข issue/BUG
- [ ] ไม่เก็บ/ไม่ log ข้อความแชตดิบ (มี assert หรือ scenario SBX-44 ยังเขียว); ไม่มี secret ใน diff
- [ ] เพดานงบ/kill switch/paid-tier gate ไม่ถูกลดโดยไม่อธิบาย
- [ ] README ของโมดูลที่แตะและ `docs/` ที่เกี่ยวข้องอัปเดตแล้ว; ตาราง env ใน README อัปเดตถ้าแก้ `config.py`
- [ ] CI บน GitHub เขียวทั้ง job `ci ok` และมีผู้รีวิวตาม `CODEOWNERS`

## 9. Release gate (ก่อน deploy ขึ้น AWS / ก่อนเชิญกลุ่มจริง)
ใช้ Gate 0 / Gate 1 ใน [TEST_POLICY.md](TEST_POLICY.md) ข้อ 5 เป็นเกณฑ์หลัก และเพิ่มข้อกำหนดเชิงเครื่องมือดังนี้
1. `ci.yml` เขียวบน commit ที่จะ release และ **nightly ล่าสุดเขียว** (ไม่มี issue `nightly-regression` เปิดค้าง)
2. P0 = 0, P1 = 0; P2 ทุกตัวมีเจ้าของและกำหนดแก้; ไม่มี `XPASS`/`FAIL` ที่ไม่มีบั๊กผูก ([QA report](../reports/QA_REPORT_round1.md) เป็นตัวอย่างรูปแบบ)
3. determinism 100% (รวมผลรัน 5 hash seed ของ nightly)
4. Intent eval (rules) ไม่ต่ำกว่าเกณฑ์ และถ้าเปลี่ยน prompt/โมเดล รัน `--live` เทียบก่อน-หลัง
5. `sam validate --lint` + `cfn-lint` ผ่าน, `sam build` ผ่าน, ตรวจ Parameter ที่ตั้ง (`GeminiPaidTierConfirmed`, `BotEnabled`, concurrency) ตรงตาม [DEPLOY.md](DEPLOY.md)
6. Deploy `dev` ก่อน -> `scripts/smoke.py` ผ่าน -> Gate 0 checklist ([LAUNCH_CHECKLIST.md](LAUNCH_CHECKLIST.md)) -> ค่อย `prod` (environment `prod` ต้องมี required reviewer)
7. หลัง deploy: DLQ ว่าง, ไม่มี alarm, budget alarm ตั้งแล้ว, มีวิธี rollback/kill switch (`BOT_ENABLED=false`) ที่ลองแล้ว
8. Gate 1 (เพื่อนจริง): เช็กมือกับ LINE จริง Level 4 ผ่าน และผู้ตัดสินเป็นเจ้าของ product

## 10. เมตริกที่ติดตาม (ขอให้ดูทุกสัปดาห์)
จำนวนเคส sandbox ที่ PASS / known bug / unexpected · coverage · เวลา `ci` · จำนวนเทสต์ xfail/quarantine (ควรลดลง) · nightly สำเร็จกี่ % ใน 14 วัน · intent accuracy ของ rules
