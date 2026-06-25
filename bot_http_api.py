"""
bot_http_api.py
===============
REST API เล็ก ๆ สำหรับสั่งคุมมือถือจากภายนอก (สคริปต์/ทูล/บอทภาษาอื่น)
— ผูกกับ 127.0.0.1 เท่านั้น (localhost) เพื่อความปลอดภัย ไม่เปิดออกเน็ตเวิร์ก

ใช้แค่ไลบรารีมาตรฐาน (http.server) — ไม่เพิ่ม dependency

ความปลอดภัย:
  - bind 127.0.0.1 อย่างเดียว → เครื่องอื่นในวง LAN ต่อไม่ได้
  - ตั้ง token ได้ (ส่งผ่าน header `X-Api-Token` หรือ query `?token=`)
    ถ้าไม่ตั้ง = เปิดให้ทุกโปรเซสในเครื่องเรียกได้ (สะดวกแต่หลวมกว่า)

เอ็นด์พอยต์ (ทั้งหมดคืน JSON ยกเว้น /screenshot ที่คืน image/png):
  GET  /            ข้อมูล/รายการคำสั่ง
  GET  /status      สถานะเครื่องมือ + serial ที่กำลังคุม
  GET  /devices     อุปกรณ์ที่ adb เห็น
  GET  /screenshot  ภาพหน้าจอ PNG
  POST /tap         {"x":..,"y":..}
  POST /swipe       {"x1":..,"y1":..,"x2":..,"y2":..,"duration_ms":200}
  POST /key         {"code":"KEYCODE_BACK"}
  POST /text        {"text":"hello"}
  GET  /plugins     รายการปลั๊กอิน + สถานะรัน

ตัวอย่าง:
  curl http://127.0.0.1:8770/status
  curl -X POST http://127.0.0.1:8770/tap -d '{"x":540,"y":1200}'
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse, parse_qs


class BotHttpApi:
    """เซิร์ฟเวอร์ REST แบบ start/stop ได้ — รันใน background thread"""

    def __init__(self, mgr, get_serial: Callable[[], str], *,
                 plugin_mgr=None, host: str = "127.0.0.1", port: int = 8770,
                 token: Optional[str] = None,
                 logger: Optional[Callable[[str], None]] = None):
        self.mgr = mgr                         # ScrcpyManager
        self.get_serial = get_serial           # callable คืน serial ปัจจุบัน ("" ถ้าไม่มี)
        self.plugin_mgr = plugin_mgr           # PluginManager (ออปชัน — ใช้ list ปลั๊กอิน)
        self.host = host
        self.port = int(port)
        self.token = token or None
        self._logger = logger
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # --------------------------------------------------------------- lifecycle
    @property
    def is_running(self) -> bool:
        return self._httpd is not None

    def start(self) -> None:
        if self.is_running:
            return
        handler = _make_handler(self)
        # ผูก localhost เท่านั้น — เครื่องอื่นเข้าไม่ได้
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="BotHttpApi", daemon=True)
        self._thread.start()
        self._log(f"🌐 เปิด HTTP API ที่ http://{self.host}:{self.port}"
                  + ("  (มี token)" if self.token else "  (ไม่มี token)"))

    def stop(self) -> None:
        if not self._httpd:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        finally:
            self._httpd = None
            self._thread = None
            self._log("🌐 ปิด HTTP API แล้ว")

    def _log(self, msg: str) -> None:
        if self._logger:
            try:
                self._logger(msg)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------- การยืนยันสิทธิ์
    def _check_token(self, headers, query: dict) -> bool:
        if not self.token:
            return True
        sent = headers.get("X-Api-Token") or (query.get("token", [None])[0])
        return sent == self.token

    def _serial_or_error(self) -> str:
        serial = self.get_serial() or ""
        if not serial:
            raise _ApiError(409, "ยังไม่มีอุปกรณ์ที่เชื่อมต่อ")
        return serial


class _ApiError(Exception):
    """error ที่มี HTTP status — ตัว handler จับแล้วตอบกลับ"""
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _make_handler(api: "BotHttpApi"):
    """สร้างคลาส handler ที่ผูกกับ instance ของ BotHttpApi"""

    class Handler(BaseHTTPRequestHandler):
        server_version = "BotHttpApi/1.0"

        # ปิด log ของ http.server ที่พ่นออก stderr (เรา log เองผ่าน api._log)
        def log_message(self, fmt, *args):  # noqa: A003
            return

        # ----------------------------------------------------------- ตัวช่วยตอบ
        def _send_json(self, obj, status: int = 200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_png(self, data: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if not length:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                raise _ApiError(400, f"อ่าน JSON ไม่ได้: {e}") from e
            if not isinstance(data, dict):
                raise _ApiError(400, "body ต้องเป็น JSON object")
            return data

        def _guard(self, query: dict):
            if not api._check_token(self.headers, query):
                raise _ApiError(401, "token ไม่ถูกต้อง")

        # ------------------------------------------------------------ dispatch
        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def _dispatch(self, method: str):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            try:
                self._guard(query)
                handler = _ROUTES.get((method, path))
                if handler is None:
                    raise _ApiError(404, f"ไม่พบเส้นทาง {method} {path}")
                handler(self)
            except _ApiError as e:
                self._send_json({"ok": False, "error": e.message}, e.status)
            except Exception as e:  # noqa: BLE001
                self._send_json({"ok": False, "error": str(e)}, 500)

        # -------------------------------------------------------------- routes
        def r_index(self):
            self._send_json({
                "ok": True,
                "service": "ScreenCast Studio — Bot HTTP API",
                "endpoints": [
                    "GET /status", "GET /devices", "GET /screenshot",
                    "POST /tap", "POST /swipe", "POST /key", "POST /text",
                    "GET /plugins",
                ],
            })

        def r_status(self):
            serial = api.get_serial() or ""
            self._send_json({
                "ok": True,
                "ready": bool(api.mgr.is_ready),
                "serial": serial,
                "screen_size": list(api.mgr.screen_size(serial)) if serial else [0, 0],
            })

        def r_devices(self):
            devs = api.mgr.list_devices()
            self._send_json({"ok": True, "devices": [
                {"serial": d.serial, "state": d.state,
                 "wireless": d.is_wireless, "model": d.model} for d in devs]})

        def r_screenshot(self):
            serial = api._serial_or_error()
            self._send_png(api.mgr.screencap_bytes(serial, use_cache=False))

        def r_tap(self):
            serial = api._serial_or_error()
            d = self._read_json()
            api.mgr.input_tap(serial, int(d["x"]), int(d["y"]))
            self._send_json({"ok": True})

        def r_swipe(self):
            serial = api._serial_or_error()
            d = self._read_json()
            api.mgr.input_swipe(serial, int(d["x1"]), int(d["y1"]),
                                int(d["x2"]), int(d["y2"]),
                                int(d.get("duration_ms", 200)))
            self._send_json({"ok": True})

        def r_key(self):
            serial = api._serial_or_error()
            d = self._read_json()
            api.mgr.input_keyevent(serial, d.get("code", d.get("keycode")))
            self._send_json({"ok": True})

        def r_text(self):
            serial = api._serial_or_error()
            d = self._read_json()
            api.mgr.input_text(serial, str(d.get("text", "")))
            self._send_json({"ok": True})

        def r_plugins(self):
            if api.plugin_mgr is None:
                raise _ApiError(501, "ไม่ได้ผูก PluginManager")
            out = []
            for lp in api.plugin_mgr.discover():
                out.append({"key": lp.key, "name": lp.meta.name,
                            "ok": lp.ok, "error": lp.error,
                            "running": api.plugin_mgr.is_running(lp.key)})
            self._send_json({"ok": True, "plugins": out})

    # ตารางเส้นทาง (method, path) -> เมธอดบน handler
    _ROUTES = {
        ("GET", "/"): Handler.r_index,
        ("GET", "/status"): Handler.r_status,
        ("GET", "/devices"): Handler.r_devices,
        ("GET", "/screenshot"): Handler.r_screenshot,
        ("GET", "/plugins"): Handler.r_plugins,
        ("POST", "/tap"): Handler.r_tap,
        ("POST", "/swipe"): Handler.r_swipe,
        ("POST", "/key"): Handler.r_key,
        ("POST", "/text"): Handler.r_text,
    }

    return Handler
