# สภาพแวดล้อม: LOCAL (Postgres) vs AWS

มี 2 สภาพแวดล้อม โค้ดธุรกิจ (`session/`, `features/`, `adapters/`) ชุดเดียวกัน ต่างกันแค่ **Store** และ **ตัวรับ event**

| | LOCAL (ใช้ตอนนี้) | AWS (deploy พรุ่งนี้) |
|---|---|---|
| ตัวรับ webhook | `scripts/local_server.py` (+ ngrok) หรือ `make simulate` | Lambda Function URL -> SQS -> Lambda worker |
| Store | `STORE=postgres` (หรือ `memory`) | `STORE=dynamo` (DynamoDB, TTL attribute `ttl`) |
| ค่าใช้จ่าย | 0 บาท | ตาม usage (คุมด้วย budget ใน template.yaml) |
| Secret | `.env` | SSM Parameter Store |
| LLM / Places / LINE | `fake` เป็นค่าเริ่มต้น เปลี่ยนเป็นของจริงได้ใน `.env` | เหมือนกัน (ผ่าน SSM) |

## เริ่ม Postgres ในเครื่อง

macOS มี docker:
```bash
docker compose up -d          # postgres:16 พอร์ต 54329
```
ไม่มี docker (หรือ sandbox/Linux): `make pg-up` (เรียก `scripts/local_pg.sh start` ใช้ binary ของ Postgres ที่ติดตั้งไว้, macOS: `brew install postgresql@16`)

```bash
make pg-up        # start
make pg-down      # stop
make pg-reset     # ล้างฐานข้อมูลทั้งหมด
make test-pg      # เทสต์ทั้งชุดบน Postgres
make simulate-pg  # เล่นบทสนทนาจำลองบน Postgres
```
URL เริ่มต้น `postgresql://pnd:pnd@localhost:54329/pnd` (เปลี่ยนด้วย `DATABASE_URL`) ตารางสร้างเองอัตโนมัติ (`store/schema.sql`, รันซ้ำได้)

## วิธีสลับ

ตั้งใน `.env` หรือหน้าคำสั่ง (`STORE_PROVIDER` แบบเดิมยังใช้ได้ ที่ AWS template ใช้อยู่):

```bash
STORE=memory   make test        # เร็วสุด ไม่เก็บถาวร
STORE=postgres make simulate    # เก็บถาวรในเครื่อง
STORE=postgres make local       # เซิร์ฟเวอร์ LINE ผ่าน ngrok + Postgres
STORE=dynamo   TABLE_NAME=...   # เฉพาะบน AWS
```

## TTL เทียบกับ DynamoDB

- ทุกแถวมี `expires_at` (epoch วินาที) เหมือน attribute `ttl`
- `seen_event`: event หมดอายุ 24 ชม. แล้วอ้างสิทธิ์ใหม่ได้ (เงื่อนไขเดียวกับ `attribute_not_exists OR ttl < now`)
- `incr`: `INSERT ... ON CONFLICT DO UPDATE` เป็น atomic, TTL ตั้งตอนนับครั้งแรก (เหมือน `if_not_exists`)
- DynamoDB ลบแถวหมดอายุเองเบื้องหลัง; Postgres ลบทุก 200 ครั้งที่เขียน หรือเรียก `purge_expired(now)` เอง
- `get_session` ไม่ซ่อน session ที่หมดอายุแต่ยังไม่ถูกลบ (เหมือน DynamoDB) engine เช็ก `is_expired` เอง

## อะไรพิสูจน์ที่ไหน

| เรื่อง | memory | Postgres (local) | moto | AWS จริง |
|---|---|---|---|---|
| ลอจิก session / ack / caps / LLM rules | พิสูจน์ | พิสูจน์ (`make test-pg`) | - | - |
| Store contract (dedup, forget, session, counter, TTL ด้วย `now` ที่ฉีด) | พิสูจน์ | พิสูจน์ | พิสูจน์ | - |
| `incr` / `seen_event` atomic ภายใต้ thread | พิสูจน์ | พิสูจน์ | ไม่ได้ (moto ไม่ thread-safe) | ต้องดูบน AWS |
| Worker handler + DynamoStore | - | - | พิสูจน์ | smoke test หลัง deploy |
| IAM permission (Lambda -> DynamoDB/SQS/SSM) | - | - | - | **AWS เท่านั้น** |
| SQS redrive / DLQ / visibility timeout / retry | - | - | จำลองบางส่วน | **AWS เท่านั้น** |
| Lambda Function URL + การตรวจ LINE signature ผ่านเครือข่ายจริง | - | - | - | **AWS เท่านั้น** |
| Cold start / timeout / memory ของ Lambda | - | - | - | **AWS เท่านั้น** |
| DynamoDB TTL ลบจริง (ช้าได้ถึงหลายชม.) | - | purge จำลอง | - | **AWS เท่านั้น** |
| ค่าใช้จ่าย / budget alarm | - | - | - | **AWS เท่านั้น** |

## ข้อควรรู้

- `tests/contract/test_store_contract.py` รันกับ 3 store; ถ้า Postgres ไม่ขึ้น เทสต์ของ Postgres จะ skip พร้อมข้อความ `run make pg-up first`
- `psycopg` อยู่ใน `requirements-dev.txt` เท่านั้น ไม่ถูกแพ็กเข้า Lambda
