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
| **วิชั่น** | `ctx.vision.find_template("ปุ่ม.png", 0.85)` → `(x,y,score)`/`None` · `ctx.vision.tap_template("ปุ่ม.png")` |
| **AI** | `ctx.ai` → ทะเบียนโมเดล (ดูด้านล่าง) |
| **ทั่วไป** | `ctx.log("...")` · `ctx.sleep(วินาที)` (ขัดจังหวะได้) · `ctx.should_stop()` · `ctx.config[...]` · `ctx.save()` |

## วิชั่น / AI (เผื่ออนาคต)

- **Template matching** ใช้ได้เลยถ้าติดตั้ง `opencv-python` + `numpy`:
  ```bash
  pip install opencv-python numpy
  ```
- **โมเดล AI** (object detection / OCR / LLM): ลงทะเบียนผ่าน `ctx.ai`
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

## ข้อควรระวัง
- บอทรันในเธรดแยก — **ห้ามแตะ UI ของ Qt โดยตรง** ใช้ `ctx.log()` ส่งข้อความแทน
- ออกจากลูปเมื่อ `ctx.should_stop()` เป็นจริง ไม่งั้นปุ่ม “หยุด” จะรอจนกว่าจะจบรอบ
- ปลั๊กอินคือโค้ดที่รันด้วยสิทธิ์เต็ม — ใช้เฉพาะจากแหล่งที่เชื่อถือได้

ดูตัวอย่างเต็มได้ที่ **`example_autotap.py`**
