"""
ปลั๊กอิน: Macro Player (เล่นแมโคร)
===================================
เล่นชุด "การกระทำ" (actions) ที่กำหนดไว้ใน config ซ้ำตามต้องการ —
เหมาะกับงานทำซ้ำเป็นขั้นตอน เช่น เก็บเดลี่ในเกม, กดเมนูตามลำดับ

ตั้งค่าผ่าน ctx.config (บันทึกลง settings.json อัตโนมัติ) — แก้ได้ในไฟล์นั้นเลย
หรือสร้าง provider/แผงตั้งค่าต่อยอดภายหลัง

รูปแบบ config:
    {
      "actions": [
        {"type": "tap",          "x": 540, "y": 1200},
        {"type": "swipe",        "x1": 540, "y1": 1600, "x2": 540, "y2": 600, "duration_ms": 300},
        {"type": "key",          "code": "KEYCODE_BACK"},
        {"type": "text",         "text": "hello world"},
        {"type": "sleep",        "seconds": 1.5},
        {"type": "wait_template","template": "ปุ่มเริ่ม.png", "threshold": 0.85, "timeout": 10},
        {"type": "tap_template", "template": "ปุ่มเริ่ม.png", "threshold": 0.85, "optional": true}
      ],
      "loop": true,          // วนซ้ำทั้งชุดไหม
      "loop_count": 0,       // จำนวนรอบ (0 = ไม่จำกัด เมื่อ loop=true)
      "loop_delay_sec": 1.0, // หน่วงระหว่างรอบ
      "step_delay_sec": 0.3  // หน่วงระหว่างแต่ละ action
    }

หมายเหตุ: action ชนิด *_template ต้องติดตั้ง opencv-python + numpy
ใส่ "optional": true เพื่อให้ "ข้าม" เมื่อหา template ไม่เจอ (แทนที่จะหยุด)
"""
from plugin_api import BotPlugin, PluginMeta

# ตัวอย่างเริ่มต้น: แตะกลางจอ 1 ที แล้วรอ 1 วิ (ผู้ใช้แก้ทับใน settings.json ได้)
_DEFAULT_ACTIONS = [
    {"type": "tap", "x": 540, "y": 1200},
    {"type": "sleep", "seconds": 1.0},
]


class MacroPlayer(BotPlugin):
    meta = PluginMeta(
        name="Macro Player (เล่นแมโคร)",
        version="1.0",
        author="ScreenCast Studio",
        description="เล่นชุดการกระทำตามที่ตั้งใน config — แตะ/ปัด/ปุ่ม/พิมพ์/รอ template",
        requires={"vision"},
    )

    def on_load(self, ctx):
        ctx.config.setdefault("actions", _DEFAULT_ACTIONS)
        ctx.config.setdefault("loop", True)
        ctx.config.setdefault("loop_count", 0)
        ctx.config.setdefault("loop_delay_sec", 1.0)
        ctx.config.setdefault("step_delay_sec", 0.3)

    def run(self, ctx):
        actions = ctx.config.get("actions") or []
        if not actions:
            ctx.log("ยังไม่มี actions ใน config — เปิด settings.json แล้วเพิ่มขั้นตอน")
            return

        loop = bool(ctx.config.get("loop", True))
        loop_count = int(ctx.config.get("loop_count", 0))
        loop_delay = float(ctx.config.get("loop_delay_sec", 1.0))
        step_delay = float(ctx.config.get("step_delay_sec", 0.3))

        ctx.log(f"เริ่มเล่นแมโคร {len(actions)} ขั้นตอน "
                f"({'วนซ้ำ' if loop else 'รอบเดียว'})")

        rounds = 0
        while not ctx.should_stop():
            for i, act in enumerate(actions, 1):
                if ctx.should_stop():
                    return
                if not self._do_action(ctx, act, i):
                    return   # action บังคับล้มเหลว — หยุดทั้งแมโคร
                ctx.sleep(step_delay)

            rounds += 1
            if not loop:
                break
            if loop_count and rounds >= loop_count:
                ctx.log(f"ครบ {loop_count} รอบ — หยุด")
                break
            ctx.sleep(loop_delay)

        ctx.log(f"จบแมโคร (เล่นไป {rounds} รอบ)")

    # ----------------------------------------------------------------- actions
    def _do_action(self, ctx, act: dict, idx: int) -> bool:
        """ทำ action หนึ่งขั้น — คืน False ถ้าควรหยุดแมโคร (ล้มเหลวแบบไม่ optional)"""
        kind = str(act.get("type", "")).lower()
        optional = bool(act.get("optional", False))
        try:
            if kind == "tap":
                ctx.tap(int(act["x"]), int(act["y"]))
            elif kind == "swipe":
                ctx.swipe(int(act["x1"]), int(act["y1"]),
                          int(act["x2"]), int(act["y2"]),
                          int(act.get("duration_ms", 200)))
            elif kind == "key":
                ctx.key(act.get("code", act.get("keycode", "KEYCODE_BACK")))
            elif kind == "text":
                ctx.text(str(act.get("text", "")))
            elif kind == "sleep":
                ctx.sleep(float(act.get("seconds", 1.0)))
            elif kind == "wait_template":
                hit = ctx.vision.wait_for_template(
                    act["template"], float(act.get("threshold", 0.85)),
                    float(act.get("timeout", 10.0)))
                if hit is None:
                    return self._miss(ctx, idx, f"รอ {act['template']} ไม่เจอ", optional)
            elif kind == "tap_template":
                ok = ctx.vision.tap_template(
                    act["template"], float(act.get("threshold", 0.85)))
                if not ok:
                    return self._miss(ctx, idx, f"หา {act['template']} ไม่เจอ", optional)
            else:
                ctx.log(f"ขั้นที่ {idx}: ไม่รู้จัก action '{kind}' — ข้าม")
        except KeyError as e:
            ctx.log(f"ขั้นที่ {idx}: ขาดค่า {e} ใน action — ข้าม")
            # ผิดรูปแบบถือว่าข้ามได้ ไม่ล้มทั้งแมโคร (เล่นขั้นถัดไปต่อ)
        return True

    @staticmethod
    def _miss(ctx, idx: int, msg: str, optional: bool) -> bool:
        if optional:
            ctx.log(f"ขั้นที่ {idx}: {msg} (optional) — ข้าม")
            return True
        ctx.log(f"ขั้นที่ {idx}: {msg} — หยุดแมโคร")
        return False
