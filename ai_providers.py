"""
ai_providers.py
===============
ผู้ให้บริการ AI ที่ "มากับแอป" (built-in) — ลงทะเบียนเข้า AIRegistry กลาง
ให้ทุกปลั๊กอินเรียกใช้ร่วมกันผ่าน ctx.ai

ตอนนี้มี:
  - OcrProvider (name="ocr")  อ่านตัวอักษรจากภาพหน้าจอ (ใช้ pytesseract ถ้ามี)

ออกแบบให้ "ต่อเติมง่าย": เขียนคลาสใหม่ที่สืบทอด AIProvider แล้วเพิ่มใน
register_builtin_providers() ด้านล่าง — ไม่ต้องไปยุ่งกับโค้ดส่วนอื่น

หมายเหตุ: dependency ของ AI (pytesseract/opencv ฯลฯ) โหลดแบบ lazy ทั้งหมด
แอปจึงรันได้แม้ไม่ได้ติดตั้ง — provider จะค่อยแจ้ง error ตอนถูกเรียกจริง
"""
from __future__ import annotations

from typing import Any

from plugin_api import AIProvider, AIRegistry


# ---------------------------------------------------------------------------
# ตัวช่วย: แปลง frame (PIL / numpy / PNG bytes) -> PIL.Image
# ---------------------------------------------------------------------------
def _to_pil(frame: Any):
    """รับภาพได้หลายแบบแล้วคืน PIL.Image (RGB) — โยน error ถ้าไม่รู้จักชนิด"""
    if frame is None:
        raise ValueError("ต้องส่งภาพ (frame) เข้ามาก่อน เช่น ctx.screencap_pil()")
    # PIL.Image อยู่แล้ว
    if hasattr(frame, "convert") and hasattr(frame, "size"):
        return frame.convert("RGB")
    # PNG/JPEG bytes
    if isinstance(frame, (bytes, bytearray)):
        from io import BytesIO
        from PIL import Image
        return Image.open(BytesIO(frame)).convert("RGB")
    # numpy array (เดาว่าเป็น BGR จาก ctx.screencap_np())
    try:
        import numpy as np
        from PIL import Image
        if isinstance(frame, np.ndarray):
            arr = frame[:, :, ::-1] if frame.ndim == 3 else frame   # BGR -> RGB
            return Image.fromarray(arr).convert("RGB")
    except ImportError:
        pass
    raise TypeError(f"ไม่รู้จักชนิดของ frame: {type(frame)!r}")


# ---------------------------------------------------------------------------
# OCR — อ่านตัวอักษรจากภาพ
# ---------------------------------------------------------------------------
class OcrProvider(AIProvider):
    """
    อ่านข้อความจากภาพหน้าจอ (เผื่อบอทที่ต้องอ่านเลข/สถานะในเกม)

    ใช้ผ่าน ctx:
        ocr = ctx.ai.get("ocr")
        text = ocr.infer(ctx.screencap_pil())            # อ่านทั้งจอ
        text = ocr.infer(ctx.screencap_pil(), lang="tha+eng")

    ต้องติดตั้งก่อนใช้งานจริง:
        pip install pytesseract pillow
        + โปรแกรม Tesseract-OCR (https://github.com/UB-Mannheim/tesseract/wiki)
    ถ้ายังไม่ได้ติดตั้ง จะโยน RuntimeError พร้อมคำแนะนำตอนถูกเรียก (แอปไม่ล่ม)
    """
    name = "ocr"

    def infer(self, frame=None, prompt: str = "", *, lang: str = "eng",
              **kwargs) -> Any:
        try:
            import pytesseract
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "OCR ต้องติดตั้ง pytesseract ก่อน (pip install pytesseract) "
                "และโปรแกรม Tesseract-OCR ในเครื่อง"
            ) from e
        img = _to_pil(frame)
        try:
            return pytesseract.image_to_string(img, lang=lang).strip()
        except pytesseract.TesseractNotFoundError as e:
            raise RuntimeError(
                "หาโปรแกรม Tesseract-OCR ไม่เจอ — ติดตั้งจาก "
                "https://github.com/UB-Mannheim/tesseract/wiki "
                "แล้วเพิ่มลง PATH (หรือ set pytesseract.pytesseract.tesseract_cmd)"
            ) from e


# ---------------------------------------------------------------------------
# ลงทะเบียน built-in ทั้งหมด — เรียกจาก PluginManager ตอนสร้าง AIRegistry
# ---------------------------------------------------------------------------
def register_builtin_providers(registry: AIRegistry) -> None:
    """เพิ่ม provider ที่มากับแอปลงทะเบียนกลาง (ข้ามตัวที่ลงทะเบียนไว้แล้ว)"""
    for provider in (OcrProvider(),):
        if provider.name not in registry:
            registry.register(provider)
