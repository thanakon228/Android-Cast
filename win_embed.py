"""
win_embed.py
------------
ฝังหน้าต่างของโปรแกรมภายนอก (scrcpy) เข้าไปใน widget ของแอปเรา บน Windows
ด้วย Win32 SetParent (reparenting)

หมายเหตุ: เป็นฟีเจอร์ "ทดลอง" — ถ้าหา/ฝังหน้าต่างไม่ได้ จะคืน 0/False เฉย ๆ
ไม่ทำให้แอปหลักพัง (scrcpy ยังเปิดเป็นหน้าต่างแยกตามปกติ)

หาหน้าต่างจาก process id ของ scrcpy เป็นหลัก (แม่นกว่า title) แล้ว fallback เป็น title
"""
from __future__ import annotations

import time

try:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _AVAILABLE = True
except Exception:  # noqa: BLE001  (ไม่ใช่ Windows)
    _AVAILABLE = False

if _AVAILABLE:
    # กำหนด prototype ให้ถูกต้อง — สำคัญมากบน 64-bit เพื่อไม่ให้ HWND ถูกตัดเป็น 32-bit
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongW.restype = wintypes.LONG
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    _user32.SetParent.restype = wintypes.HWND
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.MoveWindow.restype = wintypes.BOOL
    _user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_BORDER = 0x00800000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040


def available() -> bool:
    return _AVAILABLE


def find_window_by_pid(pid: int) -> int:
    """หาหน้าต่าง top-level ที่มองเห็นได้ ของ process pid; 0 = ไม่เจอ"""
    if not (_AVAILABLE and pid):
        return 0
    result = {"hwnd": 0}

    def _cb(hwnd, _lparam):
        wpid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and _user32.IsWindowVisible(hwnd):
            result["hwnd"] = hwnd
            return False  # หยุด enumerate
        return True

    _user32.EnumWindows(_WNDENUMPROC(_cb), 0)
    return int(result["hwnd"] or 0)


def find_window_by_title(title: str) -> int:
    if not _AVAILABLE:
        return 0
    return int(_user32.FindWindowW(None, title) or 0)


def wait_for_window(pid: int, title: str, timeout: float = 10.0) -> int:
    """รอจนหน้าต่าง scrcpy โผล่ (หา pid ก่อน แล้ว fallback เป็น title); คืน HWND หรือ 0"""
    end = time.time() + timeout
    while time.time() < end:
        hwnd = find_window_by_pid(pid) or find_window_by_title(title)
        if hwnd:
            return hwnd
        time.sleep(0.2)
    return 0


def embed(child_hwnd: int, parent_hwnd: int) -> bool:
    """ทำให้ child กลายเป็นลูกของ parent (เอา title bar/ขอบออก)"""
    if not (_AVAILABLE and child_hwnd and parent_hwnd):
        return False
    try:
        style = _user32.GetWindowLongW(child_hwnd, GWL_STYLE)
        style = (style & ~WS_POPUP & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_BORDER) | WS_CHILD
        _user32.SetWindowLongW(child_hwnd, GWL_STYLE, style)

        _kernel32.SetLastError(0)
        _user32.SetParent(child_hwnd, parent_hwnd)
        err = _kernel32.GetLastError()
        if err != 0:
            return False

        _user32.SetWindowPos(child_hwnd, None, 0, 0, 0, 0,
                             SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_SHOWWINDOW)
        return True
    except Exception:  # noqa: BLE001
        return False


def resize(child_hwnd: int, w: int, h: int) -> None:
    if _AVAILABLE and child_hwnd:
        _user32.MoveWindow(child_hwnd, 0, 0, max(1, int(w)), max(1, int(h)), True)
