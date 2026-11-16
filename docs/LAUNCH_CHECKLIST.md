# Gate 0 Go/No-Go: "บอทตอบในกลุ่ม LINE จริง"

**นิยาม Gate 0:** บอทที่ deploy บน AWS ตอบ `@ไปไหนดีวะ ...` ในกลุ่ม LINE จริงได้ ภายในงบ และมีปุ่มหยุด/ปิดฉุกเฉิน
ทำตาม `docs/DEPLOY.md` ก่อน แล้วติ๊กรายการนี้ · ทุกข้อ **ต้องผ่าน** (NO-GO ถ้าข้อใดข้อหนึ่งในหมวด A-D ไม่ผ่าน) · หมวด E เป็นข้อแนะนำ

## สถานะ ณ 2026-11-16 (สิ่งที่ทำเสร็จแล้ว vs ที่ Mickie ต้องทำเอง)

| รายการ | สถานะ |
|---|---|
| โค้ด session/engine, webhook, worker, test 93 ข้อผ่าน (offline, ของปลอม) | เสร็จ (รันซ้ำได้ `make test`) |
| `template.yaml` ผ่าน `cfn-lint` และ `sam validate --lint`, `sam build` สำเร็จบน Linux | เสร็จ (ตรวจบนเครื่อง dev ไม่ใช่ macOS) |
| IAM แบบ least-privilege, DLQ, TTL, log 7 วัน, reserved concurrency, Budgets + alarm, secret อยู่ใน SSM | เสร็จใน template (**ยังไม่เคย deploy จริง**) |
| Runbook `docs/DEPLOY.md`, สคริปต์ `scripts/smoke.py` (ทดสอบกับ handler จริงในเครื่องแล้ว) | เสร็จ |
| สมัคร/ตั้งค่า AWS account, IAM user, MFA | **Mickie ทำเอง** |
| LINE channel: Channel secret + access token, เปิด Allow join group chats, ปิด auto-reply | **Mickie ทำเอง** |
| Gemini API key (project เปิด billing) | **Mickie ทำเอง** (ไม่ต้องใช้ใน Stage A) |
| Google Places API key + จำกัด key + ตั้งโควตารายวัน + Google budget | **Mickie ทำเอง** (ไม่ต้องใช้ใน Stage A) |
| อีเมลรับ alarm + กด Confirm subscription | **Mickie ทำเอง** |
| กลุ่ม LINE ทดสอบ + เพื่อน 1-2 คน | **Mickie ทำเอง** |
| deploy จริง, LINE Verify จริง, บอทตอบในกลุ่มจริง | **ยังไม่มีใครรันได้ นอกจาก Mickie** (ไม่มี AWS credentials ฝั่งทีมพัฒนา) |

## A. ก่อน deploy (go/no-go)
- [ ] `make test` และ `make lint` ผ่านบนเครื่อง Mickie
- [ ] `sam validate --lint` ผ่าน
- [ ] root account เปิด MFA และไม่มี access key ของ root
- [ ] secret อยู่ใน SSM เท่านั้น (`git grep -n "AKIA\|sk-\|AIza"` ต้องไม่เจออะไร) และ `.env` ไม่ถูก commit
- [ ] เช็กโควตา Lambda แล้ว (DEPLOY ข้อ 1.7) เลือก `RC` ถูกต้อง

## B. ตัวกันงบ (Cost guards) ต้องครบก่อนเปิดให้คนอื่นใช้
เป้า: ไม่เกิน **1,000 บาท/เดือน** (≈ USD 28 ตามเรทที่ตั้งใน template ปรับ `MonthlyBudgetUsd` ได้ถ้าเรทเปลี่ยน)
- [ ] AWS Budgets `pai-nhai-dee-wa-dev-monthly` มีอยู่ (แจ้งเมลที่ 80% จริง, 100% จริง, และ forecast >100%) ตรวจที่ Billing > Budgets · **Budgets แค่แจ้งเตือน ไม่ตัดบริการ**
- [ ] ยืนยันอีเมล SNS แล้ว (DLQ, worker error >=3 ครั้ง/5 นาที, webhook >3,000 ครั้ง/ชั่วโมง)
- [ ] Lambda reserved concurrency: webhook 10 / worker 5 (หรือตั้ง -1 พร้อมเหตุผลเพราะโควตาต่ำ)
- [ ] เพดานในโค้ดไม่ถูกแก้ให้สูงขึ้น: LLM 40 ครั้ง/session, ค้น 10 ครั้ง/กลุ่ม/วัน, Places 300 ครั้ง/วันรวม (`config.py`, `MaxPlacesCallsPerDay`)
- [ ] Google: key จำกัดเฉพาะ Places API (New), **โควตารายวันตั้งแล้ว**, Google Cloud budget alert ตั้งแล้ว (Stage B)
- [ ] Gemini: ใช้โมเดลเล็ก (`gemini-2.5-flash-lite` ค่าเริ่มต้น) ไม่เปลี่ยนเป็นรุ่นแพง
- [ ] ไม่มี push message (บอทใช้ reply อย่างเดียว) ไม่มีค่าข้อความ LINE เพิ่ม
- [ ] รู้วิธีปิดฉุกเฉิน 3 วิธี (DEPLOY ข้อ 8) และลองปิด webhook ใน LINE Console หนึ่งครั้งแล้วเปิดใหม่
- [ ] ตั้งนัดตัวเองดูบิลวันที่ 3 และวันที่ 7 หลังเปิดใช้ (Billing > Cost Explorer; ข้อมูลบิลอาจช้า ~1 วัน)

## C. หลัง deploy: ทดสอบ Gate 0
Stage A (fake) ก่อน แล้วค่อย Stage B
- [ ] `python3 -m scripts.smoke --url "$URL" --secret-ssm ...` ได้ `SMOKE OK`
- [ ] LINE Console กด **Verify** ได้ Success, เปิด Use webhook
- [ ] ปิด Auto-response และ Greeting แล้ว (ไม่งั้นบอทตอบซ้อนกับข้อความอัตโนมัติ)
- [ ] เชิญบอทเข้ากลุ่มทดสอบได้ (เปิด Allow join group chats แล้ว)
- [ ] `@ไปไหนดีวะ กินไรดีแถวอารีย์` -> บอทตอบการ์ด PDPA + [หยุดฟัง] + 3 ร้าน ภายใน ~5 วินาที (**นี่คือ Gate 0**)
- [ ] ข้อความที่ไม่ @ ใน**ช่วงไม่มี session** บอทต้องเงียบสนิท
- [ ] กด **หยุดฟัง** แล้ว session จบ ข้อความถัดไปไม่ถูกอ่าน
- [ ] ไล่ flow ครบ: คุยเลือกร้าน -> "ไปร้านนี้แหละ" -> การ์ดยืนยัน -> ทุกคนกด ตกลง -> การ์ดแผน (ใช้เพื่อน 2 คน ตาม `docs/TESTING.md` Level 4)
- [ ] ส่ง "555" สติกเกอร์ ลิงก์ล้วน แล้วดู `sam logs` ว่า `queued` ไม่เพิ่ม (prefilter ทำงาน)
- [ ] ใน log ไม่มีข้อความแชตของเพื่อน (ค้นดูด้วยตา 1 รอบ)
- [ ] Stage B: ร้านเป็นของจริง ไม่มี `[ตัวอย่าง]`, ระยะทางสมเหตุสมผล, ตั้ง `GeminiPaidTierConfirmed=true` เฉพาะเมื่อ billing ของ Gemini เปิดจริง
- [ ] DLQ ว่าง (`aws sqs get-queue-attributes` ... `ApproximateNumberOfMessages` = 0) หลังทดสอบ
- [ ] ลอง rollback หรือ `BotEnabled=false` หนึ่งครั้งในกลุ่มทดสอบแล้วบอทเงียบจริง

## D. PDPA / ความเป็นส่วนตัว (ต้องผ่านก่อนใช้กับกลุ่มที่มีคนอื่นนอกจากตัวเอง)
สิ่งที่บอทเก็บ: สรุปความชอบ (ย่าน, ชอบ/ไม่เอา, งบ), user ID ของคนที่คุยใน session, ร้านที่เสนอ · **ไม่เก็บข้อความดิบ** · ทุกอย่างหมดอายุเองภายใน 60 นาที (counter รายวัน 2 วัน, event id 1 วัน)
ข้อความที่บอทอ่านขณะ session ถูกส่งให้ Gemini (Google) ประมวลผลเพื่อสกัดความชอบ จึงต้องแจ้งให้ชัด

- [ ] แอดมินกลุ่ม/คนเชิญบอท **โพสต์ประกาศนี้ในกลุ่มก่อนเริ่มใช้** (ข้อความสั้น ปรับได้):

  > 🤖 แจ้งเพื่อนๆ: กลุ่มนี้เพิ่มบอท "ไปไหนดีวะ" ช่วยเลือกร้าน บอทจะ **เริ่มฟังก็ต่อเมื่อมีคน @ เรียก** และฟังไม่เกิน 60 นาที ไม่เก็บข้อความแชต เก็บแค่สรุปสิ่งที่ชอบ/ไม่ชอบ (เช่น ไม่กินเผ็ด งบ 300) กับ LINE user ID ชั่วคราว แล้วลบอัตโนมัติ ข้อความช่วงที่ฟังจะถูกส่งให้ Google Gemini ประมวลผล (แบบ paid ที่ไม่นำไปเทรนโมเดล) ใครไม่สะดวก กด **[หยุดฟัง]** หรือพิมพ์ "@ไปไหนดีวะ หยุด" ได้ตลอด หรือแจ้ง [ชื่อเจ้าของ] ให้ถอดบอทออก

- [ ] การ์ดแรกของบอทมี [หยุดฟัง] และบอก "ไม่เกิน 60 นาที" (มีในโค้ดแล้ว ยืนยันด้วยตาในกลุ่มจริง)
- [ ] ถ้ามีเพื่อนไม่เห็นด้วย -> ถอดบอทออกจากกลุ่มนั้นทันที
- [ ] ถ้าจะเปิดสาธารณะ/หลายกลุ่ม ต้องมี Privacy Policy และช่องทางติดต่อเจ้าของข้อมูล และให้ที่ปรึกษากฎหมายทบทวน (ข้อความข้างบนเป็นร่างเพื่อ pilot กับเพื่อน ไม่ใช่คำแนะนำทางกฎหมาย)

## E. ข้อแนะนำ (ไม่บล็อก Gate 0)
- [ ] ใช้ LINE channel แยก dev/prod และ stack `dev`/`prod` แยก (`samconfig.toml` มีทั้งคู่)
- [ ] จด runbook "ถ้าบิลพุ่ง": ปิด webhook > `BotEnabled=false` > ดู Cost Explorer แยกตาม service > ดู Google Cloud Console > rotate key ที่รั่ว
- [ ] ลดสิทธิ์ IAM user `pai-deployer` จาก AdministratorAccess เมื่อ stack นิ่งแล้ว

## ผลการตัดสินใจ

| วันที่ | ผู้ตัดสิน | GO / NO-GO | หมายเหตุ |
|---|---|---|---|
| | | | |

## สิ่งที่ยัง **ไม่ได้ตรวจ** (ต้องเห็นของจริงถึงจะมั่นใจ)
- การ deploy จริงบน AWS (ไม่มี credentials) รวมถึงโควตา Lambda ของบัญชี Mickie
- Function URL ที่เปิดสาธารณะรับ request จาก LINE จริง และ latency ภายใน 5 วินาที
- `sam build` บน macOS (ตรวจบน Linux x86_64 ได้ wheel arm64 ถูกต้อง)
- พฤติกรรม Gemini/Places จริงและคุณภาพภาษาไทย (ใช้ eval ใน `docs/TESTING.md` Level 5)
- ตัวเลขค่าใช้จ่ายจริงต่อเดือน (เป็นเพดานที่ตั้งไว้ ไม่ใช่ค่าที่วัดได้)
