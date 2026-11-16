# ไปไหนดีวะ (Pai-nhai-dee-wa)

บอท LINE ที่อยู่ในกลุ่มเหมือนเพื่อนอีกคน ช่วยกลุ่มตัดสินใจว่า **กินอะไร / ทำอะไร** ด้วยร้านจริงจาก Google Maps และระยะจริง

> **English summary.** A conversational LINE group bot. `@bot กินไรดีแถวอารีย์` starts a 60‑minute
> *session*: the bot announces it is listening (PDPA), reads group messages through a cheap
> pre‑filter + small LLM that extracts only preferences (never stores chat text), speaks only when
> @mentioned or when the group settles on a place, then collects ✅ from every participant and posts
> a plan card. Python 3.12, line-bot-sdk v3, Gemini, Places API (New), DynamoDB, SAM.
> Run `make install && make test && make simulate` — everything works offline with fakes, no keys.
> Local LINE testing via ngrok needs no AWS (`make local`). See `docs/ARCHITECTURE.md`.

## ทำงานยังไง (สั้นๆ)

1. มีคน `@ไปไหนดีวะ กินไรดีแถวอารีย์` → บอทบอกว่า "จะฟังแชตกลุ่มนี้ไม่เกิน 60 นาที" + ปุ่ม **[หยุดฟัง]** แล้วเสนอ 3 ร้าน
2. ระหว่างนั้นบอท **อ่านแต่ไม่พูด** จำว่าใครชอบ/ไม่เอา/เพิ่งกินอะไร (เก็บแค่สรุป ไม่เก็บข้อความ)
3. `@ไปไหนดีวะ แถวอารีย์มีบุฟเฟต์นานาชาติไหม` → บอทค้นจากทุกอย่างที่จำไว้
4. "โอเค ไปร้านนี้แหละ" → บอทส่งการ์ดยืนยัน รายชื่อทุกคนที่คุย + ปุ่ม **[ตกลง ✅] [ยังก่อน]**
5. ครบทุกคน → การ์ดแผน (ร้าน ระยะเส้นตรง ลิงก์แผนที่ เวลาถ้ามี) แล้วจบ session
6. โหวต: ใช้โพลของ LINE (`@บอท โหวตหน่อย` จะแนะนำวิธี) · ประกาศสรุป: `@บอท ประกาศหน่อย`

## เริ่มเร็วที่สุด (ไม่ต้องมี key อะไรเลย)

ต้องมี Python 3.12+ (macOS: `brew install python@3.12`)

```bash
cd pai-nhai-dee-wa
python3 -m venv .venv && source .venv/bin/activate
make install        # ติดตั้ง library
make test           # รันเทสต์ทั้งหมด (ใช้ของปลอม ไม่เสียเงิน)
make simulate       # เล่นบทสนทนา A/B/C แถวอารีย์ใน terminal
python -m scripts.simulate --interactive   # พิมพ์คุยเองเป็นหลายคน เช่น  A: @bot กินไรดีแถวสยาม
```

บทสนทนาอยู่ที่ `scripts/scenarios/ari_buffet.txt` แก้หรือเขียนไฟล์ใหม่แล้วรัน `python -m scripts.simulate --script ไฟล์.txt`

## ทดสอบกับ LINE จริง (ยังไม่ต้องใช้ AWS)

### 1) ตั้งค่า LINE OA
1. เข้า <https://developers.line.biz/console/> → สร้าง Provider → สร้าง channel แบบ **Messaging API** (แนะนำแยก dev กับ prod)
2. แท็บ **Basic settings** → คัดลอก **Channel secret**
3. แท็บ **Messaging API** → กด Issue **Channel access token (long-lived)**
4. ใน LINE Official Account Manager → Settings → **Account settings** → เปิด **"Allow bot to join group chats"**
5. Response settings: ปิด **Auto-reply** และ **Greeting message**, เปิด **Webhook**

### 2) รันบนเครื่อง + ngrok
```bash
cp .env.example .env      # ใส่ LINE_CHANNEL_SECRET และ LINE_CHANNEL_ACCESS_TOKEN
make local                # เซิร์ฟเวอร์ที่ http://localhost:8000/callback
ngrok http 8000           # อีกหน้าต่าง (ติดตั้ง: brew install ngrok)
```
เอา URL จาก ngrok ไปใส่ **Webhook URL** = `https://xxxx.ngrok-free.app/callback` → กด Verify → เปิด Use webhook
แล้วเชิญบอทเข้ากลุ่ม LINE ลองพิมพ์ `@ชื่อบอท กินไรดีแถวอารีย์`

ค่าเริ่มต้นใช้ LLM และ Places แบบ **ปลอม** (ร้านขึ้นต้นด้วย `[ตัวอย่าง]`) เพื่อเช็กว่า LINE ต่อติดก่อนโดยไม่เสียเงิน

### 3) ใช้ Google จริง (เสียเงินตามการใช้งาน)
1. Google Cloud Console → สร้าง project → เปิด **Billing**
2. APIs & Services → Enable **Places API (New)**
3. Credentials → Create **API key** → Restrict key ให้ใช้ได้แค่ Places API (New)
4. APIs & Services → Places API (New) → **Quotas** → ตั้งเพดานต่อวัน (เช่น Text Search 300 ครั้ง/วัน) กันบิลบาน
5. Gemini: <https://aistudio.google.com/> → สร้าง API key ใน project **ที่เปิด billing แล้ว (paid tier)**
6. ใน `.env`: `LLM_PROVIDER=gemini`, `PLACES_PROVIDER=google`, ใส่ key ทั้งสอง

> ⚠️ **ความเป็นส่วนตัว (PDPA):** Gemini แบบฟรีอาจเอาข้อความไปใช้พัฒนาโมเดล
> บอทจึง **ไม่อ่านแชตกลุ่ม** จนกว่าจะตั้ง `GEMINI_PAID_TIER_CONFIRMED=true` (ตั้งเฉพาะเมื่อ project เปิด billing แล้วจริงๆ)
> ถ้ายังไม่ตั้ง บอทจะทำงานแค่ตอนถูก @ และตอนกดปุ่ม (เซิร์ฟเวอร์จะเตือนตอนเริ่ม)

## คุมงบ 1,000 บาท/เดือน (ไม่รวมการตลาด)

| ตัวคุม | ค่าเริ่มต้น | ตั้งที่ |
|---|---|---|
| ปิดบอททั้งหมด (kill switch) | `BOT_ENABLED=true` | `.env` / SAM parameter |
| LLM ต่อ session | 40 ครั้ง (เกินแล้วใช้กฎฟรีแทน) | `MAX_LLM_CALLS_PER_SESSION` |
| ค้นหาต่อกลุ่มต่อวัน | 10 | `MAX_SEARCHES_PER_GROUP_PER_DAY` |
| เรียก Places รวมทุกกลุ่มต่อวัน | 300 | `MAX_PLACES_CALLS_PER_DAY` |
| แจ้งเตือนงบ AWS | USD 28 (~1,000 บาท) | `MonthlyBudgetUsd` ใน `template.yaml` |
| Push message | ไม่ใช้เลย ตอบด้วย reply อย่างเดียว | — |

ย่านยอดฮิต (อารีย์ สยาม สาทร ฯลฯ) มีพิกัดในโค้ด ไม่ต้องเสียค่า geocode

## Deploy ขึ้น AWS (ทีหลัง)

ต้องมี AWS CLI + SAM CLI และ login แล้ว (`aws configure`)
```bash
# เก็บ secret ใน SSM (ครั้งเดียว ต่อ stage)
aws ssm put-parameter --type SecureString --name /pai-nhai-dee-wa/dev/line-channel-secret --value '...'
aws ssm put-parameter --type SecureString --name /pai-nhai-dee-wa/dev/line-channel-access-token --value '...'
aws ssm put-parameter --type SecureString --name /pai-nhai-dee-wa/dev/gemini-api-key --value '...'
aws ssm put-parameter --type SecureString --name /pai-nhai-dee-wa/dev/google-places-api-key --value '...'
ALERT_EMAIL=you@example.com make deploy-dev
```
เอา `WebhookUrl` จาก output ไปใส่ใน LINE แทน ngrok · ต้องการให้อ่านแชต: `--parameter-overrides GeminiPaidTierConfirmed=true`
CI (`.github/workflows/ci.yml`) รันแค่ lint + test; deploy ทำมือเท่านั้น

## โครงสร้างโค้ด

| โฟลเดอร์ | หน้าที่ |
|---|---|
| `handlers/` | Lambda: `webhook.py` (ตรวจ signature, กรอง, ส่ง SQS) และ `worker.py` |
| `session/` | หัวใจ: `engine.py` (state machine), `prefilter.py`, `merge.py`, `models.py` |
| `features/` | `search.py` (ค้น + Haversine + จัดอันดับ), `cards.py` (ข้อความ/ปุ่ม), `geo.py`, food/activity |
| `adapters/` | `llm.py` (Gemini + กฎออฟไลน์), `places.py` (Places API New + ของปลอม), `line.py` |
| `store/` | `memory.py` (เครื่องตัวเอง), `dynamo.py` (AWS) |
| `scripts/` | `local_server.py`, `simulate.py`, scenarios |
| `tests/` | unit + integration (ใช้ของปลอมและ moto) |
