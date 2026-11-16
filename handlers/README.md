# handlers/ : Lambda entry points (AWS)

## หน้าที่
ชั้นบางๆ ระหว่าง AWS กับ `SessionEngine` ไม่มีลอจิกของ product ที่นี่

| ไฟล์ | Lambda | ทำอะไร |
|---|---|---|
| `webhook.py` | `WebhookFunction` (Function URL, timeout 5 วิ) | ตรวจ `x-line-signature` -> กรองข้อความขยะด้วย prefilter -> ส่ง SQS FIFO (`MessageGroupId`=groupId, dedup=`webhookEventId`) -> ตอบ 200 |
| `worker.py` | `WorkerFunction` (SQS, BatchSize 1, timeout 30 วิ) | `asyncio.run(engine.handle(event))` ต่อ record แล้วคืน `batchItemFailures` |
| `ssm.py` | - | `settings_from_ssm(only=...)` อ่าน secret จาก SSM ตอน cold start แบบ least privilege |

## Public interface
```python
# webhook.py
handler(request, ctx) -> {"statusCode": 200|400|401|413, "body": ...}
process(body: bytes, signature: str|None, secret: str, send) -> dict    # แกนที่เทสต์ได้ (send = callback ส่ง SQS)
should_enqueue(event) -> bool;  parse_body(request) -> bytes
# worker.py
handler(sqs_event, ctx) -> {"batchItemFailures": [{"itemIdentifier": messageId}, ...]}
# ssm.py
settings_from_ssm(only: tuple[str, ...] | None) -> Settings
```

## Data flow
```
LINE -> Function URL -> webhook.handler -> process(): len > 256 KB (413) -> verify_signature (401) -> json events (JSON เสีย = 400)
   -> should_enqueue (join/leave/memberLeft/postback; text ที่ @บอท หรือ worth_reading) -> send(SQS) -> 200
SQS -> worker.handler -> engine.handle (idempotent via seen_event) -> LINE reply
   ล้มเหลว -> itemIdentifier ใน batchItemFailures -> SQS ส่งซ้ำ (visibility timeout 180 วิ)
   ครบ maxReceiveCount=3 -> DLQ (14 วัน) + CloudWatch alarm
```

## Invariants
1. body เกิน 256 KB = 413 (ก่อน HMAC/parse); ตรวจ signature **ก่อน** parse JSON ใดๆ; signature ผิด/ไม่มี/secret ว่าง = 401 และไม่ส่ง SQS; signature ถูกแต่ JSON เสีย/รูปทรงผิด = 400 (ไม่ raise ไม่ retry)
2. ถ้าส่ง SQS ล้มเหลว **ต้องไม่ตอบ 200** (exception ทะลุ) เพื่อให้ LINE ส่ง webhook ซ้ำ
3. `events: []` (ปุ่ม Verify ของ LINE และ `scripts/smoke.py`) = 200 และไม่ส่งอะไรเลย
4. ไม่ log ข้อความแชต; worker log เฉพาะชื่อชนิด exception (`type(exc).__name__`)
5. worker ประมวลผลต่อไปแม้ record หนึ่งล้ม แล้วรายงานเฉพาะตัวที่ล้ม (partial batch response)
6. webhook อ่าน SSM ได้เฉพาะ `LINE_CHANNEL_SECRET_PARAM`; worker ได้เฉพาะ 3 ตัวที่เหลือ (ตรงกับ IAM ใน `template.yaml`)
7. `BOT_ENABLED=false` = engine คืนเงียบ -> worker ack (ไม่ retry) คิวจึงไม่ค้าง
8. ตัวแปร global (`_secret`, `_sqs`, `_engine`) สร้างตอน cold start ครั้งเดียว (เทสต์ใช้ `monkeypatch`)

## ข้อสังเกตที่รู้แล้ว (ไม่ใช่บั๊กที่ block)
- dedup id สำรอง (ไม่มี `webhookEventId`) = sha256 ของ canonical JSON (คงที่ข้าม process; เทส `test_fallback_dedup_id_is_stable_across_processes`)
- ถ้าเพิ่ม `BatchSize` > 1 ใน template: worker ประมวลผลต่อหลัง record ล้ม ซึ่งอาจทำลายลำดับต่อกลุ่มของ FIFO
  (ตอนนี้ BatchSize=1 จึงไม่กระทบ) ถ้าจะเพิ่มต้องหยุดที่ตัวแรกที่ล้มแล้วคืนตัวที่เหลือด้วย
- **ไม่มี EventBridge / scheduled / cleanup job**: การลบข้อมูลหมดอายุอาศัย DynamoDB TTL (ไม่มี Lambda ตั้งเวลา)

## How to extend
- **event type ใหม่จาก LINE**: เพิ่มใน `should_enqueue` (ต้องไม่ส่งของที่ไม่ใช้ เพื่อไม่เสียค่า SQS/Lambda) แล้วจัดการใน `SessionEngine._dispatch` + เทสต์ในตาราง `test_should_enqueue_table`
- **secret ใหม่**: เพิ่มใน `ssm._SECRETS`, `template.yaml` (env `*_PARAM` + IAM resource ของ Lambda ที่ต้องใช้เท่านั้น), `.env.example`
- **Lambda/job ตามเวลาใหม่**: เพิ่ม function ใน `template.yaml` (Events: Schedule), ไฟล์ `handlers/<name>.py` ที่เป็น `handler(event, ctx)` บางๆ เรียกฟังก์ชันที่เทสต์ได้, และเทสต์ใน `tests/unit/`

## เทสต์ที่ครอบ
| ไฟล์ | ครอบ |
|---|---|
| `tests/unit/test_webhook_handler.py` | signature (fail closed), empty events, noise, group id, dedup id, ขนาดใหญ่, envelope Function URL (base64, header case), SQS fan-out/ล้ม, least-privilege SSM |
| `tests/unit/test_worker_handler.py` | batch ว่าง/สำเร็จ/partial failure/ทั้งหมดล้ม, body เสีย, log ไม่รั่ว, retry ได้ครั้งเดียว, duplicate, kill switch, จำลอง redrive -> DLQ, lazy engine |
| `tests/integration/test_webhook.py` | `process` กับ event จริงของ `scripts/events.py` |
| `tests/integration/test_aws.py` | worker + DynamoStore ผ่าน moto |
| `scripts/smoke.py` | หลัง deploy: 200/401 บน Function URL จริง |
| **พิสูจน์ได้เฉพาะบน AWS** | SQS redrive/DLQ จริง, visibility timeout, IAM, cold start, timeout |
