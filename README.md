# ไปไหนดีวะ (Pai-nhai-dee-wa)

บอท LINE ที่อยู่ในกลุ่มเหมือนเพื่อนอีกคน ช่วยกลุ่มตัดสินใจว่า **กินอะไร / ทำอะไร** ด้วยร้านจริงจาก Google Maps และระยะจริง
โดย **อ่านเฉพาะตอนเปิดโหมดช่วยคิด (session ไม่เกิน 60 นาที) และไม่เก็บข้อความแชตดิบ** (PDPA)

[![ci](https://github.com/Mickiepk/pai-nhai-dee-wa/actions/workflows/ci.yml/badge.svg)](https://github.com/Mickiepk/pai-nhai-dee-wa/actions/workflows/ci.yml)
[![regression](https://github.com/Mickiepk/pai-nhai-dee-wa/actions/workflows/regression.yml/badge.svg)](https://github.com/Mickiepk/pai-nhai-dee-wa/actions/workflows/regression.yml)

> **English summary.** A conversational LINE group-chat bot (Python 3.12, line-bot-sdk v3, Gemini for preference extraction,
> Google Places API (New), DynamoDB on AWS / Postgres locally, AWS SAM). `@bot กินไรดีแถวอารีย์` starts a 60-minute *session*:
> the bot announces it is listening, extracts preferences only (never stores chat text), speaks only when @mentioned or when
> the group settles on a place, then collects ✅ from every participant and posts a plan card.
> Everything runs offline with fakes: `make install && make ci && make simulate`, no API keys needed.

## สารบัญ
1. [บอททำงานยังไง](#บอททำงานยังไง)
2. [Architecture](#architecture)
3. [Quick start (local)](#quick-start-local)
4. [Environments: local vs AWS](#environments-local-vs-aws)
5. [Make targets](#make-targets)
6. [Config / environment variables](#config--environment-variables)
7. [Cost guards](#cost-guards-คุมงบ-1000-บาทเดือน)
8. [Testing overview](#testing-overview)
9. [CI/CD overview](#cicd-overview)
10. [Repo map](#repo-map)
11. [Troubleshooting](#troubleshooting)
12. [Contributing](#contributing-branching-commit)
13. [เอกสารทั้งหมด](#เอกสารทั้งหมด)

## บอททำงานยังไง

1. มีคน `@ไปไหนดีวะ กินไรดีแถวอารีย์` -> บอทบอกว่า "จะฟังแชตกลุ่มนี้ไม่เกิน 60 นาที" + ปุ่ม **[หยุดฟัง]** แล้วเสนอ 3 ร้าน
2. ระหว่างนั้นบอท **อ่านแต่ไม่พูด** จำว่าใครชอบ/ไม่เอา/เพิ่งกินอะไร (เก็บแค่สรุป ไม่เก็บข้อความ)
3. `@ไปไหนดีวะ แถวอารีย์มีบุฟเฟต์นานาชาติไหม` -> บอทค้นจากทุกอย่างที่จำไว้
4. "โอเค ไปร้านนี้แหละ" -> การ์ดยืนยัน รายชื่อทุกคนที่คุย + ปุ่ม **[ตกลง ✅] [ยังก่อน]**
5. ครบทุกคน -> การ์ดแผน (ร้าน ระยะเส้นตรง ลิงก์แผนที่ เวลาถ้ามี) แล้วจบ session
6. โหวต: ใช้โพลของ LINE (`@บอท โหวตหน่อย` จะแนะนำวิธี) · ประกาศสรุป: `@บอท ประกาศหน่อย`

กฎหลักที่ห้ามหลุด: บอทพูดเฉพาะตอนถูก @, ตอนตรวจพบการตัดสินใจ, หรือตอนกดปุ่ม · ไม่มี session = ไม่อ่านแชต ·
ไม่เก็บ/ไม่ log ข้อความดิบ · LLM สกัดสัญญาณเท่านั้น การตัดสินใจทั้งหมดอยู่ในโค้ด (รายละเอียด: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))

## Architecture

```mermaid
flowchart LR
    LINE[LINE Platform] -->|webhook POST + x-line-signature| WH
    subgraph AWS["AWS (prod / dev)"]
        WH["WebhookFunction<br/>handlers/webhook.py<br/>verify signature, prefilter"]
        Q[("SQS FIFO<br/>MessageGroupId = groupId<br/>dedup = webhookEventId")]
        DLQ[("DLQ<br/>after 3 receives")]
        WK["WorkerFunction<br/>handlers/worker.py<br/>batchItemFailures"]
        DDB[("DynamoDB<br/>sessions / dedup / quotas<br/>TTL")]
        SSM[("SSM SecureString<br/>secrets")]
        WH --> Q --> WK
        Q -. maxReceiveCount=3 .-> DLQ
        WK --> DDB
        WH -. cold start .-> SSM
        WK -. cold start .-> SSM
    end
    subgraph CORE["Business core (identical locally and on AWS)"]
        ENG["SessionEngine<br/>session/engine.py"]
        FEAT["features/<br/>search, cards, geo"]
        ADP["adapters/<br/>LLM, Places, LINE"]
        ST["store/<br/>memory, postgres, dynamo"]
        ENG --> FEAT
        ENG --> ADP
        ENG --> ST
    end
    WK --> ENG
    ADP -->|extract| GEM[Gemini]
    ADP -->|search| GP[Google Places API]
    ADP -->|reply token| LINE
    LOCAL["scripts/local_server.py<br/>or make simulate"] --> ENG
    ST -.-> DDB
    ST -.-> PG[("Postgres 16<br/>local / CI")]
```

- Lambda 2 ตัว: **webhook** (ตรวจ signature, กรองข้อความขยะ, ส่ง SQS แล้วตอบ 200 ทันที) และ **worker** (รัน `SessionEngine`)
- ตอบกลับด้วย **reply token** ของ event นั้นเท่านั้น (ไม่ใช้ push message)
- Local ใช้ engine ตัวเดียวกัน ต่างกันที่ตัวรับ event และ Store (ดู [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md))
- State machine ต่อกลุ่ม: `LISTENING <-> CONFIRMING -> จบ` (diagram ใน [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md))

## Quick start (local)

ต้องมี Python 3.12+ (macOS: `brew install python@3.12`) · ไม่ต้องมี key ใดๆ

### A) Memory store (เร็วสุด ไม่ต้องมี Docker)
```bash
python3 -m venv .venv && source .venv/bin/activate
make install        # ติดตั้ง library
make ci             # ruff + เทสต์ + coverage + sandbox + lint template (ของปลอมทั้งหมด ไม่เสียเงิน)
make simulate       # เล่นบทสนทนา A/B/C แถวอารีย์ใน terminal
python -m scripts.simulate --interactive   # พิมพ์คุยเองเป็นหลายคน เช่น  A: @bot กินไรดีแถวสยาม
```
บทสนทนาอยู่ที่ `scripts/scenarios/ari_buffet.txt` แก้หรือเขียนไฟล์ใหม่แล้วรัน `python -m scripts.simulate --script ไฟล์.txt`

### B) Postgres store (เหมือน AWS มากขึ้น เก็บถาวรในเครื่อง)
```bash
docker compose up -d      # postgres:16 พอร์ต 54329   (หรือ make pg-up ถ้าไม่มี Docker)
make test-pg              # เทสต์ทั้งชุด + store contract บน Postgres
make simulate-pg          # เล่นบทสนทนาบน Postgres
STORE=postgres make local # เซิร์ฟเวอร์ LINE จริงผ่าน ngrok + Postgres
make pg-down              # หยุด   (make pg-reset = ล้างข้อมูลทั้งหมด)
```
URL เริ่มต้น `postgresql://pnd:pnd@localhost:54329/pnd` ตารางสร้างเองอัตโนมัติ (`store/schema.sql`)

### C) ทดสอบกับ LINE จริง (ยังไม่ต้องใช้ AWS)
1. <https://developers.line.biz/console/> -> Provider -> channel แบบ **Messaging API** (แยก dev/prod)
2. **Basic settings** คัดลอก **Channel secret** · **Messaging API** กด Issue **Channel access token (long-lived)**
3. LINE Official Account Manager -> Settings -> Account settings -> เปิด **Allow bot to join group chats**
4. Response settings: ปิด **Auto-reply** และ **Greeting message**, เปิด **Webhook**
5. ```bash
   cp .env.example .env      # ใส่ LINE_CHANNEL_SECRET และ LINE_CHANNEL_ACCESS_TOKEN
   make local                # http://localhost:8000/callback
   ngrok http 8000           # อีกหน้าต่าง
   ```
6. เอา URL จาก ngrok ไปใส่ **Webhook URL** = `https://xxxx.ngrok-free.app/callback` -> Verify -> เปิด Use webhook -> เชิญบอทเข้ากลุ่ม

ค่าเริ่มต้นใช้ LLM และ Places แบบ **ปลอม** (ร้านขึ้นต้นด้วย `[ตัวอย่าง]`) เพื่อเช็กว่า LINE ต่อติดก่อนโดยไม่เสียเงิน

### D) ใช้ Google จริง (เสียเงินตามการใช้งาน)
1. Google Cloud Console -> สร้าง project -> เปิด **Billing** -> Enable **Places API (New)** -> สร้าง API key แล้ว restrict เฉพาะ Places API (New)
2. ตั้ง **Quotas** ของ Places ต่อวัน (เช่น Text Search 300 ครั้ง/วัน) กันบิลบาน
3. Gemini: <https://aistudio.google.com/> สร้าง key ใน project **ที่เปิด billing แล้ว (paid tier)**
4. `.env`: `LLM_PROVIDER=gemini`, `PLACES_PROVIDER=google`, ใส่ key ทั้งสอง

> **PDPA:** Gemini แบบฟรีอาจเอาข้อความไปพัฒนาโมเดล บอทจึง **ไม่อ่านแชตกลุ่ม** จนกว่าจะตั้ง `GEMINI_PAID_TIER_CONFIRMED=true`
> (ตั้งเฉพาะเมื่อ project เปิด billing แล้วจริงๆ) ถ้าไม่ตั้ง บอททำงานแค่ตอนถูก @ และตอนกดปุ่ม (เซิร์ฟเวอร์เตือนตอนเริ่ม)

## Environments: local vs AWS

| | LOCAL | AWS (dev / prod) |
|---|---|---|
| ตัวรับ event | `scripts/local_server.py` + ngrok, หรือ `make simulate` | Lambda Function URL -> SQS FIFO -> Lambda worker |
| Store | `STORE=memory` หรือ `postgres` | `dynamo` (DynamoDB, TTL attribute `ttl`) |
| Secret | `.env` | SSM Parameter Store (SecureString) |
| ค่าใช้จ่าย | 0 บาท (ถ้าใช้ของปลอม) | ตาม usage คุมด้วย budget ใน `template.yaml` |
| Deploy | - | `make deploy-dev` (มือ) หรือ `deploy.yml` (ยังไม่เคยรัน) |

รายละเอียดและตารางว่า "อะไรพิสูจน์ได้ที่ไหน": [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) · ขั้นตอน deploy ทีละบล็อก: [docs/DEPLOY.md](docs/DEPLOY.md) ·
**ยังไม่เคย deploy จริง** (ไม่มี AWS credentials) ดู [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md)

## Make targets

| Target | ทำอะไร | ต้องมี |
|---|---|---|
| `make install` | ติดตั้ง `requirements-dev.txt` | pip |
| `make test` | `pytest -q` ทั้งชุด (ตาม `STORE`, ค่าเริ่มต้น memory) | - |
| `make cov` | เหมือน `test` + coverage, fail ถ้าต่ำกว่า `fail_under` (85), เขียน `coverage.xml` | - |
| `make lint` | `ruff check .` | - |
| `make sandbox` | scenario ทั้งหมด + determinism (5 รอบ) เขียน `reports/sandbox_report.md` | - |
| `make template-lint` | `sam validate --lint` + `cfn-lint` (ข้ามพร้อมข้อความถ้าไม่ได้ติดตั้ง) | sam, cfn-lint |
| `make ci` | **เหมือน PR pipeline**: `lint cov sandbox template-lint` บน memory store | - |
| `make ci-full` | `ci` + `test-pg` | Postgres |
| `make lint-actions` | `actionlint` ตรวจ `.github/workflows` | `pip install actionlint-py` |
| `make simulate` | เล่นบทสนทนาจำลองใน terminal | - |
| `make local` | เซิร์ฟเวอร์ LINE ในเครื่อง (`/callback` พอร์ต 8000) | `.env`, ngrok |
| `make pg-up` / `pg-down` / `pg-reset` | เริ่ม/หยุด/ล้าง Postgres ในเครื่อง (`scripts/local_pg.sh`) | Postgres หรือ Docker |
| `make test-pg` | เทสต์ทั้งชุด + contract บน Postgres | `pg-up` |
| `make simulate-pg` | simulate บน Postgres | `pg-up` |
| `make deploy-dev` | `sam build && sam deploy --config-env dev` (มือ ถามก่อนเปลี่ยน) | AWS credentials, `ALERT_EMAIL` |

## Config / environment variables

อ่านใน `config.py` (`load_settings()`) · ตัวอย่างไฟล์: `.env.example` · `Settings` ใช้ pydantic validate ค่า (ค่านอกช่วงจะ error ตอนเริ่ม)
"Secret" = ห้าม commit/ห้าม log; บน AWS มาจาก SSM ไม่ใช่ environment ตรงๆ

| ตัวแปร | Field ใน `Settings` | Default | Required? | Secret? | ความหมาย |
|---|---|---|---|---|---|
| `LINE_CHANNEL_SECRET` | `line_channel_secret` | `""` | ถ้า `LINE_PROVIDER=real` | **ใช่** | ใช้ตรวจ `x-line-signature` |
| `LINE_CHANNEL_ACCESS_TOKEN` | `line_channel_access_token` | `""` | ถ้า `LINE_PROVIDER=real` | **ใช่** | ใช้เรียก LINE reply API |
| `GEMINI_API_KEY` | `gemini_api_key` | `""` | ถ้า `LLM_PROVIDER=gemini` | **ใช่** | key ของ Gemini (ต้องเป็น project ที่เปิด billing) |
| `GOOGLE_PLACES_API_KEY` | `google_places_api_key` | `""` | ถ้า `PLACES_PROVIDER=google` | **ใช่** | key ของ Places API (New) |
| `LLM_PROVIDER` | `llm_provider` | `fake` | ไม่ | ไม่ | `fake` (กฎออฟไลน์) หรือ `gemini` |
| `PLACES_PROVIDER` | `places_provider` | `fake` | ไม่ | ไม่ | `fake` หรือ `google` |
| `LINE_PROVIDER` | `line_provider` | `fake` | ไม่ | ไม่ | `fake` (เก็บ reply ในหน่วยความจำ) หรือ `real`; `make local` บังคับเป็น `real` |
| `STORE` (หรือ `STORE_PROVIDER`) | `store_provider` | `memory` | ไม่ | ไม่ | `memory` / `postgres` / `dynamo`; `STORE` ชนะ `STORE_PROVIDER`; AWS template ตั้ง `STORE_PROVIDER=dynamo` |
| `DATABASE_URL` | `database_url` | `postgresql://pnd:pnd@localhost:54329/pnd` | ถ้า `STORE=postgres` นอกเครื่อง dev | **ใช่** ถ้าชี้ฐานข้อมูลจริง | DSN ของ Postgres |
| `TABLE_NAME` | `table_name` | `pai-nhai-dee-wa-dev` | ถ้า `STORE=dynamo` | ไม่ | ชื่อตาราง DynamoDB (template ตั้งให้ตาม Stage) |
| `GEMINI_MODEL` | `gemini_model` | `gemini-2.5-flash-lite` | ไม่ | ไม่ | รุ่นโมเดลที่ใช้สกัดสัญญาณ |
| `GEMINI_PAID_TIER_CONFIRMED` | `gemini_paid_tier_confirmed` | `false` | **ต้องเป็น `true` ก่อนให้ Gemini อ่านแชต** | ไม่ | ยืนยันว่าเป็น paid tier (PDPA) ถ้าไม่ true บอทตอบแค่ @ และปุ่ม; ถ้า `LLM_PROVIDER=fake` ถือว่าอ่านได้เพราะไม่มีอะไรออกจากเครื่อง |
| `BOT_ENABLED` | `bot_enabled` | `true` | ไม่ | ไม่ | kill switch: `false` = เงียบทั้งหมด (event ถูก ack ทิ้ง ไม่ retry) |
| `SESSION_MINUTES` | `session_minutes` | `60` (ช่วง 5-120) | ไม่ | ไม่ | อายุ session |
| `MAX_LLM_CALLS_PER_SESSION` | `max_llm_calls_per_session` | `40` | ไม่ | ไม่ | เกินแล้วใช้กฎฟรี |
| `MAX_SEARCHES_PER_GROUP_PER_DAY` | `max_searches_per_group_per_day` | `10` | ไม่ | ไม่ | โควตาค้นต่อกลุ่มต่อวัน (เวลาไทย) |
| `MAX_PLACES_CALLS_PER_DAY` | `max_places_calls_per_day` | `300` | ไม่ | ไม่ | โควตา Places รวมทุกกลุ่มต่อวัน (นับ geocode ด้วย) |
| (ไม่มี env) | `default_radius_km` | `3.0` | - | - | ค่าตายตัวใน `Settings`; รัศมีจริงต่อชนิดงานอยู่ที่ `features/food.py` (3 กม.) และ `features/activity.py` (5 กม.) |

ตัวแปรเฉพาะ AWS / เครื่องมือ (ไม่อยู่ใน `config.py`):

| ตัวแปร | ใช้ที่ | ความหมาย |
|---|---|---|
| `QUEUE_URL` | `handlers/webhook.py` | URL ของ SQS FIFO (template ตั้งให้; ไม่มี = `KeyError`) |
| `LINE_CHANNEL_SECRET_PARAM`, `LINE_CHANNEL_ACCESS_TOKEN_PARAM`, `GEMINI_API_KEY_PARAM`, `GOOGLE_PLACES_API_KEY_PARAM` | `handlers/ssm.py` | **ชื่อ** SSM parameter (ไม่ใช่ค่า secret) ที่ Lambda จะอ่านตอน cold start; webhook อ่านได้แค่ตัวแรก, worker อ่านอีกสามตัว |
| `STAGE` | template | `dev` / `prod` |
| `PND_PG_PORT`, `PND_PG_DIR`, `PG_BIN` | `scripts/local_pg.sh` | พอร์ต (54329), โฟลเดอร์ข้อมูล (`/tmp/pnd-pg`), path ของ binary Postgres |
| `PYTHONHASHSEED` | `regression.yml` | สลับ seed เพื่อจับบั๊กที่ขึ้นกับลำดับ set/dict |

SAM parameters (`template.yaml`): `Stage`, `AlertEmail` (บังคับ), `MonthlyBudgetUsd` (28), `LlmProvider`, `PlacesProvider`, `GeminiPaidTierConfirmed`, `BotEnabled`, `MaxPlacesCallsPerDay`, `WebhookReservedConcurrency` (10), `WorkerReservedConcurrency` (5)

## Cost guards (คุมงบ 1,000 บาท/เดือน)

| ตัวคุม | ค่าเริ่มต้น | ตั้งที่ | ทำงานที่ |
|---|---|---|---|
| Kill switch ปิดบอททั้งหมด | `BOT_ENABLED=true` | `.env` / SAM `BotEnabled` | `SessionEngine.handle` |
| LLM ต่อ session | 40 ครั้ง แล้วใช้กฎฟรีแทน | `MAX_LLM_CALLS_PER_SESSION` | `SessionEngine._extract` |
| ค้นหาต่อกลุ่มต่อวัน | 10 | `MAX_SEARCHES_PER_GROUP_PER_DAY` | `SessionEngine._search_replies` |
| Places รวมทุกกลุ่มต่อวัน | 300 (นับทุกครั้งที่เรียก รวม geocode) | `MAX_PLACES_CALLS_PER_DAY` | `SessionEngine._search_replies` (`spend`) |
| ต้อง paid tier ก่อนอ่านแชต | `false` | `GEMINI_PAID_TIER_CONFIRMED` | `Settings.chat_reading_enabled` |
| Concurrency Lambda | webhook 10 / worker 5 | SAM parameters | `template.yaml` (บัญชีใหม่ที่โควตา < 120 ใช้ `-1` ดู DEPLOY.md) |
| แจ้งเตือนงบ AWS | USD 28 (~1,000 บาท) | `MonthlyBudgetUsd` | `template.yaml` (แจ้งเตือนอย่างเดียว ไม่ตัดบริการ) |
| Push message | ไม่ใช้เลย | - | ตอบด้วย reply token เท่านั้น |
| ย่านยอดฮิต | มีพิกัดในโค้ด ไม่เสีย geocode | `features/geo.AREA_CENTERS` | `features/search.py` |

เทสต์ที่พิสูจน์ตัวคุมเหล่านี้: `tests/integration/test_caps.py` และ scenario SBX-39..43 ใน `tests/sandbox/`

## Testing overview

| ชั้น | อยู่ที่ | พิสูจน์อะไร | รันเมื่อ |
|---|---|---|---|
| Unit | `tests/unit/` | ลอจิกย่อย: prefilter, merge, extractor rules, geo, ack, webhook/worker handler | ทุก PR |
| Integration | `tests/integration/` | engine ทั้งก้อนกับของปลอม, caps, bugfix regression, DynamoDB ผ่าน moto | ทุก PR |
| Contract | `tests/contract/` | Store ทั้ง 3 ตัวประพฤติเหมือนกัน | ทุก PR (Postgres job) |
| Sandbox | `tests/sandbox/` + `make sandbox` | บทสนทนาทั้งเรื่อง 60+ เคส + determinism ทุก byte | ทุก PR + nightly (5 hash seed) |
| Intent eval | `scripts/eval_intents.py` | ความแม่นของการอ่านภาษาไทย วัดเป็น % | nightly / ก่อน release |
| Smoke | `scripts/smoke.py` | หลัง deploy: Function URL ตอบ 200/401 ถูก | หลัง deploy เท่านั้น |

กลยุทธ์ครบ (pyramid, coverage, flaky policy, definition of done, release gate): [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) ·
นโยบายความหมายของ "deterministic" และระดับความรุนแรง P0-P3: [docs/TEST_POLICY.md](docs/TEST_POLICY.md) ·
คอร์สเทสทีละ Level: [docs/TESTING.md](docs/TESTING.md) · ตาราง 72 เคส: [docs/TEST_SPEC.md](docs/TEST_SPEC.md) · อธิบายโค้ดเทสต์: [tests/README.md](tests/README.md)

## CI/CD overview

| Workflow | Trigger | ทำอะไร |
|---|---|---|
| `.github/workflows/ci.yml` | PR + push main | ruff · unit+integration (memory) · contract + full suite บน Postgres 16 + coverage artifact · `make sandbox` · `sam validate --lint` + `cfn-lint` + `sam build` (cache) · actionlint · job รวม `ci ok` สำหรับ branch protection |
| `.github/workflows/regression.yml` | nightly 02:00 (เวลาไทย) + manual | full suite x Postgres · sandbox x 5 hash seeds · intent eval (ขั้นต่ำ 90%) · อัปโหลด report · เปิด/อัปเดต issue `nightly-regression` เมื่อพัง |
| `.github/workflows/deploy.yml` | manual เท่านั้น | **ปิดไว้/ยังไม่เคยทดสอบ** (ยังไม่มี AWS): environment gate -> OIDC (`AWS_ROLE_ARN`) -> `sam build/deploy` -> `scripts.smoke` |
| `.github/dependabot.yml` | รายสัปดาห์ | อัปเดต GitHub Actions + pip |

ตั้ง branch protection ของ `main` ให้ require check **`ci ok`** · ทุกอย่างบน GitHub Actions **ยังไม่เคยรันจริงบน GitHub** (ตรวจด้วย actionlint + YAML เท่านั้น)

## Repo map

```
.
├── config.py            Settings + load_settings() + load_dotenv()
├── wiring.py            build_engine(): จุดเดียวที่เลือก real vs fake provider
├── handlers/            Lambda entry points (webhook, worker, ssm)          -> handlers/README.md
├── session/             SessionEngine (state machine), prefilter, merge     -> session/README.md
├── features/            search/rank, cards (LINE Flex), geo                  -> features/README.md
├── adapters/            LLM (Gemini + rules), Places, LINE gateway, lexicon  -> adapters/README.md
├── store/               memory / postgres / dynamo + schema.sql              -> store/README.md
├── scripts/             simulate, local_server, smoke, eval_intents, local_pg -> scripts/README.md
├── tests/               unit, integration, contract, sandbox, eval          -> tests/README.md
├── docs/                ARCHITECTURE, ENVIRONMENTS, DEPLOY, TEST_*, modules/INDEX.md
├── reports/             sandbox_report.md (สร้างโดย make sandbox), QA reports
├── template.yaml        AWS SAM (Lambda x2, SQS FIFO + DLQ, DynamoDB, alarms, budget)
├── samconfig.toml       ค่า deploy ต่อ stage (dev/prod)
├── docker-compose.yml   Postgres 16 สำหรับ local/CI
└── .github/             workflows, dependabot, CODEOWNERS, PR template
```

## Troubleshooting

| อาการ | สาเหตุที่พบบ่อย | วิธีแก้ |
|---|---|---|
| `make test-pg` skip เทสต์ Postgres พร้อมข้อความ `run make pg-up first` | Postgres ไม่ขึ้น | `make pg-up` (หรือ `docker compose up -d`) แล้วเช็ก `DATABASE_URL` |
| `make pg-up` บอกหา binary ไม่เจอ | ไม่ได้ติดตั้ง Postgres | macOS: `brew install postgresql@16` หรือใช้ `docker compose up -d` |
| บอทไม่ตอบในกลุ่ม (local) | webhook URL ผิด/ngrok เปลี่ยน URL, ยังไม่เปิด "Allow bot to join group chats", Auto-reply เปิดอยู่ | ตั้ง Webhook URL ใหม่แล้วกด Verify; ดู log ของ `make local` |
| บอทตอบแค่ตอน @ ไม่อ่านแชต | `GEMINI_PAID_TIER_CONFIRMED` ไม่ใช่ `true` (ออกแบบไว้ตาม PDPA) | ตั้งหลังเปิด billing ของ Gemini แล้วเท่านั้น หรือใช้ `LLM_PROVIDER=fake` ตอนทดสอบ |
| บอทเงียบทั้งหมด | `BOT_ENABLED=false` | ตั้งเป็น `true` |
| เซิร์ฟเวอร์เตือน `... missing` ตอนเริ่ม | ตั้ง provider จริงแต่ไม่ใส่ key | ใส่ key ใน `.env` หรือกลับไป `fake` |
| 401 จาก webhook | Channel secret ไม่ตรง / body ถูกแก้ก่อนตรวจ signature | เช็ก secret ของ channel ที่ถูกตัว (dev vs prod) |
| ขึ้น "วันนี้ค้นครบ N ครั้งแล้ว" | ชนโควตา `MAX_SEARCHES_PER_GROUP_PER_DAY` | รอวันถัดไป (เวลาไทย) หรือปรับค่า |
| `make sandbox` ออก 1 พร้อม `XPASS` | บั๊กที่ track ไว้ถูกแก้แล้ว | ลบ `bug:` ออกจาก scenario นั้น (ดู docs/TEST_POLICY.md ข้อ 6) |
| `make sandbox` ออก 1 พร้อม `determinism` | โค้ดขึ้นกับลำดับ set/dict/เวลา/uuid | ดู diff ใน `reports/sandbox_report.md` ตัดสินด้วย key คงที่ (เช่น `place_id`) |
| `make ci` ข้าม template lint | ไม่ได้ติดตั้ง `sam` / `cfn-lint` | `brew install aws-sam-cli` และ `pip install cfn-lint` |
| coverage ต่ำกว่า 85% | เพิ่มโค้ดโดยไม่มีเทสต์ | เพิ่มเทสต์ (ดู docs/TEST_STRATEGY.md) อย่าลดค่า `fail_under` เพื่อให้เขียว |
| `sam build` พังบน Mac | Python ไม่ใช่ 3.12 | `brew install python@3.12` ดู docs/DEPLOY.md หัวข้อแก้ปัญหา |
| Lambda: ตั้ง reserved concurrency ไม่ได้ | บัญชี AWS ใหม่โควตารวมต่ำ | ใช้ `WebhookReservedConcurrency=-1 WorkerReservedConcurrency=-1` (docs/DEPLOY.md ข้อ 1.7) |

## Contributing (branching, commit)

- **Branch**: แตกจาก `main` ชื่อ `type/short-description` เช่น `feat/radius-meters`, `fix/dedup-hash`, `docs/test-strategy`, `ci/nightly` · ห้าม push ตรงเข้า `main` เมื่อเปิด branch protection · PR เล็กและทำเรื่องเดียว
- **Commit**: [Conventional Commits](https://www.conventionalcommits.org/) `type(scope): summary` (ภาษาอังกฤษ ไม่เกิน ~72 ตัวอักษร) type = `feat | fix | test | docs | ci | refactor | chore | perf`
  scope เช่น `session`, `adapters`, `store`, `handlers`, `sandbox`, `deploy` · body อธิบาย "ทำไม" ไม่ใช่ "ทำอะไร"
- **ก่อนเปิด PR**: `make ci` ต้องเขียว (ถ้าแตะ store ให้ `make ci-full`) · ใช้ [PR template](.github/PULL_REQUEST_TEMPLATE.md)
- **ทุกบั๊กต้องมีเทส**: เพิ่ม scenario ใน `tests/sandbox/scenarios/` หรือ unit test ก่อนแก้ (ดู docs/TEST_POLICY.md ข้อ 6)
- **ห้าม**: commit `.env` / key จริง, log หรือเก็บข้อความแชตดิบ, ลดเพดานงบ/ปิด guard โดยไม่อธิบายใน PR, แก้ expectation ของเทสต์ให้ตรงกับพฤติกรรมที่ผิดเพื่อให้เขียว
- **Review**: `CODEOWNERS` กำหนดเจ้าของ; ไฟล์ `template.yaml`, `config.py`, `.github/` ต้องผ่านเจ้าของ repo
- **เพิ่ม provider/store ใหม่**: ดู "How to extend" ใน [adapters/README.md](adapters/README.md) และ [store/README.md](store/README.md)

## เอกสารทั้งหมด

| เอกสาร | เรื่อง |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | flow, state machine, stored state, failure modes |
| [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md) | local (Postgres) vs AWS, อะไรพิสูจน์ที่ไหน |
| [docs/DEPLOY.md](docs/DEPLOY.md) | runbook deploy ขึ้น AWS |
| [docs/LAUNCH_CHECKLIST.md](docs/LAUNCH_CHECKLIST.md) | Gate 0 go/no-go, PDPA |
| [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) | pyramid, ชุดเทสต์ต่อ PR/nightly/release, coverage, flaky, DoD |
| [docs/TEST_POLICY.md](docs/TEST_POLICY.md) | deterministic, กติกา sandbox, ระดับ P0-P3, gates |
| [docs/TEST_SPEC.md](docs/TEST_SPEC.md) | ตารางเคสทดสอบ sandbox |
| [docs/TESTING.md](docs/TESTING.md) | คอร์สเทส Level 0-5 สำหรับมือใหม่ |
| [docs/BACKLOG.md](docs/BACKLOG.md) | งานที่ค้าง (เจ้าของคือทีมอื่น; ถ้ายังไม่มีไฟล์ แปลว่ากำลังสร้าง) |
| [docs/modules/INDEX.md](docs/modules/INDEX.md) | สารบัญเอกสารโมดูลทุกตัว |
| [reports/QA_REPORT_round1.md](reports/QA_REPORT_round1.md) | รายงาน QA รอบ 1 |
