# 🤖 คู่มือเขียนปลั๊กอินบอท — ScreenCast Studio

วางไฟล์ `.py` (หรือโฟลเดอร์ที่มี `__init__.py`) ไว้ในโฟลเดอร์ **`plugins/`** นี้
แล้วกด **“🔄 โหลดปลั๊กอินใหม่”** ในแท็บ 🤖 บอท — แอปจะค้นเจอและแสดงให้รันได้ทันที

## โครงสร้างขั้นต่ำ

```python
from plugin_api import BotPlugin, PluginMeta

class MyBot(BotPlugin):
    meta = PluginMeta(
        name="ชื่อบอท",
        version="1.0",
        author="คุณ",
        description="บอททำอะไร",
    )

    def on_load(self, ctx):
        ctx.config.setdefault("delay", 1.0)   # ตั้งค่าเริ่มต้น (บันทึกอัตโนมัติ)

    def run(self, ctx):
        while not ctx.should_stop():           # ⚠️ ต้องเช็ก should_stop() เสมอ
            ctx.tap(500, 1000)
            ctx.sleep(ctx.config["delay"])
```

## สิ่งที่เรียกได้จาก `ctx` (BotContext)

| กลุ่ม | คำสั่ง |
|------|--------|
| **ควบคุม** | `ctx.tap(x,y)` · `ctx.swipe(x1,y1,x2,y2,duration_ms)` · `ctx.key("KEYCODE_BACK")` · `ctx.text("hi")` · `ctx.back()` · `ctx.home()` |
| **จับภาพ** | `ctx.screencap_png()` (bytes) · `ctx.screencap_pil()` (PIL) · `ctx.screencap_np()` (numpy BGR) |
| **ข้อมูล** | `ctx.screen_size()` → `(w,h)` · `ctx.device_model()` |
| **วิชั่น** | `ctx.vision.find_template("ปุ่ม.png", 0.85)` → `(x,y,score)`/`None` · `ctx.vision.find_all_templates("ไอเทม.png")` → `[(x,y,score), …]` · `ctx.vision.wait_for_template("ปุ่ม.png", timeout=10)` → รอจนเจอ · `ctx.vision.tap_template("ปุ่ม.png")` |
| **AI** | `ctx.ai` → ทะเบียนโมเดล · `ctx.ai.get("ocr")` → อ่านตัวอักษร (ดูด้านล่าง) |
| **ทั่วไป** | `ctx.log("...")` · `ctx.sleep(วินาที)` (ขัดจังหวะได้) · `ctx.should_stop()` · `ctx.config[...]` · `ctx.save()` |

## วิชั่น / AI

- **Template matching** ใช้ได้เลยถ้าติดตั้ง `opencv-python` + `numpy`:
  ```bash
  pip install opencv-python numpy
  ```
  ```python
  hit = ctx.vision.find_template("ปุ่ม.png")          # จุดเดียวที่ดีที่สุด
  for x, y, score in ctx.vision.find_all_templates("เหรียญ.png"):
      ctx.tap(x, y)                                     # แตะทุกเหรียญที่เจอ
  hit = ctx.vision.wait_for_template("โหลดเสร็จ.png", timeout=15)  # รอจนโผล่
  ```
  > 💡 จับภาพหน้าจอมีแคชสั้น ๆ (~150ms) — หา template หลายรูปติดกันจะยิง adb ครั้งเดียว
  > และแคชจะถูกล้างทันทีหลังสั่ง `tap/swipe/key/text` (ภาพไม่ค้าง)

- **OCR (อ่านตัวอักษร)** — มากับแอป ลงทะเบียนชื่อ `"ocr"` ให้แล้ว:
  ```python
  text = ctx.ai.get("ocr").infer(ctx.screencap_pil())          # อ่านทั้งจอ (eng)
  text = ctx.ai.get("ocr").infer(ctx.screencap_pil(), lang="tha+eng")
  ```
  ต้องติดตั้งก่อนใช้จริง: `pip install pytesseract` + โปรแกรม Tesseract-OCR
  (ถ้ายังไม่ได้ติดตั้ง จะแจ้ง error พร้อมวิธีติดตั้ง — แอปไม่ล่ม)

- **โมเดล AI ของตัวเอง** (object detection / LLM): ลงทะเบียนผ่าน `ctx.ai`
  ```python
  from plugin_api import AIProvider

  class MyDetector(AIProvider):
      name = "yolo"
      def infer(self, frame=None, prompt="", **kw):
          ...  # คืนผลตรวจจับ

  # ลงทะเบียนครั้งเดียว (เช่นใน on_load):
  if "yolo" not in ctx.ai:
      ctx.ai.register(MyDetector())

  # ปลั๊กอินตัวไหนก็เรียกใช้ร่วมกันได้:
  result = ctx.ai.get("yolo").infer(ctx.screencap_np())
  ```

## เล่นแมโครจาก config (ไม่ต้องเขียนโค้ด)

ปลั๊กอิน **`macro_recorder.py`** เล่นชุดการกระทำตามที่ตั้งใน `ctx.config["actions"]`
รองรับ `tap / swipe / key / text / sleep / wait_template / tap_template` —
แก้ลำดับขั้นได้ใน `settings.json` ใต้คีย์ `plugins` โดยไม่ต้องเขียนปลั๊กอินใหม่
(ดูรูปแบบเต็มในหัวไฟล์ `macro_recorder.py`)

## คุมมือถือจากภายนอกผ่าน REST API

เปิดได้ที่ **แท็บ ⚙️ ตั้งค่า → 🌐 REST API** (ผูกกับ `localhost` เท่านั้น) แล้วสั่งจากสคริปต์:
```bash
curl http://127.0.0.1:8770/status
curl -X POST http://127.0.0.1:8770/tap  -d '{"x":540,"y":1200}'
curl http://127.0.0.1:8770/screenshot -o shot.png
```
เอ็นด์พอยต์: `/status /devices /screenshot /tap /swipe /key /text /plugins`
(รายละเอียดในหัวไฟล์ `bot_http_api.py`)

## ข้อควรระวัง
- บอทรันในเธรดแยก — **ห้ามแตะ UI ของ Qt โดยตรง** ใช้ `ctx.log()` ส่งข้อความแทน
- ออกจากลูปเมื่อ `ctx.should_stop()` เป็นจริง ไม่งั้นปุ่ม “หยุด” จะรอจนกว่าจะจบรอบ
- ปลั๊กอินคือโค้ดที่รันด้วยสิทธิ์เต็ม — ใช้เฉพาะจากแหล่งที่เชื่อถือได้

ดูตัวอย่างเต็มได้ที่ **`example_autotap.py`**
