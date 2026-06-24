"""
win_embed.py
------------
ฝังหน้าต่างของโปรแกรมภายนอก (scrcpy) เข้าไปใน widget ของแอปเรา บน Windows
ด้วย Win32 SetParent (reparenting)

หมายเหตุ: เป็นฟีเจอร์ "ทดลอง" — ถ้าหา/ฝังหน้าต่างไม่ได้ จะคืน False เฉย ๆ
ไม่ทำให้แอปหลักพัง (scrcpy ยังเปิดเป็นหน้าต่างแยกตามปกติ)
"""
from __future__ import annotations

import time

try:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _AVAILABLE = True
except Exception:  # noqa: BLE001  (ไม่ใช่ Windows)
    _AVAILABLE = False

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000


def available() -> bool:
    return _AVAILABLE


def find_window(title: str) -> int:
    """หา HWND จากชื่อหน้าต่างแบบตรงเป๊ะ; 0 = ไม่เจอ"""
    if not _AVAILABLE:
        return 0
    return _user32.FindWindowW(None, title) or 0


def wait_for_window(title: str, timeout: float = 6.0) -> int:
    """รอจนหน้าต่างชื่อนี้โผล่ (หรือหมดเวลา) คืน HWND หรือ 0"""
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find_window(title)
        if hwnd:
            return hwnd
        time.sleep(0.15)
    return 0


def embed(child_hwnd: int, parent_hwnd: int) -> bool:
    """ทำให้ child กลายเป็นลูกของ parent (เอา title bar/ขอบออก)"""
    if not (_AVAILABLE and child_hwnd and parent_hwnd):
        return False
    try:
        style = _user32.GetWindowLongW(child_hwnd, GWL_STYLE)
        style = (style & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME) | WS_CHILD
        _user32.SetWindowLongW(child_hwnd, GWL_STYLE, style)
        _user32.SetParent(child_hwnd, parent_hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


def resize(child_hwnd: int, w: int, h: int) -> None:
    if _AVAILABLE and child_hwnd:
        _user32.MoveWindow(child_hwnd, 0, 0, max(1, w), max(1, h), True)
