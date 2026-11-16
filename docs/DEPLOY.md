# Runbook: Deploy ไปไหนดีวะ ขึ้น AWS (macOS, มือใหม่ LINE bot)

เขียนให้ Mickie ทำตามได้ทีละบล็อก (copy-paste) · เวลารวมประมาณ 2-3 ชั่วโมงถ้าไม่ติดอะไร
ผ่านการตรวจแล้ว: `cfn-lint`, `sam validate --lint`, `sam build` (บน Linux) · **ยังไม่เคย deploy จริง** เพราะไม่มี AWS credentials ผลที่ได้จริงอาจต่างจากที่เขียน ถ้าติดให้ดูหัวข้อ "แก้ปัญหา" ท้ายไฟล์

ลำดับที่แนะนำ (ถูกที่สุดก่อน): **Stage A** deploy แบบ `fake` (ไม่เรียก Gemini/Places เลย) เพื่อพิสูจน์ว่า LINE ต่อติด → **Stage B** เปลี่ยนเป็น Gemini + Places จริง

---

## 0. เตรียมเครื่อง (macOS, ครั้งเดียว)

```bash
brew install awscli aws-sam-cli python@3.12 jq
python3.12 --version      # ต้องได้ 3.12.x (sam build ใช้ runtime ตรงกับ Lambda)
aws --version && sam --version
export SAM_CLI_TELEMETRY=0
cd pai-nhai-dee-wa && python3 -m venv .venv && source .venv/bin/activate && make install && make test
```
`make test` ต้องผ่านทั้งหมดก่อน deploy ทุกครั้ง

## 1. สร้าง AWS account และ IAM user

1. สมัคร <https://aws.amazon.com/> (ต้องมีบัตรเครดิต) เลือก region ที่ใช้ทั้งโปรเจกต์: **Asia Pacific (Singapore) `ap-southeast-1`**
2. ล็อกอินด้วย root แล้ว **เปิด MFA ให้ root** (IAM > Security credentials) **ห้ามสร้าง access key ของ root**
3. เปิดให้ IAM ดูบิลได้: Account (มุมขวาบน) > Account > ส่วน "IAM user and role access to Billing information" > Activate
4. สร้าง IAM user สำหรับ deploy: IAM > Users > Create user `pai-deployer` (ไม่ต้องให้เข้า console) > Attach policies directly > **`AdministratorAccess`** > Create
   - เหตุผล: SAM สร้าง IAM role, Lambda, SQS, DynamoDB, Budgets, SNS ฯลฯ การทำ policy แคบกว่านี้เสียเวลามากสำหรับ pilot บัญชีส่วนตัวคนเดียว (ภายหลังค่อยลดสิทธิ์ได้) ชดเชยด้วย MFA + ไม่แชร์ key
5. user นั้น > Security credentials > **Create access key** > ใช้แบบ "Command Line Interface (CLI)" > เก็บ key ไว้ใน password manager (ห้ามใส่ใน git/แชต)
6. ตั้งค่า CLI:
   ```bash
   aws configure --profile pai        # ใส่ Access key, Secret, region = ap-southeast-1, output = json
   export AWS_PROFILE=pai AWS_REGION=ap-southeast-1 AWS_DEFAULT_REGION=ap-southeast-1
   aws sts get-caller-identity        # ต้องเห็น arn ของ pai-deployer
   ```
   (ต้อง `export` สามบรรทัดนี้ใหม่ทุกครั้งที่เปิด terminal ใหม่)
7. **เช็กโควตา Lambda** (บัญชีใหม่มักได้เพดานต่ำมาก ทำให้ตั้ง reserved concurrency ไม่ได้):
   ```bash
   aws lambda get-account-settings --query 'AccountLimit.ConcurrentExecutions'
   ```
   - ได้ **120 ขึ้นไป** → ใช้ค่าเริ่มต้นใน template ได้ (webhook 10 + worker 5)
   - ได้ **น้อยกว่า 120** (เช่น 10) → ตอน deploy ต้องใส่ `WebhookReservedConcurrency=-1 WorkerReservedConcurrency=-1` (ตัวแปรชุด `RC` ในขั้น 4) ตัวกันงบอื่นยังอยู่ครบ (เพดาน Places/LLM ในโค้ด, Budgets, kill switch) และขอเพิ่มโควตาได้ที่ Service Quotas > Lambda > "Concurrent executions"

## 2. เตรียม key ภายนอก (ทำเองที่เว็บ แล้วเก็บไว้ก่อน อย่าแปะลงแชต)

| Key | ที่ไหน | หมายเหตุ |
|---|---|---|
| LINE Channel secret + Channel access token (long-lived) | <https://developers.line.biz/console/> ตาม README หัวข้อ "ตั้งค่า LINE OA" | ใช้ Stage A เลย |
| Gemini API key | <https://aistudio.google.com/> ใน project ที่ **เปิด billing (paid tier)** | จำเป็นก่อนให้บอทอ่านแชต (PDPA) ใช้ใน Stage B |
| Google Places API key | Google Cloud Console > Enable **Places API (New)** > Credentials > Create API key | ทำ 2 ข้อล่างก่อนใช้ |

**จำกัดความเสียหายของ Google key (ทำก่อน Stage B):**
1. Credentials > คลิก key > API restrictions > Restrict key > เลือกเฉพาะ **Places API (New)** (key ของ Gemini ควรเป็นคนละ key และจำกัดเฉพาะ Generative Language API)
2. APIs & Services > Places API (New) > **Quotas & System Limits** > ตั้งเพดาน Text Search ต่อวัน (แนะนำ 300) และต่อนาทีให้ต่ำ ๆ (ชื่อเมนูอาจต่างเล็กน้อยตามเวอร์ชันหน้าเว็บ)
3. Billing > Budgets & alerts > สร้าง budget ของ Google Cloud ~ 1,000 บาท/เดือน (แจ้งเตือนอย่างเดียว **ไม่ตัดบริการอัตโนมัติ** เพดานจริงคือโควตาข้อ 2 + `MAX_PLACES_CALLS_PER_DAY` ในโค้ด)

## 3. เก็บ secret ใน SSM Parameter Store (SecureString)

ใช้ `read -s` เพื่อไม่ให้ค่าโผล่ใน history/จอ รันทีละบล็อก วางค่าแล้วกด Enter:

```bash
P=/pai-nhai-dee-wa/dev      # ถ้า deploy prod ให้เปลี่ยนเป็น /pai-nhai-dee-wa/prod

read -rs -p "LINE channel secret: " V; echo
aws ssm put-parameter --type SecureString --overwrite --name $P/line-channel-secret --value "$V"; unset V

read -rs -p "LINE channel access token: " V; echo
aws ssm put-parameter --type SecureString --overwrite --name $P/line-channel-access-token --value "$V"; unset V
```
เก็บ Gemini/Places ทีหลังตอน Stage B ได้ (ถ้ายังไม่มี บอทแบบ `fake` ก็ทำงานได้):
```bash
read -rs -p "Gemini API key: " V; echo
aws ssm put-parameter --type SecureString --overwrite --name $P/gemini-api-key --value "$V"; unset V

read -rs -p "Google Places API key: " V; echo
aws ssm put-parameter --type SecureString --overwrite --name $P/google-places-api-key --value "$V"; unset V
```
ตรวจว่ามีครบ (ไม่โชว์ค่า): `aws ssm describe-parameters --parameter-filters "Key=Name,Option=BeginsWith,Values=$P" --query 'Parameters[].[Name,Type]' --output table`

> สิทธิ์ใน template: webhook อ่านได้แค่ `line-channel-secret`, worker อ่านได้แค่ 3 ตัวที่เหลือ ไม่มี secret ใน environment variable ของ Lambda (มีแต่ "ชื่อ" parameter)

## 4. Deploy (Stage A: ของปลอม ไม่เรียก Gemini/Places)

```bash
export ALERT_EMAIL="อีเมลของ-mickie@example.com"
RC=""        # ถ้าโควตาขั้น 1.7 < 120 ให้ใช้: RC="WebhookReservedConcurrency=-1 WorkerReservedConcurrency=-1"

sam validate --lint
sam build
sam deploy --config-env dev --parameter-overrides \
  Stage=dev AlertEmail=$ALERT_EMAIL LlmProvider=fake PlacesProvider=fake GeminiPaidTierConfirmed=false $RC
```
- SAM จะโชว์ change set แล้วถาม `Deploy this changeset? [y/N]` ให้ตรวจแล้วกด `y` (ครั้งแรกสร้าง S3 bucket จัดการให้เอง)
- ใช้เวลา ~3-5 นาที จบด้วย Outputs ที่มี `WebhookUrl`
- **เช็กอีเมล** แล้วกด "Confirm subscription" ในเมลจาก AWS Notifications (ถ้าไม่กด จะไม่ได้เมลแจ้งเตือน DLQ/error) ส่วนเมล Budgets ไม่ต้องกดยืนยัน
- เก็บ URL:
  ```bash
  URL=$(aws cloudformation describe-stacks --stack-name pai-nhai-dee-wa-dev \
        --query "Stacks[0].Outputs[?OutputKey=='WebhookUrl'].OutputValue" --output text)
  echo $URL
  ```

## 5. Smoke test หลัง deploy (ไม่เรียก API ภายนอก ไม่เสียเงิน)

```bash
python3 -m scripts.smoke --url "$URL" --secret-ssm $P/line-channel-secret
```
ต้องเห็น `PASS` 3 บรรทัด + `SMOKE OK` (ไม่ลายเซ็น = 401, ลายเซ็นผิด = 401, ลายเซ็นถูก = 200) · ตัวสคริปต์ส่งแค่ webhook ที่ไม่มี event จึงไม่เข้าคิวและไม่เรียก worker
ถ้าไม่อยากให้สคริปต์เรียก aws เอง: `LINE_CHANNEL_SECRET=xxx python3 -m scripts.smoke --url "$URL" --secret-from-env`

ตรวจลายเซ็นด้วยมือ (เข้าใจว่ามันทำงานยังไง):
```bash
SECRET=$(aws ssm get-parameter --with-decryption --name $P/line-channel-secret --query Parameter.Value --output text)
BODY='{"destination":"Utest","events":[]}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -binary | base64)
curl -s -o /dev/null -w "signed=%{http_code}\n"  -X POST "$URL" -H "x-line-signature: $SIG" -H "Content-Type: application/json" -d "$BODY"
curl -s -o /dev/null -w "unsigned=%{http_code}\n" -X POST "$URL" -H "Content-Type: application/json" -d "$BODY"
unset SECRET
```
ต้องได้ `signed=200` และ `unsigned=401`

## 6. ตั้ง webhook ใน LINE + เชิญบอทเข้ากลุ่ม

1. LINE Developers Console > channel > แท็บ **Messaging API** > **Webhook URL** = ค่า `$URL` > **Update** > กด **Verify** ต้องขึ้น Success > เปิด **Use webhook**
2. ใน **LINE Official Account Manager** (ปุ่ม "LINE Official Account Manager" ในแท็บเดียวกัน) > Settings > **Response settings**: ปิด **Auto-response messages** และ **Greeting message**, เปิด **Webhook**
3. Settings > **Account settings** > เปิด **"Allow bot to join group and multi-person chats"** (ถ้าไม่เปิด จะเชิญบอทเข้ากลุ่มไม่ได้)
4. เพิ่มเพื่อนบอทด้วย QR code (แท็บ Messaging API) > ในแอป LINE เปิดกลุ่มทดสอบ (ใช้เพื่อน 1-2 คน หรือกลุ่มที่มีแค่ตัวเอง + บัญชีรอง) > เมนู > เชิญ > เลือกบอท
5. พิมพ์ในกลุ่ม: `@ไปไหนดีวะ กินไรดีแถวอารีย์` (ต้องกด mention จริงจากรายชื่อ ไม่ใช่พิมพ์ข้อความเฉย ๆ) ถ้าถูกต้อง บอทตอบ PDPA notice + ร้านขึ้นต้นด้วย `[ตัวอย่าง]` (ของปลอม) = **LINE ต่อติด**
6. ดู log ตอนทดสอบ: `sam logs --stack-name pai-nhai-dee-wa-dev --tail` (log ไม่มีข้อความแชต มีแค่จำนวน event/ชื่อ error)

## 7. Stage B: เปลี่ยนเป็น Gemini + Places จริง

ทำเมื่อ (ก) key ครบใน SSM (ข) ตั้งโควตา Google แล้ว (ค) Gemini project เปิด billing แล้วจริง
```bash
sam deploy --config-env dev --parameter-overrides \
  Stage=dev AlertEmail=$ALERT_EMAIL LlmProvider=gemini PlacesProvider=google GeminiPaidTierConfirmed=true $RC
```
> `GeminiPaidTierConfirmed=true` คือ "ฉันยืนยันว่าเป็น paid tier" ถ้าตั้งเท็จ ๆ แชตของเพื่อนอาจถูก Google เอาไปพัฒนาโมเดล ถ้ายังไม่แน่ใจให้ใส่ `false` (บอทจะตอบแค่ตอนถูก @ และตอนกดปุ่ม ไม่อ่านแชต)

จากนั้นทดสอบในกลุ่มอีกรอบ ร้านต้องเป็นร้านจริง (ไม่มี `[ตัวอย่าง]`) แล้วไล่ตาม `docs/LAUNCH_CHECKLIST.md`

## 8. คำสั่งใช้บ่อยตอนดูแล

```bash
sam logs --stack-name pai-nhai-dee-wa-dev --tail                      # ดู log
aws cloudwatch describe-alarms --state-value ALARM --query 'MetricAlarms[].AlarmName'   # alarm ไหนดัง
# ดูว่ามี event ตกค้างใน DLQ ไหม (ชื่อคิวขึ้นต้น pai-nhai-dee-wa-dev-DeadLetterQueue)
aws sqs list-queues --queue-name-prefix pai-nhai-dee-wa-dev
```

**ปิดบอทฉุกเฉิน (เลือกอย่างเร็วที่สุดก่อน):**
1. เร็วสุด ~10 วินาที: LINE Developers Console > Messaging API > ปิด **Use webhook**
2. Kill switch ในโค้ด: deploy ซ้ำด้วย `BotEnabled=false` (บอทเงียบ ไม่เรียก Gemini/Places)
3. ให้บอทออกจากกลุ่ม: ในกลุ่ม LINE กดเมนู > ลบ/ออกจากสมาชิก หรือให้แอดมินกลุ่มเตะบอท

## 9. Rollback

- **deploy ล้มกลางทาง**: CloudFormation rollback เองอัตโนมัติ ดู `aws cloudformation describe-stack-events --stack-name pai-nhai-dee-wa-dev --max-items 15`
  ถ้าล้มตอนสร้างครั้งแรก stack จะค้างสถานะ `ROLLBACK_COMPLETE` ต้องลบก่อนค่อยลองใหม่: `sam delete --stack-name pai-nhai-dee-wa-dev --no-prompts`
- **deploy สำเร็จแต่บอทพัง**: กลับไปโค้ดเวอร์ชันก่อนหน้าแล้ว deploy ซ้ำ
  ```bash
  git log --oneline -10                 # หา commit ที่ดี
  git switch --detach <commit-ที่ดี>    # ดูโค้ดเก่า (ไม่แก้ history)
  sam build && sam deploy --config-env dev --parameter-overrides Stage=dev AlertEmail=$ALERT_EMAIL $RC
  git switch -                          # กลับ branch เดิม
  ```
  (ต้องใส่ override ชุดเดิม เช่น `LlmProvider=...` ให้ตรงกับที่ใช้อยู่ ไม่งั้นจะกลับเป็นค่า default)
- **ข้อมูล**: DynamoDB เก็บแค่ session ชั่วคราว (หมดอายุเองใน 60 นาที) ไม่ต้อง restore
- **อาการแย่เร็ว**: ปิด webhook ใน LINE ก่อน (ข้อ 8) แล้วค่อยไล่แก้

## 10. Teardown (ลบทุกอย่างเพื่อไม่ให้เสียเงิน)

```bash
sam delete --stack-name pai-nhai-dee-wa-dev --region ap-southeast-1      # ลบ Lambda, คิว, ตาราง, alarm, budget, log group
for n in line-channel-secret line-channel-access-token gemini-api-key google-places-api-key; do
  aws ssm delete-parameter --name $P/$n
done
```
แล้วทำมือต่อ: (1) LINE Console ลบ Webhook URL / ปิด Use webhook (2) Google Cloud: ลบ/rotate API key ทั้งสองตัว (3) ลบ bucket ที่ SAM จัดการให้: CloudFormation > stack `aws-sam-cli-managed-default` > ลบ bucket ให้ว่างก่อนแล้ว Delete stack (4) IAM: ลบ access key ของ `pai-deployer` ถ้าไม่ใช้แล้ว
ตรวจ: `aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE` ไม่ควรเหลือ `pai-nhai-dee-wa-*`

---

## แก้ปัญหา

| อาการ | สาเหตุที่พบบ่อย | วิธีแก้ |
|---|---|---|
| `sam build` บอกหา python3.12 ไม่เจอ | ไม่ได้ติดตั้ง/ไม่อยู่ใน PATH | `brew install python@3.12` แล้วเปิด terminal ใหม่ หรือใช้ `sam build --use-container` (ต้องมี Docker) |
| deploy ล้ม: "decreases account's UnreservedConcurrentExecution below its minimum" | โควตา Lambda ต่ำ (ข้อ 1.7) | ใส่ `WebhookReservedConcurrency=-1 WorkerReservedConcurrency=-1` หรือขอเพิ่มโควตา |
| LINE Verify ขึ้น error / 401 | secret ใน SSM ไม่ตรงกับ channel (คนละ channel? เว้นวรรคเกิน?) | ใส่ใหม่ด้วย `put-parameter --overwrite` แล้วบังคับให้ Lambda โหลดใหม่ (มัน cache secret ไว้ตอน cold start): `F=$(aws cloudformation describe-stack-resource --stack-name pai-nhai-dee-wa-dev --logical-resource-id WebhookFunction --query StackResourceDetail.PhysicalResourceId --output text); aws lambda update-function-configuration --function-name $F --description "reload $(date +%s)"` (ทำกับ `WorkerFunction` ด้วยถ้าเปลี่ยน token/key) แล้วรัน smoke ใหม่ |
| LINE Verify ขึ้น 403 / timeout | URL ผิด หรือ Function URL ไม่เปิดสาธารณะ | เทียบ `$URL` กับ Outputs; `curl -i $URL` ต้องได้ 401 (ไม่ใช่ 403) |
| เชิญบอทเข้ากลุ่มไม่ได้ | ยังไม่เปิด Allow bot to join group chats | ข้อ 6.3 |
| บอทเงียบในกลุ่ม | ไม่ได้กด mention จริง / ปิด webhook / `BotEnabled=false` / ลืมปิด Auto-response | ไล่ดูข้อ 6.1-6.2, `sam logs --tail` ดู `webhook events=... queued=...` |
| บอทตอบแต่ตอน @ ไม่อ่านแชต | `GeminiPaidTierConfirmed=false` (ตั้งใจ) | ข้อ 7 เมื่อ paid tier จริง |
| ตอบช้า/ไม่ตอบ + DLQ alarm เมล | worker ล้ม 3 ครั้ง (key ผิด, โควตา Google หมด, reply token หมดอายุ) | `sam logs` ดู `event failed: <ชื่อ error>`; แก้แล้ว event เก่าใน DLQ ไม่ควร redrive (reply token หมดอายุแล้ว) ให้ purge |
| ไม่ได้เมล alarm | ยังไม่กด Confirm subscription ของ SNS | เปิดเมล AWS Notifications แล้วกด Confirm (เช็ก spam) |
