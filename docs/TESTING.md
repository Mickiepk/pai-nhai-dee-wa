# คอร์สเทสบอท "ไปไหนดีวะ" สำหรับมือใหม่

เขียนโดย QA สำหรับ Mickie (macOS) · ทุกคำสั่งในไฟล์นี้ QA รันจริงแล้ว ผลลัพธ์ที่แปะไว้คือของจริงจากรอบที่รัน (2026-11-16)

ไล่ตามลำดับ Level 0 → 5 ห้ามข้าม เพราะแต่ละขั้นแพงขึ้น (ฟรี → ไม่กี่บาท → ต้องใช้เพื่อนจริง)

| Level | ทำอะไร | เสียเงิน? | เวลา |
|---|---|---|---|
| 0 | เข้าใจว่าทำไมเทสแชตบอทไม่เหมือนเทสเว็บ | ฟรี | 5 นาที |
| 1 | `make test` เทสอัตโนมัติ | ฟรี | 10 นาที |
| 2 | Simulator ของปลอม (ไม่ต้องมี key) | ฟรี | 30 นาที |
| 3 | Simulator + Gemini/Places จริง | ~1-5 บาท/รอบ | 30 นาที |
| 4 | LINE จริงผ่าน ngrok + กลุ่มทดสอบ | ~ไม่กี่บาท | 1-2 ชม. |
| 5 | AI eval (วัดความแม่นของการอ่านภาษาไทย) | ฟรี (rules) / ~1 บาท (Gemini) | 20 นาที |

ก่อนเริ่ม (ครั้งเดียว):

```bash
cd pai-nhai-dee-wa
python3 -m venv .venv && source .venv/bin/activate   # ทุกครั้งที่เปิด terminal ใหม่ต้อง source อีกรอบ
make install
```

---

## Level 0: ทำไมเทสแชตบอทถึงไม่เหมือนเทส API

- **LLM ไม่ deterministic** ประโยคเดียวกัน Gemini อาจตอบไม่เหมือนกันทุกรอบ จึงแยกเป็น 2 ชั้น: โค้ด/กฎ (เทสด้วย `assert` ได้เป๊ะ) กับ AI (วัดเป็น % ด้วย eval set ใน Level 5) ห้ามเขียน unit test ที่ต้องเรียก Gemini จริง
- **แชตกลุ่มมีขยะเยอะ** "555", สติกเกอร์, "โอเค", ลิงก์ ฯลฯ บอทต้องเงียบ และต้องไม่เสียเงินเรียก LLM กับข้อความพวกนี้ (`session/prefilter.py`) การ "ไม่พูด" ก็เป็นผลลัพธ์ที่ต้องเทส
- **มี state** คำตอบขึ้นกับสิ่งที่คุยมาก่อน (ใครเพิ่งกินอะไร, อยู่สถานะ LISTENING หรือ CONFIRMING, หมดเวลา 60 นาทีหรือยัง) เทสทีละประโยคไม่พอ ต้องเทสเป็น "บทสนทนา"
- **หลายคนพร้อมกัน** ทุกคนในกลุ่มต้องกด ✅ คนที่ไม่ได้พูดไม่ถูกนับ ต้องลองเล่นเป็นหลายคนเสมอ
- **reply token ใช้ได้ครั้งเดียวและหมดอายุเร็ว** บอทตอบได้เฉพาะตอนมี event เข้ามา (pilot ไม่ใช้ push) LINE ส่ง event ซ้ำได้ จึงต้องเทสว่า event ซ้ำทำงานครั้งเดียว

---

## Level 1: เทสอัตโนมัติ (`make test`)

**เป้าหมาย:** รู้ว่าโค้ดพังหรือไม่ภายใน 2 วินาที รันทุกครั้งก่อน commit

### คำสั่ง

```bash
make test                                              # ทั้งหมด
python -m pytest -v                                    # แสดงชื่อเทสทีละตัว
python -m pytest tests/unit/test_ack.py                # ไฟล์เดียว
python -m pytest tests/unit/test_ack.py::test_all_acked -v   # เทสเดียว
python -m pytest -k dedup                              # เทสที่ชื่อมีคำว่า dedup
python -m pytest -x                                    # หยุดที่ตัวแรกที่พัง
make lint                                              # ตรวจ style (ruff)
```

### ควรเห็น

```
python3 -m pytest -q
...........................................................              [100%]
59 passed in 0.72s
```

```
tests/unit/test_ack.py::test_all_acked PASSED                            [100%]
============================== 1 passed in 0.10s ===============================
```

### ผ่าน / ไม่ผ่าน

- ผ่าน = บรรทัดสุดท้ายเป็น `N passed` ไม่มีคำว่า `failed` หรือ `error`
- จุดแต่ละจุด `.` = 1 เทสผ่าน, `F` = assert ไม่ผ่าน, `E` = เทสรันไม่ได้เลย (มักเป็น import/setup)
- ตัวอย่างตอนพัง (QA เขียนเทสทดลองให้ดูว่าพิมพ์ "อารีย" ไม่มีการันต์):

```
>       assert d.area == "อารีย์"
E       AssertionError: assert None == 'อารีย์'
E        +  where None = MessageDelta(intent='food', request='search', area=None, ...).area

/tmp/qa_demo/test_demo.py:4: AssertionError
FAILED ../../../tmp/qa_demo/test_demo.py::test_typo_area - AssertionError: as...
1 failed in 0.07s
```

อ่านแบบนี้: บรรทัด `>` = บรรทัดที่พัง, `E` = ค่าที่ได้ (`None`) เทียบกับที่อยากได้ (`'อารีย์'`), บรรทัด `file:4` = เปิดไฟล์ที่บรรทัดนั้น

### ไฟล์เทสหลักครอบคลุมอะไร

| ไฟล์ | ครอบคลุม |
|---|---|
| `tests/unit/test_extractor.py` | กฎออฟไลน์อ่านภาษาไทย: intent, ชอบ/ไม่เอา/เพิ่งกิน, "ร้านที่ 2", งบ, เวลา, ประกาศ/โหวต/หยุด |
| `tests/unit/test_prefilter.py` | ข้อความขยะ ("555", "ok", สติกเกอร์, รูป) ถูกทิ้ง ข้อความจริงถูกอ่าน |
| `tests/unit/test_merge.py` | รวมความชอบของแต่ละคน, เพิ่งกินแล้วต้องเลี่ยง, งบใช้ค่าต่ำสุด |
| `tests/unit/test_geo.py` | ระยะ Haversine (สยาม→อารีย์ ~4 กม.), format ระยะ, ลิงก์แผนที่ |
| `tests/unit/test_ack.py` | การ์ดแผนออกเมื่อทุกคนกด ✅ เท่านั้น, ยังก่อน, การ์ดเก่าถูกเมิน |
| `tests/integration/test_session_flow.py` | บทสนทนา A/B/C อารีย์ครบวงจร, หยุดฟัง, หมดเวลา, ถามย่าน, event ซ้ำ, ไม่เก็บข้อความแชต |
| `tests/integration/test_caps.py` | เพดานงบ: LLM ต่อ session, ค้นต่อกลุ่มต่อวัน, Places ต่อวัน, kill switch, Gemini ไม่ใช่ paid tier = ไม่อ่านแชต |
| `tests/integration/test_webhook.py` | signature ผิด = 401, กรอง event ก่อนเข้าคิว |
| `tests/integration/test_aws.py` | DynamoDB (จำลองด้วย moto): dedup, TTL, counter, worker |

### Error ที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| `ModuleNotFoundError: No module named 'httpx'` (QA เจอจริงตอนรันครั้งแรก) | ยังไม่ได้ `source .venv/bin/activate` หรือยังไม่ `make install` |
| `5 errors during collection` | สาเหตุเดียวกับข้างบน: import ไม่ได้ |
| `python3: command not found` / เวอร์ชันต่ำกว่า 3.12 | `brew install python@3.12` แล้วสร้าง venv ใหม่ด้วย `python3.12 -m venv .venv` |
| เทส AWS พังเพราะ credentials | ไม่ต้องมี AWS จริง เทสใช้ moto ถ้าเครื่องตั้ง `AWS_PROFILE` แปลกๆ ไว้ ลอง `unset AWS_PROFILE` |

---

## Level 2: Simulator แบบไม่มี key (ฟรี)

**เป้าหมาย:** เล่นเป็นเพื่อนหลายคนในกลุ่มใน terminal ดูว่าบอทพูด/เงียบถูกจังหวะไหม ร้านปลอมจะขึ้นต้นด้วย `[ตัวอย่าง]` และ **มีแค่แถวอารีย์** (แถวอื่นจะได้ "ไม่เจอ" ซึ่งถูกต้องสำหรับของปลอม)

### 2.1 รันบท A/B/C อารีย์

```bash
make simulate
```

ควรเห็น (ตัดมาบางส่วน):

```
--- simulator (llm=fake, places=fake) ---

เอ (A): @bot กินไรดีแถวอารีย์
  🤖 👂 เปิดโหมดช่วยคิดละ
     เราจะอ่านแชตกลุ่มนี้ไม่เกิน 60 นาที เพื่อจำว่าใครอยากกินอะไร ไม่เก็บข้อความ เก็บแค่สรุปความชอบ
     [หยุดฟัง]
  🤖 ได้ 3 ที่ละ ทุกที่ไม่เกิน 3 กม. จากอารีย์
  ...
เอ (A): ไม่เอาอันนี้ อยากกินญี่ปุ่น

บี (B): เพิ่งกินญี่ปุ่นมา เอาเกาหลีได้ไหม

บี (B): 555
...
ซี (C): @bot แถวอารีย์มีบุฟเฟต์นานาชาติไหม
  🤖 ได้ 1 ที่ละ ทุกที่ไม่เกิน 3 กม. จากอารีย์
     (ข้ามญี่ปุ่นให้ละ มีคนไม่เอาหรือเพิ่งกิน)
  🤖 1. [ตัวอย่าง] เวิลด์บุฟเฟต์ พหลโยธิน
     ~510 ม. จากอารีย์
...
เอ (A): โอเค ไปร้านนี้แหละ
  🤖 สรุปว่าไปที่นี่นะ?
     [ตัวอย่าง] เวิลด์บุฟเฟต์ พหลโยธิน
     ~510 ม. จากอารีย์
     รอทุกคนกดตกลง: เอ, บี, ซี
     [ตกลง ✅] [ยังก่อน]

* (*): [ตกลง]
  🤖 ✅ 1/3 คนตกลงแล้ว
  🤖 ✅ 2/3 คนตกลงแล้ว
  🤖 🎉 จบ! ได้ที่ไปละ
...
--- session: ended ---
```

**ผ่านเมื่อ:** บรรทัดที่ไม่มี `@bot` ไม่มี 🤖 ตามหลัง (บอทเงียบ), ร้านซูชิ/ญี่ปุ่นหายไปหลัง B บอกว่าเพิ่งกิน, การ์ดยืนยันมีชื่อครบ 3 คน, บรรทัดสุดท้ายเป็น `session: ended`

### 2.2 โหมดพิมพ์เอง (หลายคน)

```bash
python -m scripts.simulate --interactive
```

กติกาการพิมพ์ (หนึ่งบรรทัด = หนึ่งข้อความ):

| พิมพ์ | ความหมาย |
|---|---|
| `A: สวัสดี` | ผู้ใช้ A (เอ) พิมพ์ในกลุ่ม ใช้ได้ `A B C D` หรือชื่ออื่นก็ได้ |
| `A: @bot กินไรดีแถวสยาม` | A แท็กบอท (ต้องขึ้นต้นด้วย `@bot` เป๊ะๆ) |
| `B: [ตกลง]` / `B: [ยังก่อน]` / `A: [หยุดฟัง]` | กดปุ่ม |
| `A: [เอาร้านนี้ 2]` | กดปุ่ม "เอาร้านนี้" ใต้ร้านที่ 2 |
| `*: [ตกลง]` | ทุกคนที่คุยกดตกลงพร้อมกัน |
| `Ctrl-D` | ออก (แสดงสถานะ session สุดท้าย) |

เขียนบทเป็นไฟล์แล้วรันซ้ำได้: `python -m scripts.simulate --script scripts/scenarios/ari_buffet.txt`
เคล็ดลับ: ยิงบทเร็วๆ ด้วย `printf "A: @bot กินไรดีแถวอารีย์\nB: 555\n" | python -m scripts.simulate --interactive`

### 2.3 บทสนทนา 10 บทที่ต้องลองเอง

"ผลจริง" คือสิ่งที่ QA ได้ตอนรันกับกฎออฟไลน์ ถ้าเห็นต่างจากนี้แปลว่ามีอะไรเปลี่ยน

| # | พิมพ์ (ทีละบรรทัด) | บอทที่ถูกต้อง | ผลจริงตอน QA รัน |
|---|---|---|---|
| 1 | `A: วันนี้เหนื่อยมาก` → `A: @bot กินไรดีวะ` | บรรทัดแรกเงียบ (ไม่มี session = ไม่อ่าน) บรรทัดสองเปิด session + ถาม "จะไปแถวไหนกันอะ?" พร้อมปุ่มย่าน | ✅ ตามนั้น |
| 2 (คุยเล่น) | `A: @bot กินไรดีแถวอารีย์` → `B: 555` → `C: 👍` → `B: เมื่อวานดูบอลมันส์มาก` | เงียบทั้ง 3 บรรทัดหลัง ไม่เปลี่ยนร้าน | ✅ เงียบ |
| 3 (สแลง) | `A: @bot หิวแล้ว แถวสยาม` → `B: หมูกระทะป่ะ 2 ทุ่ม` → `B: @bot ประกาศหน่อย` | ประกาศสรุปมี "หมูกระทะ" และเวลา 20:00 | ของปลอมไม่มีร้านแถวสยาม ตอบ "ใน 3 กม. จากสยาม ไม่เจอ..." (ถูกต้องสำหรับ fake) |
| 4 (พิมพ์ผิด) | `A: @bot กินไรดีแถวอารีย` (ไม่มีการันต์) → `A: @bot แถวอารีย์ หมูกะทะ` | ควรเข้าใจว่าอารีย์/หมูกระทะ | ❌ กฎออฟไลน์ไม่เข้าใจทั้งคู่ (ถามย่าน, แล้วให้ร้านทั่วไป) ดู Known issues #4 ต้องเช็กกับ Gemini ใน Level 3 |
| 5 (เปลี่ยนใจ) | `A: @bot กินไรดีแถวอารีย์` → `A: อยากกินญี่ปุ่น` → `A: ไม่เอาญี่ปุ่นแล้ว เกาหลีดีกว่า` → `A: @bot มีไรแนะนำ` | ผลสุดท้ายไม่มีร้านญี่ปุ่น มีปิ้งย่างโซล (เกาหลี) | ✅ "ได้ 1 ที่ละ ... (ข้ามญี่ปุ่นให้ละ...)" → ปิ้งย่างโซล ~150 ม. |
| 6 (ยังก่อน) | เปิดแถวอารีย์ → `B: เอาร้านที่ 2` → `C: [ยังก่อน]` → `A: ไปร้านที่ 3` → `*: [ตกลง]` | การ์ดยืนยันร้านที่ 2 → ยังก่อนกลับไปคุยต่อ → การ์ดร้านที่ 3 → แผน | ✅ ได้แผนปิ้งย่างโซล แต่ C ที่ไม่เคยพิมพ์กดยังก่อนได้ และไม่ถูกนับเป็นผู้ร่วม (Known issues #3) |
| 7 (หยุดฟัง) | เปิด session → `A: [หยุดฟัง]` → `B: ไปกินชาบูกัน` | "โอเค หยุดฟังละ" แล้วบรรทัดหลังเงียบ, `session: ended` | ✅ |
| 8 (หยุดด้วยคำพูด) | เปิด session → `B: @bot พอแล้ว` | "โอเค หยุดฟังละ เรียกใหม่ได้ตลอดนะ" | ✅ |
| 9 (ประกาศ + โหวต) | เปิดแถวอารีย์ → `B: เกาหลีดีกว่า` → `A: @bot ประกาศหน่อย` → `A: @bot โหวตหน่อย` | ประกาศ: ย่านอารีย์, บี ชอบเกาหลี / โหวต: แนะนำใช้โพลของ LINE | ✅ |
| 10 (กิจกรรม + ระยะ) | `A: @bot ไปไหนดีแถวสยาม โบว์ลิ่ง` → `B: @bot ไกลไป เอาแถวอโศกไม่เกิน 5 กม.` | ร้านใหม่ต้องอยู่ใน 5 กม. จากอโศก ระยะที่โชว์ต้อง ≤ 5.0 | ✅ "~5.0 กม. จากอโศก" (จริง 4.99 กม.) แต่ "ไกลไป" ไม่ได้ลดรัศมี (Known issues #5) |

ลองเพิ่มเอง: `A: @bot กินไรดีแถวบางนา` ก่อน QA แก้จะได้ "ได้ 0 ที่ละ" + การ์ดว่าง ตอนนี้ต้องได้ "หาพิกัดบางนาไม่เจอ ลองเลือกย่านใกล้ๆ ดูนะ" + ปุ่มย่าน

### Error ที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| พิมพ์ `@bot` แล้วบอทไม่ตอบ | ต้องขึ้นต้นบรรทัดด้วย `@bot` (ตัวเล็ก) และมี `A:` นำหน้า |
| `(unknown button [ตกลง ✅])` | ใส่แค่ `[ตกลง]` ไม่ต้องใส่ emoji |
| กดปุ่มแล้วได้ "อันนี้หมดเวลาแล้ว" | session จบไปแล้ว (เช่นแผนออกแล้ว) ถูกต้อง |
| พิมพ์ภาษาอังกฤษแล้วได้ข้อความช่วยเหลือ | กฎออฟไลน์อ่านแค่ภาษาไทย ใช้ Level 3 |

---

## Level 3: Simulator + API จริง (`--live`)

**เป้าหมาย:** ดูว่า Gemini อ่านสแลง/พิมพ์ผิด/อังกฤษได้ไหม และร้านจริงจาก Google อยู่ในรัศมีจริงไหม โดยยังไม่ต้องยุ่งกับ LINE

### 3.1 ตั้งเพดานเงินก่อน (ทำก่อนสร้าง key)

1. <https://console.cloud.google.com/> → สร้าง project ใหม่ เช่น `pai-nhai-dee-wa-dev` → เปิด **Billing**
2. Billing → **Budgets & alerts** → Create budget 300 บาท/เดือน (แจ้งที่ 50%, 90%, 100%) *หมายเหตุ: budget แค่แจ้งเตือน ไม่ตัดบริการ เพดานจริงคือ quota ข้อ 3.3*
3. APIs & Services → Enable **Places API (New)** และ **Generative Language API**

### 3.2 Gemini key (ต้องเป็น paid tier)

1. <https://aistudio.google.com/> → Get API key → เลือก project ที่เปิด billing แล้ว
2. **ทำไมต้อง paid tier:** Gemini แบบฟรีอาจเอา prompt ไปใช้ปรับปรุงโมเดล แต่บอทเราส่งข้อความแชตของเพื่อนเข้า Gemini นี่คือข้อมูลส่วนบุคคลของคนที่ไม่ได้ยินยอมกับ Google ตาม PDPA เราจึงต้องใช้ paid tier ซึ่งไม่เอาไปเทรน โค้ดบังคับเรื่องนี้ไว้: ถ้า `GEMINI_PAID_TIER_CONFIRMED` ไม่ใช่ `true` บอทจะ **ไม่อ่านข้อความที่ไม่ได้แท็ก** (`config.py` `chat_reading_enabled`)
3. ตั้ง `GEMINI_PAID_TIER_CONFIRMED=true` เฉพาะเมื่อ project เปิด billing จริงแล้ว

### 3.3 Places key + quota cap (กันบิลบาน)

1. APIs & Services → Credentials → Create API key → **Restrict key** → API restrictions: เลือกแค่ Places API (New)
2. APIs & Services → Places API (New) → **Quotas & system limits** → แก้ `SearchTextRequest per day` เป็น **30** ช่วง dev (เกินแล้ว Google ตอบ error บอทจะตอบ "ตอนนี้ค้นร้านไม่ได้" แทนการเก็บเงินต่อ)
3. ในโค้ดก็มีเพดานซ้อนอีกชั้น: `MAX_SEARCHES_PER_GROUP_PER_DAY=10`, `MAX_PLACES_CALLS_PER_DAY=300` (ช่วงเทสลดเหลือ 30 ได้ใน `.env`)

### 3.4 ใส่ key แล้วรัน

```bash
cp .env.example .env    # ถ้ายังไม่มี
# แก้ .env: GEMINI_API_KEY=..., GOOGLE_PLACES_API_KEY=..., GEMINI_PAID_TIER_CONFIRMED=true
set -a; . ./.env; set +a          # สำคัญ! simulator ไม่โหลด .env เอง
python -m scripts.simulate --live
python -m scripts.simulate --live --interactive
```

ควรเห็นบรรทัดแรก `--- simulator (llm=gemini, places=google) ---` และชื่อร้าน **ไม่มี** `[ตัวอย่าง]`

**ผ่านเมื่อ:** ร้านมีจริง (กด/คัดลอกลิงก์แผนที่ไปเปิดดู), ระยะที่โชว์ใกล้เคียงกับ Google Maps (ระยะเส้นตรง ไม่ใช่ระยะขับ ต่างได้), ไม่มีร้านเกินรัศมีที่ header บอก, ข้อ 4 (พิมพ์ผิด) ใน Level 2 ตอนนี้ต้องเข้าใจ
**ไม่ผ่านเมื่อ:** ร้านปิดถาวร/ไม่มีจริง, ระยะเกินรัศมี, บอทพูดเองโดยไม่ถูกแท็ก

### 3.5 ประมาณค่าใช้จ่ายต่อรอบ (ราคาเดือน พ.ย. 2026 ควรเช็กหน้า pricing อีกครั้ง)

| ส่วน | ต่อครั้ง | บท A/B/C 1 รอบ |
|---|---|---|
| Gemini 2.5 Flash-Lite (~500 token เข้า + ~100 ออก) | ~0.003 บาท | ~6 ครั้ง ≈ 0.02 บาท |
| Places Text Search (New) ที่ขอ rating/priceLevel = SKU Enterprise ~USD 35/1,000 | ~1.2 บาท (มีโควตาฟรีรายเดือนของ SKU นี้ก่อน) | 2 ครั้ง ≈ 2.5 บาท |
| **รวม** | | **~3 บาท/รอบ** (ถ้ายังอยู่ในโควตาฟรีของ Places ≈ 0 บาท) |

สรุป: ค่าใช้จ่ายเกือบทั้งหมดคือ Places ไม่ใช่ LLM ถ้า quota 30 ครั้ง/วัน เดือนหนึ่งแย่สุด ~900 ครั้ง ≈ 1,000 บาท ช่วง dev ลดเหลือ 10/วันก็พอ ดูยอดจริงที่ Billing → Reports ทุกสัปดาห์

### Error ที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| ยังขึ้น `llm=gemini` แต่ร้านยัง `[ตัวอย่าง]`/พฤติกรรมเหมือนกฎ | ไม่ได้ `set -a; . ./.env; set +a` key ว่าง → Gemini error → ใช้กฎแทนเงียบๆ |
| `403 PERMISSION_DENIED` / `API_KEY_INVALID` | key ถูก restrict ไม่ตรง API หรือยังไม่ enable Places API (New) |
| `429 RESOURCE_EXHAUSTED` | ชน quota ที่ตั้งไว้ (ดีแล้ว) รอพรุ่งนี้หรือเพิ่ม quota |
| ข้อความที่ไม่ได้แท็กถูกเมินหมด | ลืมตั้ง `GEMINI_PAID_TIER_CONFIRMED=true` |
| `llm_call failed (TimeoutError)` | Gemini ช้าเกิน 4 วิ บอทใช้กฎแทน ไม่ใช่บั๊ก ถ้าบ่อยให้แจ้ง dev |

---

## Level 4: LINE จริงผ่าน ngrok

**เป้าหมาย:** ทดสอบกับแอป LINE จริงในกลุ่มที่มี 2-3 บัญชี

### 4.1 สร้าง LINE OA + Messaging API channel

1. <https://developers.line.biz/console/> → login → **Create a new provider** (เช่น "ไปไหนดีวะ dev")
2. Create channel → **Messaging API** → กรอกชื่อ (เช่น "ไปไหนดีวะ DEV" แยกจาก prod เสมอ) หมวด/อีเมล → Create
3. แท็บ **Basic settings** → คัดลอก **Channel secret**
4. แท็บ **Messaging API** → ล่างสุด **Channel access token (long-lived)** → Issue → คัดลอก
5. แท็บ Messaging API → **LINE Official Account features** → กด Edit ของ "Allow bot to join group chats" (จะเปิด LINE Official Account Manager) → Settings → Account settings → เปิด **Allow bot to join group chats** → Save
6. ใน OA Manager → Response settings: **Webhook = เปิด**, **Auto-reply = ปิด**, **Greeting message = ปิด** (ไม่งั้นจะมีข้อความอัตโนมัติปนจนสับสน)

### 4.2 รันเซิร์ฟเวอร์ + ngrok

```bash
brew install ngrok
ngrok config add-authtoken <token จาก dashboard.ngrok.com>   # ครั้งเดียว
# .env: LINE_CHANNEL_SECRET=..., LINE_CHANNEL_ACCESS_TOKEN=...
# รอบแรกให้ LLM_PROVIDER=fake และ PLACES_PROVIDER=fake (ฟรี เช็กว่าต่อติดก่อน)
make local                       # หน้าต่าง 1
ngrok http 8000                  # หน้าต่าง 2
curl http://localhost:8000/      # หน้าต่าง 3: เช็กว่าเซิร์ฟเวอร์ขึ้น
```

ควรเห็น (QA รันจริงด้วย `PORT=8011` ตอนไม่ได้ใส่ access token ของคุณจะเป็น 8000):

```
WARNING config: LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN missing
INFO listening on http://localhost:8011/callback (llm=fake places=fake)
```
`curl` ได้ `pai-nhai-dee-wa local ok` · ยิง POST ที่ signature ผิดได้ `401` และ log `WARNING bad signature -> 401` ถ้าใส่ครบแล้วบรรทัด `missing` ต้องหายไป

### 4.3 ตั้ง Webhook

1. คัดลอก URL `https://xxxx.ngrok-free.app` จากหน้าต่าง ngrok
2. LINE Developers → แท็บ Messaging API → **Webhook URL** = `https://xxxx.ngrok-free.app/callback` → Update → **Verify** → ต้องขึ้น **Success** (log ฝั่งเราจะไม่มี event เพราะ verify ส่ง events ว่าง)
3. เปิด **Use webhook**
4. ngrok ฟรีเปลี่ยน URL ทุกครั้งที่รันใหม่ → ต้องแก้ Webhook URL ทุกครั้ง

### 4.4 สร้างกลุ่มทดสอบ

- ต้องมีอย่างน้อย 2 คน + บอท: ชวนเพื่อนสนิท 1-2 คน (บอกก่อนว่าเป็นบอททดสอบที่อ่านแชตได้ 60 นาที) หรือใช้ LINE บัญชีที่สองบนเครื่องอื่น/แท็บเล็ต (LINE 1 เบอร์ = 1 บัญชี)
- แอดบอทเป็นเพื่อน: แท็บ Messaging API → สแกน QR code
- สร้างกลุ่ม → เชิญเพื่อน + บอท → บอทต้องทักว่า "หวัดดีแก๊ง เราคือ ไปไหนดีวะ 👋 ..."
- แท็กบอทด้วยการพิมพ์ `@` แล้ว **เลือกชื่อบอทจากรายการ** (พิมพ์เองไม่นับเป็น mention)

### 4.5 Checklist ทดสอบมือ

ระหว่างเทส เปิดหน้าต่าง `make local` ไว้ดู log ตลอด

| # | เคส | ขั้นตอน | ที่ควรเป็น | ผ่าน? |
|---|---|---|---|---|
| 1 | เข้ากลุ่ม | เชิญบอทเข้ากลุ่ม | ข้อความทักทาย 1 ครั้ง บอกว่าอ่านแชตเฉพาะตอนเปิดโหมดช่วยคิด | ☐ |
| 2 | เงียบเมื่อไม่ถูกเรียก | ยังไม่แท็ก พิมพ์ "กินไรดี" "หิว" | บอทเงียบ log มีแค่ `event type=message` | ☐ |
| 3 | เปิด session | `@ไปไหนดีวะ กินไรดีแถวอารีย์` | ประกาศ "จะอ่านแชตกลุ่มนี้ไม่เกิน 60 นาที" + ปุ่ม [หยุดฟัง] + 3 ร้าน | ☐ |
| 4 | เงียบระหว่าง session | พิมพ์ "555", สติกเกอร์, "ok", "เมื่อวานดูบอล" | เงียบทั้งหมด | ☐ |
| 5 | จำความชอบ | เพื่อน: "เพิ่งกินญี่ปุ่นมา" → แท็ก "มีบุฟเฟต์ไหม" | ไม่มีร้านญี่ปุ่น + "(ข้ามญี่ปุ่นให้ละ...)" | ☐ |
| 6 | ประกาศสรุป | แท็ก "ประกาศหน่อย" | สรุปย่าน + ความชอบแยกคน | ☐ |
| 7 | ตัดสินใจ → การ์ดยืนยัน | พิมพ์ "โอเค ไปร้านนี้แหละ" (ไม่ต้องแท็ก) | การ์ด "สรุปว่าไปที่นี่นะ?" รายชื่อทุกคนที่พิมพ์ + [ตกลง ✅] [ยังก่อน] | ☐ |
| 8 | ต้องครบทุกคน | กด ✅ คนเดียว | "✅ 1/2 คนตกลงแล้ว" ยังไม่มีการ์ดแผน | ☐ |
| 9 | ครบแล้วได้แผน | คนที่เหลือกด ✅ | การ์ด "🎉 จบ!" + ระยะ (ระยะเส้นตรง) + ปุ่มเปิดแผนที่ เปิดแล้วเป็นร้านเดียวกัน | ☐ |
| 10 | ยังก่อน | เปิด session ใหม่ → ตัดสินใจ → กด [ยังก่อน] | "โอเค ยังไม่สรุป คุยกันต่อได้เลย" แล้วตัดสินใจใหม่ได้ | ☐ |
| 11 | การ์ดเก่า | กด ✅ บนการ์ดของ session ที่จบแล้ว | "อันนี้หมดเวลาแล้ว เรียกเราใหม่ได้เลย" | ☐ |
| 12 | หยุดฟัง | กด [หยุดฟัง] แล้วพิมพ์ "ไปกินชาบูกัน" | "โอเค หยุดฟังละ" แล้วเงียบ | ☐ |
| 13 | หมดเวลา 60 นาที | ตั้ง `SESSION_MINUTES=5` ใน `.env` → restart `make local` → เปิด session → รอ 6 นาที → "ไปร้านนี้แหละ" | เงียบ (session หมดแล้ว) กดปุ่มเก่าได้ "หมดเวลาแล้ว" (คืนค่าเป็น 60 หลังเทส) | ☐ |
| 14 | ข้อความซ้ำ | LINE Developers → Messaging API → เปิด **Webhook redelivery** แล้ว Ctrl-C เซิร์ฟเวอร์ ~10 วิระหว่างพิมพ์ แล้วเปิดใหม่ (หรือรัน `pytest -k duplicate`) | ข้อความเดียวกันไม่ได้คำตอบ 2 ครั้ง | ☐ |
| 15 | บอทออกจากกลุ่ม = ลบข้อมูล | เปิด session → เตะบอทออก → เชิญกลับ → พิมพ์ "ไปร้านนี้แหละ" | ทักใหม่ ไม่มี session เดิม (ไม่จำความชอบเก่า) | ☐ |
| 16 | ไม่มีข้อความแชตใน log | หลังเทสทั้งหมด ดู terminal ของ `make local` (หรือ copy log ลงไฟล์แล้ว `grep "อารีย์\|ญี่ปุ่น" log.txt`) | ไม่มีข้อความที่เพื่อนพิมพ์ เห็นแค่ `event type=...`, `line_reply messages=N`, `places_call` | ☐ |
| 17 | แชต 1:1 | ทักบอทในแชตส่วนตัว | "ชวนเราเข้ากลุ่มเพื่อนก่อนนะ..." | ☐ |

ถ้าเทสข้อ 1-12 ผ่านด้วย fake แล้ว ให้เปลี่ยน `.env` เป็น `LLM_PROVIDER=gemini`, `PLACES_PROVIDER=google` แล้วทำ 3, 5, 7, 9 ซ้ำ

### Error ที่เจอบ่อย

| อาการ | แก้ |
|---|---|
| Verify ขึ้น "The webhook returned an HTTP status code other than 200" (401) | `LINE_CHANNEL_SECRET` ผิด/ไม่ได้อยู่ใน `.env` แล้ว restart `make local` |
| Verify ขึ้น 404 | ลืม `/callback` ท้าย URL |
| Verify timeout / ngrok ขึ้น `ERR_NGROK_...` | `make local` ไม่ได้รันอยู่ หรือ port ไม่ใช่ 8000 |
| เชิญบอทเข้ากลุ่มไม่ได้ | ยังไม่ได้เปิด Allow bot to join group chats |
| บอทตอบข้อความอัตโนมัติแปลกๆ | ปิด Auto-reply / Greeting ใน OA Manager |
| log มี `event failed` + traceback ตอนตอบ | access token ผิด/หมดอายุ (reply ได้ 401) หรือ reply token หมดอายุ (เซิร์ฟเวอร์ช้าเกิน) |
| แท็กแล้วบอทเงียบ | พิมพ์ `@ชื่อ` เอง ไม่ได้เลือกจากรายการ จึงไม่ใช่ mention จริง |

---

## Level 5: AI eval

**เป้าหมาย:** วัดเป็นตัวเลขว่าบอทอ่านภาษาไทยถูกกี่ % แทนการ "รู้สึกว่าดีขึ้น"

### 5.1 รัน

```bash
python -m scripts.eval_intents                # กฎออฟไลน์ ฟรี
python -m scripts.eval_intents -v             # แสดง PASS/FAIL ทีละประโยค
python -m scripts.eval_intents --places       # + ค้นร้าน (fake) เช็กระยะ
set -a; . ./.env; set +a
python -m scripts.eval_intents --live         # Gemini จริง (~50 ครั้ง ≈ 0.2 บาท)
python -m scripts.eval_intents --live --places  # + Places จริง (ทุกประโยคที่ request=search เรียก 1 ครั้ง ≈ 1.2 บาทต่อครั้ง)
```

ผลจริงตอน QA รัน (กฎออฟไลน์ 27 ประโยค):

```
--- eval: 27 utterances, llm=rules ---
intent accuracy : 25/27 = 93%
all-fields exact: 24/27 = 89%
  intent    25/27
  area      7/9
  request   12/13
  ...
failures:
  u25 'กินไรดีแถวอารีย' -> area: want 'อารีย์' got None  (typo: missing ์ (known hard for rules))
  u26 'หมูกะทะกันมั้ย' -> intent: want 'food' got 'none'; likes: want ['หมูกระทะ'] got []  (typo/slang spelling (known hard for rules))
  u27 'wanna eat sushi near Siam' -> intent: want 'food' got 'none'; area: want 'สยาม' got None; request: want 'search' got 'none'  (English (known hard for rules))
places: 4 suggestions, real-place 0%, within-radius 100%
```

(real-place 0% ถูกต้องเพราะ fake ทั้งหมดขึ้นต้น `fake-` และเจอแค่แถวอารีย์ ตัวเลขนี้มีความหมายเฉพาะตอน `--live --places`)

### 5.2 สร้างชุด 50 ประโยค

ไฟล์ `tests/eval/utterances.jsonl` บรรทัดละ 1 ประโยค (ตอนนี้มี 27) ใส่เฉพาะ label ที่อยากตรวจ:

```json
{"id": "u07", "text": "เพิ่งกินญี่ปุ่นมา เอาเกาหลีได้ไหม", "mentioned": false, "intent": "food", "just_ate": ["ญี่ปุ่น"], "likes": ["เกาหลี"]}
{"id": "u11", "text": "เอาร้านที่ 2", "mentioned": false, "intent": "none", "decision": true, "pick": 2}
{"id": "u13", "text": "ไม่กินชาบู งบ 300", "mentioned": false, "intent": "none", "dislikes": ["ชาบู"], "budget": 300}
{"id": "u17", "text": "หยุดฟังได้แล้ว", "mentioned": true, "intent": "none", "request": "stop"}
{"id": "u23", "text": "เมื่อวานดูบอลมันส์มาก", "mentioned": false, "intent": "none"}
```

label ที่ใช้ได้: `intent` (food/activity/meetup/none), `area`, `request` (search/announce/vote/stop/none), `likes`/`dislikes`/`just_ate` (ตรวจว่ามีอย่างน้อยตามนี้), `decision`, `pick`, `rejects`, `budget`, `when` ("20:00"), `note`

สูตรผสม 50 ประโยค (ให้ใกล้แชตจริง):
- 15 เปิด/ขอค้น (`mentioned: true`) หลายย่าน ทั้งอาหารและกิจกรรม
- 10 ความชอบ/ไม่เอา/เพิ่งกิน/งบ/เวลา
- 5 ตัดสินใจ ("ไปร้านนี้แหละ", "จบที่ร้าน 3") + 3 ปฏิเสธที่ห้ามนับเป็นการตัดสินใจ
- 5 คำสั่ง (ประกาศ/โหวต/หยุด)
- 7 คุยเล่นที่ต้องเป็น `intent: none` (เรื่องงาน บอล แฟน)
- 5 ยาก: พิมพ์ผิด สแลง ("ป่ะ", "แดกไรดี") อังกฤษปนไทย emoji
- **ห้ามใช้แชตจริงของเพื่อน** ให้แต่งประโยคเลียนแบบ (PDPA)

### 5.3 วัดอะไร และเกณฑ์

| ตัวชี้วัด | วิธีคิด | เกณฑ์ Gate 1 (แนะนำ) |
|---|---|---|
| Intent accuracy | `intent` ถูก / ทั้งหมด | Gemini ≥ 90% |
| All-fields exact | ทุก label ในบรรทัดถูก / ทั้งหมด | Gemini ≥ 80% |
| Decision false positive | ประโยคปฏิเสธที่ได้ `decision=true` | 0 ครั้ง (ถ้าผิด บอทจะส่งการ์ดยืนยันมั่ว) |
| Real-place rate | ร้านที่ไม่ใช่ fake และมีลิงก์ Maps / ร้านทั้งหมด (`--live --places`) จากนั้นสุ่มเปิดดูเอง 10 ร้าน | 100% |
| Within-radius rate | ระยะคำนวณใหม่ ≤ รัศมี / ร้านทั้งหมด | 100% (ต่ำกว่านี้ = บั๊กโค้ด ไม่ใช่ AI) |

### 5.4 รันซ้ำเมื่อไหร่

- แก้ `SYSTEM_PROMPT` ใน `adapters/llm.py` หรือเปลี่ยน `GEMINI_MODEL`
- แก้กฎ/คำศัพท์ใน `RuleExtractor` (แบบออฟไลน์ ฟรี รันได้ทุก commit)
- เพิ่ม/แก้ `MessageDelta` ใน `adapters/models.py`
- เจอบั๊กการอ่านภาษาจากแชตจริง → เพิ่มประโยคแบบนั้นลง jsonl ก่อนแก้ (กันพังซ้ำ)
- ก่อน Gate 1 และเดือนละครั้ง (Google อัปเดตโมเดลเงียบๆ ได้)

---

## Template รายงานบั๊ก

```markdown
### [สั้นๆ] เช่น "ตอบ 'ได้ 0 ที่ละ' + การ์ดว่าง เมื่อย่านเป็นบางนา"
- ระดับ: P0 (เสียเงิน/ข้อมูลรั่ว/บอทพูดเอง) | P1 (flow พัง) | P2 (ตอบแปลก) | P3 (คำผิด)
- ที่ไหน: simulator fake | simulator --live | LINE จริง (commit: `git rev-parse --short HEAD`)
- ขั้นตอน (copy ไปวางใน --interactive ได้):
  A: @bot กินไรดีแถวบางนา
- ที่ควรเป็น:
- ที่เป็นจริง (แปะ output/screenshot, ห้ามแปะแชตจริงของเพื่อน):
- เกิดทุกครั้งไหม: ทุกครั้ง / 3 ใน 5 ครั้ง
- น่าจะเป็น: LLM | กฎ | โค้ด  (ดูวิธีแยกด้านล่าง)  ไฟล์ที่สงสัย:
```

## แยกยังไงว่าเป็น LLM, กฎ หรือโค้ด

1. **รันซ้ำแบบ fake** (`python -m scripts.simulate --interactive`) ด้วยบทเดียวกัน
   - fake ก็พัง → ไม่ใช่ LLM ต่อข้อ 2
   - fake ผ่าน แต่ `--live` พัง → น่าจะ **LLM** (prompt/โมเดล) ยืนยันด้วยข้อ 3
2. **ทดสอบกฎทีละประโยค**:
   ```bash
   python -c "from adapters.llm import RuleExtractor; print(RuleExtractor().extract_sync('กินไรดีแถวอารีย', mentioned=True))"
   ```
   - ค่าที่อ่านได้ผิด (เช่น `area=None`) → **กฎ** (`adapters/llm.py` คำศัพท์/regex)
   - อ่านถูกหมดแต่บอทยังทำผิด → **โค้ด** (`session/engine.py`, `session/merge.py`, `features/search.py`, `features/cards.py`)
3. **LLM:** ใส่ประโยคนั้นใน jsonl แล้ว `python -m scripts.eval_intents --live -v` 3 รอบ ถ้าผิดบ้างถูกบ้าง = LLM ไม่นิ่ง (แก้ prompt/ตัวอย่าง) ถ้าผิดทุกครั้ง = prompt ไม่ครอบคลุม
4. **ร้าน/ระยะผิด:** ระยะเกินรัศมี = โค้ด (`features/search.py rank`) · ร้านไม่มีจริง/ปิด = ข้อมูล Google (แจ้งพร้อม place_id) · LLM ไม่มีสิทธิ์คิดระยะเลย
5. **ทำงานใน simulator แต่ไม่ทำงานใน LINE จริง** → ตั้งค่า LINE/ngrok/token (ดูตาราง error Level 4) หรือรูปแบบ event จริงต่างจาก `scripts/events.py`

---

## ก่อนชวนเพื่อนจริง (Gate 1) ต้องผ่านทุกข้อ

- [ ] `make test` และ `make lint` ผ่านทั้งหมด
- [ ] `make simulate` จบด้วย `session: ended` และ 10 บทใน Level 2 เป็นไปตามตาราง
- [ ] Eval ด้วย Gemini: intent ≥ 90%, decision false positive = 0, ชุดครบ 50 ประโยค
- [ ] `--live --places`: real-place 100%, within-radius 100%, สุ่มเปิด Maps 10 ร้านมีจริงและไม่ปิดถาวร
- [ ] Checklist Level 4 ผ่านครบ 17 ข้อ บน LINE จริงกับ Gemini + Places จริง
- [ ] `GEMINI_PAID_TIER_CONFIRMED=true` เฉพาะเมื่อ billing เปิดจริง
- [ ] Places quota ต่อวัน + Google budget alert + AWS budget alarm ตั้งแล้ว และรู้วิธีกด kill switch (`BOT_ENABLED=false`)
- [ ] log ไม่มีข้อความแชตแม้แต่บรรทัดเดียว (ข้อ 16) รวม traceback ตอน error
- [ ] บอกเพื่อนก่อนว่าบอทอ่านแชตได้ไม่เกิน 60 นาทีหลังเรียก และกด [หยุดฟัง] ได้
- [ ] Known issues ระดับ P0/P1 ด้านล่างปิดหมดแล้ว หรือยอมรับเป็นลายลักษณ์อักษร

---

## Known issues found by QA (2026-11-16)

| # | ระดับ | ปัญหา | วิธีทำซ้ำ | ไฟล์ที่สงสัย | สถานะ |
|---|---|---|---|---|---|
| 1 | P1 | ย่านที่กฎรู้จักแต่ไม่มีพิกัดใน `AREA_CENTERS` (บางนา รัชดา ลาดพร้าว พระราม 9 เยาวราช ราชเทวี) + geocode ไม่เจอ → ตอบ "ได้ 0 ที่ละ" + การ์ดร้านว่าง (LINE จริงน่าจะ reject ข้อความว่าง ทั้งชุด reply หาย) | `A: @bot กินไรดีแถวบางนา` | `session/engine.py _search_replies` ไม่จัดการ `error == "no_area"` | **แก้แล้ว (tiny fix)**: ตอบ "หาพิกัด{ย่าน}ไม่เจอ" + ปุ่มย่าน และเพิ่มเทส `test_unknown_area_asks_again_instead_of_empty_card` ควรเพิ่มพิกัดย่านเหล่านี้ใน `features/geo.py` ด้วย (ส่ง web-dev) |
| 2 | P1 | Dedup mark event ว่า "เห็นแล้ว" ก่อนประมวลผล ถ้า worker พังกลางทาง SQS retry จะถูกข้าม ข้อความหาย (มี TODO ใน ARCHITECTURE.md) | ทำให้ `line.reply` throw ครั้งแรกแล้วส่ง event เดิมซ้ำ | `session/engine.py handle`, `store/*.seen_event` | เปิด |
| 3 | P2 | คนที่ไม่เคยพิมพ์ใน session กด [ยังก่อน] ยกเลิกการ์ดยืนยันได้ แต่ไม่ถูกเพิ่มเป็นผู้ร่วม (กด [ตกลง] จะถูกเพิ่ม) พฤติกรรมไม่สม่ำเสมอ | บท #6 ใน Level 2 | `session/engine.py _on_ack` | เปิด ต้องตัดสินใจ product |
| 4 | P2 | กฎออฟไลน์ไม่รองรับพิมพ์ผิด/สะกดแบบพูด/อังกฤษ ("อารีย", "หมูกะทะ", "sushi near Siam") กระทบตอน Gemini ล่ม/ชนเพดาน 40 ครั้ง | eval u25-u27 | `adapters/llm.py RuleExtractor` | เปิด |
| 5 | P2 | "ไกลไป" และ "ไม่เกิน 5 กม." ไม่ถูกอ่าน รัศมีคงที่ (อาหาร 3 / กิจกรรม 5 กม.) ไม่มีฟิลด์รัศมีใน `MessageDelta` | บท #10 ใน Level 2 | `adapters/models.py`, `features/search.py` | เปิด (เป็น must-test ของ QA) |
| 6 | P2 | `scripts/local_server.py` ใช้ `log.exception` → traceback อาจมีข้อความแชตถ้า exception message ใส่ input (เช่น pydantic ValidationError) ขัดกับ "ไม่มีข้อความแชตใน log" (Lambda worker log แค่ชื่อ exception ถูกแล้ว) | ทำให้ engine throw ระหว่าง local test | `scripts/local_server.py` | เปิด (เฉพาะ local) |
| 7 | P3 | ข้อความเปิด session บอก "จำว่าใครอยากกินอะไร" แม้เป็นกิจกรรม (โบว์ลิ่ง) | `A: @bot ไปไหนดีแถวสยาม โบว์ลิ่ง` | `features/cards.py listening_notice` | เปิด |
| 8 | P3 | `simulate --live` และ `eval_intents --live` ไม่โหลด `.env` เอง (ต่างจาก `make local`) ลืม source แล้ว Gemini fail เงียบๆ ไปใช้กฎ | รัน `--live` โดยไม่ source | `scripts/simulate.py`, `Makefile` | เปิด (เขียนไว้ใน Level 3 แล้ว) |
| 9 | P3 | Geocode ของย่านที่ไม่อยู่ในตารางเรียก Places แต่ไม่ถูกนับใน `QUOTA#PLACES` | ย่านนอกตาราง + `PLACES_PROVIDER=google` | `features/search.py resolve_center` | เปิด |

**การแก้ production code ของ QA:** มีจุดเดียวคือ #1 (`session/engine.py` เพิ่มการจัดการ `no_area` 3 บรรทัด)
