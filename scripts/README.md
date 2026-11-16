# scripts/ : เครื่องมือ dev และ ops (ไม่ถูกแพ็กเข้า Lambda)

## หน้าที่
| ไฟล์ | ใช้ทำอะไร | เรียกด้วย |
|---|---|---|
| `simulate.py` | เล่นบทสนทนาหลายคนใน terminal ด้วย engine จริง + ของปลอม (`--interactive`, `--script`, `--live` ใช้ API จริง) | `make simulate`, `make simulate-pg` |
| `scenarios/ari_buffet.txt` | บทสนทนาตัวอย่างของ simulator (`A: ข้อความ` หรือ `B: [ตกลง]`) | `--script` |
| `local_server.py` | HTTP server `/callback` รับ webhook LINE จริงผ่าน ngrok ไม่ต้องมี AWS (รัน engine แบบ synchronous) | `make local` |
| `events.py` | สร้าง LINE event ปลอม (`text_event`, `postback_event`, `join_event`, `sticker_event`) **ใช้ร่วมกับเทสต์** | import |
| `render.py` | แปลง LINE message (flex/text) เป็นข้อความอ่านง่ายใน terminal | import |
| `eval_intents.py` | วัดความแม่นของการสกัด intent บน `tests/eval/utterances.jsonl` (`--live` Gemini, `--places`) | `python -m scripts.eval_intents` |
| `smoke.py` | smoke test หลัง deploy: ยิง webhook ที่ `events=[]` 3 แบบ (signature ถูก 200, ผิด 401, ไม่มี 401) ไม่เรียก LINE/Gemini/Places | `python -m scripts.smoke --url ... --secret-ssm ...` |
| `local_pg.sh` | เริ่ม/หยุด/ล้าง Postgres 16 ในเครื่องโดยไม่ใช้ Docker (พอร์ต 54329) | `make pg-up/pg-down/pg-reset` |

## Public interface (ที่เทสต์/โมดูลอื่นพึ่งพา)
- `scripts.events.*_event(...)` รูปแบบ event เหมือน LINE จริง (`webhookEventId`, `replyToken`, `source`)
- `scripts.local_server.run_event(engine, ev)` -> `bool` (จับ exception แล้ว log แค่ชื่อชนิด)
- `scripts.smoke.sign(secret, body)`, `post(...)`, `main(argv) -> exit code` (0 ผ่าน, 1 มีข้อที่ไม่ผ่าน, 2 argument ผิด)
- `scripts.eval_intents`: **exit code เป็น 0 เสมอ** แม้ accuracy ต่ำ; ใน CI ตรวจเกณฑ์จากข้อความ output (`regression.yml`)

## Data flow
simulate/local_server -> `wiring.build_engine(settings)` -> `SessionEngine.handle(event)` (เส้นทางเดียวกับ worker บน AWS)

## Invariants
1. สคริปต์ **ไม่เปลี่ยนพฤติกรรมของ engine** แค่ขับมัน
2. `smoke.py` ไม่ส่ง event จริง (ไม่ทำให้ worker ถูกเรียก) และไม่พิมพ์ secret
3. `simulate` เริ่มจากฐานข้อมูลว่างเสมอเมื่อใช้ Postgres (`store.reset()`) ห้ามชี้ไปฐานจริง
4. `--live` / `--places` เสียเงินจริง ใช้ด้วยมือเท่านั้น ห้ามใส่ใน CI
5. `local_server` ไม่ log ข้อความ (log แค่ชนิด event และชื่อ exception)

## How to extend
- **บทสนทนาใหม่**: เขียนไฟล์ `.txt` แล้ว `python -m scripts.simulate --script ไฟล์.txt` (ถ้าต้องการให้เป็น regression ถาวร ให้เขียนเป็น YAML scenario ใน `tests/sandbox/scenarios/` แทน)
- **utterance ใหม่ใน eval**: เพิ่มบรรทัด JSONL ใน `tests/eval/utterances.jsonl` (เช็กเฉพาะ label ที่ใส่)
- **สคริปต์ใหม่**: ไฟล์ `scripts/<name>.py` ที่มี `main(argv=None) -> int` และเรียกผ่าน `python -m scripts.<name>` อย่าเขียน logic ที่ควรเทสต์ไว้ใน `if __name__`; เพิ่ม target ใน Makefile ถ้าใช้บ่อย

## เทสต์ที่ครอบ
`events.py` และ `render.py` ถูกใช้ในเทสต์เกือบทั้งหมด · `local_server.run_event` ถูกเรียกในบางเทสต์ integration ·
`simulate.py`, `smoke.py`, `eval_intents.py` ยัง **ไม่มี unit test ของตัวเอง** (coverage 0% และไม่นับใน gate; `smoke.py` ถูกรันจริงหลัง deploy เท่านั้น,
`eval_intents` รันใน nightly) เป็นช่องว่างที่ยอมรับได้ชั่วคราว
