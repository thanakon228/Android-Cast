"""
plugin_api.py
=============
สัญญา (contract) สำหรับเขียนปลั๊กอินบอท ของ ScreenCast Studio

แนวคิด:
  - ปลั๊กอิน = คลาสที่สืบทอดจาก `BotPlugin` แล้ววางไฟล์ไว้ในโฟลเดอร์ `plugins/`
  - แอปจะค้นเจอ โหลด และให้ "BotContext" เป็นสะพานคุมมือถือ/จับภาพ/เรียก AI
  - ไม่ผูกกับ PyQt → เขียนบอท/รันแบบ headless หรือเทสต์แยกได้

โครงสร้างชั้น (layer):
  BotPlugin (โค้ดของผู้ใช้)
      │ ใช้ผ่าน
      ▼
  BotContext  ── capture (จับภาพ) ─┐
              ── input  (แตะ/ปัด)  ─┼─► ScrcpyManager ► adb ► มือถือ
              ── vision (หา template)┘
              ── ai     (registry โมเดล AI — เผื่ออนาคต)

ความปลอดภัย: ปลั๊กอินคือโค้ด Python ที่รันด้วยสิทธิ์เต็ม — ติดตั้งเฉพาะจากแหล่งที่เชื่อถือได้
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# ข้อมูลประจำตัวปลั๊กอิน
# ---------------------------------------------------------------------------
@dataclass
class PluginMeta:
    name: str
    version: str = "1.0"
    author: str = ""
    description: str = ""
    # ความสามารถที่ต้องใช้ (ไว้เตือนผู้ใช้ก่อนรัน) เช่น {"vision", "ai"}
    requires: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# ตัวช่วยด้านวิชั่น (computer vision) — โหลด cv2/numpy แบบ lazy (เป็นออปชัน)
# ---------------------------------------------------------------------------
class Vision:
    """หา/เทียบรูปบนหน้าจอ — รากฐานของบอทเกมและงาน AI"""

    def __init__(self, ctx: "BotContext"):
        self.ctx = ctx

    @staticmethod
    def _cv():
        try:
            import cv2  # noqa: F401
            import numpy as np  # noqa: F401
            return cv2, np
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "ฟีเจอร์ vision ต้องติดตั้ง opencv-python + numpy ก่อน "
                "(pip install opencv-python numpy)"
            ) from e

    def find_template(self, template, threshold: float = 0.85):
        """
        หา template (path รูป หรือ ndarray) บนหน้าจอปัจจุบัน
        คืน (x, y, score) = จุดกึ่งกลางที่เจอ + ความมั่นใจ, หรือ None ถ้าไม่เจอ
        """
        cv2, np = self._cv()
        screen = self.ctx.screencap_np()
        tmpl = cv2.imread(template) if isinstance(template, str) else template
        if tmpl is None:
            raise FileNotFoundError(f"เปิดไฟล์ template ไม่ได้: {template}")
        res = cv2.matchTemplate(screen, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= threshold:
            h, w = tmpl.shape[:2]
            return (max_loc[0] + w // 2, max_loc[1] + h // 2, float(max_val))
        return None

    def tap_template(self, template, threshold: float = 0.85) -> bool:
        """หา template แล้วแตะตรงนั้นเลย — คืน True ถ้าเจอและแตะแล้ว"""
        hit = self.find_template(template, threshold)
        if hit:
            self.ctx.tap(hit[0], hit[1])
            return True
        return False


# ---------------------------------------------------------------------------
# ช่องต่อ AI (เผื่ออนาคต) — ลงทะเบียน "ผู้ให้บริการ AI" แล้วปลั๊กอินเรียกใช้ร่วมกันได้
#   เช่น object detection (YOLO), OCR, หรือ LLM ที่รับภาพ+คำสั่ง
# ---------------------------------------------------------------------------
class AIProvider:
    """อินเทอร์เฟซกลางของโมเดล AI — สืบทอดแล้วลงทะเบียนกับ AIRegistry"""
    name: str = "base"

    def infer(self, frame=None, prompt: str = "", **kwargs) -> Any:
        raise NotImplementedError


class AIRegistry:
    """ทะเบียนกลางของ AIProvider (แชร์ข้ามปลั๊กอินทั้งแอป)"""

    def __init__(self):
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Optional[AIProvider]:
        return self._providers.get(name)

    def names(self) -> list[str]:
        return list(self._providers)

    def __contains__(self, name: str) -> bool:
        return name in self._providers


# ---------------------------------------------------------------------------
# BotContext — สะพานเดียวที่ปลั๊กอินใช้คุยกับมือถือ/แอป
# ---------------------------------------------------------------------------
class BotContext:
    def __init__(self, mgr, serial: str, *, logger: Callable[[str], None],
                 stop_event: threading.Event, config: dict,
                 save_config: Callable[[], None], ai: AIRegistry):
        self._mgr = mgr
        self.serial = serial
        self._logger = logger
        self._stop = stop_event
        self.config = config                # dict ตั้งค่าเฉพาะปลั๊กอิน (persist อัตโนมัติ)
        self._save_config = save_config
        self.vision = Vision(self)
        self.ai = ai                        # ทะเบียน AI ส่วนกลาง

    # ----- วงจรชีวิต / การหยุด --------------------------------------------
    def should_stop(self) -> bool:
        return self._stop.is_set()

    def sleep(self, seconds: float) -> None:
        """หน่วงเวลาแบบขัดจังหวะได้ (ถ้าผู้ใช้สั่งหยุด จะคืนทันที)"""
        self._stop.wait(timeout=max(0.0, seconds))

    # ----- log -------------------------------------------------------------
    def log(self, msg: str) -> None:
        self._logger(str(msg))

    # ----- ตั้งค่า ---------------------------------------------------------
    def save(self) -> None:
        """บันทึก self.config ลงไฟล์ตั้งค่าของแอป"""
        self._save_config()

    # ----- จับภาพหน้าจอ ----------------------------------------------------
    def screencap_png(self) -> bytes:
        return self._mgr.screencap_bytes(self.serial)

    def screencap_pil(self):
        """คืนภาพเป็น PIL.Image (Pillow มากับแอปอยู่แล้ว)"""
        from io import BytesIO
        from PIL import Image
        return Image.open(BytesIO(self.screencap_png())).convert("RGB")

    def screencap_np(self):
        """คืนภาพเป็น numpy array (BGR) สำหรับ OpenCV — ต้องมี numpy"""
        import numpy as np
        img = self.screencap_pil()                 # RGB
        arr = np.asarray(img)
        return arr[:, :, ::-1].copy()              # RGB -> BGR

    # ----- ข้อมูลอุปกรณ์ ---------------------------------------------------
    def screen_size(self) -> tuple[int, int]:
        return self._mgr.screen_size(self.serial)

    def device_model(self) -> str:
        return self._mgr.device_model(self.serial)

    # ----- ควบคุม (input) --------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self._mgr.input_tap(self.serial, x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> None:
        self._mgr.input_swipe(self.serial, x1, y1, x2, y2, duration_ms)

    def key(self, keycode) -> None:
        self._mgr.input_keyevent(self.serial, keycode)

    def text(self, s: str) -> None:
        self._mgr.input_text(self.serial, s)

    def back(self) -> None:
        self.key("KEYCODE_BACK")

    def home(self) -> None:
        self.key("KEYCODE_HOME")


# ---------------------------------------------------------------------------
# คลาสฐานของปลั๊กอิน — ผู้ใช้สืบทอดจากตัวนี้
# ---------------------------------------------------------------------------
class BotPlugin:
    """
    สืบทอดคลาสนี้เพื่อสร้างบอท แล้ววางไฟล์ไว้ในโฟลเดอร์ plugins/

    ขั้นต่ำที่ต้องมี:
      - แอตทริบิวต์ `meta` (PluginMeta)
      - เมธอด `run(self, ctx)` วนลูปของบอท โดย "ต้องเช็ก ctx.should_stop()"
    """
    meta: PluginMeta = PluginMeta(name="Unnamed Plugin")

    def on_load(self, ctx: BotContext) -> None:
        """เรียกครั้งเดียวตอนเลือกปลั๊กอิน (ตั้งค่าเริ่มต้น/โหลดทรัพยากร)"""

    def run(self, ctx: BotContext) -> None:  # pragma: no cover - ผู้ใช้ override
        """ลูปหลักของบอท — ต้องออกจากลูปเมื่อ ctx.should_stop() เป็น True"""
        raise NotImplementedError("ปลั๊กอินต้องนิยามเมธอด run(self, ctx)")

    def on_stop(self) -> None:
        """เรียกเมื่อบอทหยุด (เคลียร์ทรัพยากร)"""

    # ออปชัน: คืน QWidget เพื่อโชว์แผงตั้งค่าของปลั๊กอินในแอป (คืน None ถ้าไม่มี)
    def build_settings_widget(self):
        return None


# helper เล็ก ๆ ให้ปลั๊กอินใช้
def now() -> float:
    return time.monotonic()
