"""
ตัวอย่างปลั๊กอินบอท: Auto Tapper
================================
แตะหน้าจอตำแหน่งกึ่งกลาง ซ้ำ ๆ ตามรอบเวลาที่ตั้งไว้

ใช้เป็น "แม่แบบ" สำหรับเขียนบอทเกมของคุณเอง:
  1. คัดลอกไฟล์นี้
  2. แก้ตรรกะในเมธอด run()
  3. วางไว้ในโฟลเดอร์ plugins/ แล้วกด "โหลดปลั๊กอินใหม่" ในแอป

ความสามารถที่เรียกได้จาก ctx:
  ctx.tap(x, y) / ctx.swipe(...) / ctx.key("KEYCODE_BACK") / ctx.text("hello")
  ctx.screencap_png() / ctx.screencap_pil() / ctx.screencap_np()
  ctx.screen_size() -> (w, h)
  ctx.vision.find_template("ปุ่ม.png")  / ctx.vision.tap_template("ปุ่ม.png")
  ctx.ai  -> ทะเบียนโมเดล AI (เผื่ออนาคต)
  ctx.config["..."]  -> ตั้งค่าที่ถูกบันทึกอัตโนมัติ
  ctx.log("...") / ctx.sleep(วินาที) / ctx.should_stop()
"""
from plugin_api import BotPlugin, PluginMeta


class AutoTapper(BotPlugin):
    meta = PluginMeta(
        name="Auto Tapper (ตัวอย่าง)",
        version="1.0",
        author="ScreenCast Studio",
        description="แตะกลางจอซ้ำ ๆ ทุก N วินาที — แม่แบบสำหรับเขียนบอทเกม",
    )

    def on_load(self, ctx):
        # ตั้งค่าเริ่มต้น (จะถูกบันทึกไว้ใน settings.json)
        ctx.config.setdefault("interval_sec", 1.0)
        ctx.config.setdefault("max_taps", 0)   # 0 = ไม่จำกัด

    def run(self, ctx):
        w, h = ctx.screen_size()
        if not (w and h):
            ctx.log("อ่านขนาดหน้าจอไม่ได้ — หยุด")
            return
        cx, cy = w // 2, h // 2
        interval = float(ctx.config.get("interval_sec", 1.0))
        max_taps = int(ctx.config.get("max_taps", 0))
        ctx.log(f"จอ {w}x{h} — แตะที่ ({cx},{cy}) ทุก {interval}s")

        count = 0
        while not ctx.should_stop():
            ctx.tap(cx, cy)
            count += 1
            ctx.log(f"แตะครั้งที่ {count}")
            if max_taps and count >= max_taps:
                ctx.log("ครบจำนวนที่ตั้งไว้ — หยุด")
                break
            ctx.sleep(interval)
