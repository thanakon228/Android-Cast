"""
scrcpy_manager.py
-----------------
จัดการเครื่องมือ scrcpy + adb:
- ดาวน์โหลด/แตกไฟล์ scrcpy อัตโนมัติ (Windows) ถ้ายังไม่มีในเครื่อง
- ฟังก์ชัน wrapper สำหรับ adb / scrcpy ที่ใช้บ่อย (pair, connect, devices, mirror)

ทุกฟังก์ชันที่ "บล็อก" (เรียก subprocess) ออกแบบให้เรียกจาก worker thread ได้
"""

from __future__ import annotations

import io
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

# ---------------------------------------------------------------------------
# ตำแหน่งไฟล์
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
TOOLS_DIR = ROOT / "tools"
GITHUB_API_LATEST = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"

# ป้องกัน console window เด้งตอนเรียก subprocess บน Windows
_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class Device:
    """ข้อมูลอุปกรณ์ที่ adb มองเห็น"""
    serial: str          # เช่น 192.168.1.50:5555  หรือ  RZ8N...  (USB)
    state: str           # device / unauthorized / offline
    is_wireless: bool
    model: str = ""

    @property
    def label(self) -> str:
        name = self.model or self.serial
        kind = "WiFi" if self.is_wireless else "USB"
        return f"{name}  ({kind})"


class ToolError(Exception):
    pass


class ScrcpyManager:
    """หา / ดาวน์โหลด scrcpy แล้วเรียกใช้ adb + scrcpy"""

    def __init__(self) -> None:
        self.scrcpy_path: Optional[Path] = None
        self.adb_path: Optional[Path] = None
        # callback รับข้อความ log (set จากภายนอก) — ต้อง thread-safe ฝั่งผู้รับ
        self.logger: Optional[Callable[[str], None]] = None
        # callback รับค่า FPS เรียลไทม์ (parse จาก --print-fps) — ต้อง thread-safe
        self.fps_callback: Optional[Callable[[int], None]] = None
        # แคชภาพหน้าจอช่วงสั้น ๆ (กันยิง adb ซ้ำถี่ ๆ เวลาหา template หลายรูป)
        # TTL ~150ms: นานพอลด adb roundtrip แต่สั้นพอภาพยังสด — ล้างทันทีหลังสั่ง input
        self.screencap_ttl: float = 0.15
        self._screencap_cache: dict[str, tuple[float, bytes]] = {}
        self._screencap_lock = threading.Lock()
        self._locate_existing()

    def _log(self, msg: str) -> None:
        if self.logger:
            try:
                self.logger(msg)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ setup
    def _locate_existing(self) -> None:
        """หา scrcpy/adb จาก (1) โฟลเดอร์ tools ที่เคยโหลด (2) PATH ของระบบ"""
        # 1) โฟลเดอร์ tools ที่โหลดเอง
        for exe in TOOLS_DIR.rglob("scrcpy.exe"):
            self.scrcpy_path = exe
            adb = exe.parent / "adb.exe"
            if adb.exists():
                self.adb_path = adb
            break
        # 2) ระบบ PATH
        if self.scrcpy_path is None:
            found = shutil.which("scrcpy")
            if found:
                self.scrcpy_path = Path(found)
        if self.adb_path is None:
            found = shutil.which("adb")
            if found:
                self.adb_path = Path(found)

    @property
    def is_ready(self) -> bool:
        return self.scrcpy_path is not None and self.adb_path is not None

    def ensure_tools(self, progress: Optional[Callable[[str, int], None]] = None) -> None:
        """ถ้ายังไม่มี scrcpy ให้ดาวน์โหลดเวอร์ชันล่าสุด (win64) มาแตกที่ tools/"""
        if self.is_ready:
            return

        def report(msg: str, pct: int) -> None:
            if progress:
                progress(msg, pct)

        report("กำลังค้นหาเวอร์ชัน scrcpy ล่าสุด...", 2)
        try:
            rel = requests.get(GITHUB_API_LATEST, timeout=30).json()
        except Exception as e:  # noqa: BLE001
            raise ToolError(f"เชื่อมต่อ GitHub ไม่ได้: {e}") from e

        asset = None
        for a in rel.get("assets", []):
            name = a.get("name", "")
            if name.endswith(".zip") and "win64" in name:
                asset = a
                break
        if asset is None:
            raise ToolError("ไม่พบไฟล์ scrcpy win64 บน GitHub release")

        url = asset["browser_download_url"]
        report(f"กำลังดาวน์โหลด {asset['name']} ...", 5)

        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            got = 0
            for chunk in r.iter_content(chunk_size=1 << 16):
                buf.write(chunk)
                got += len(chunk)
                if total:
                    pct = 5 + int(got / total * 80)
                    report(f"กำลังดาวน์โหลด... {got // (1<<20)}MB / {total // (1<<20)}MB", pct)

        report("กำลังแตกไฟล์...", 88)
        with zipfile.ZipFile(buf) as z:
            z.extractall(TOOLS_DIR)

        self._locate_existing()
        if not self.is_ready:
            raise ToolError("แตกไฟล์แล้วแต่หา scrcpy.exe/adb.exe ไม่เจอ")
        report("พร้อมใช้งาน", 100)

    # ------------------------------------------------------------------- adb
    def _adb(self, *args: str, timeout: int = 30,
             log: bool = False) -> subprocess.CompletedProcess:
        if not self.adb_path:
            raise ToolError("ยังไม่มี adb")
        if log:
            self._log("$ adb " + " ".join(args))
        cp = subprocess.run(
            [str(self.adb_path), *args],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
        if log:
            out = (cp.stdout + cp.stderr).strip()
            if out:
                self._log("  " + out.replace("\n", "\n  "))
        return cp

    def start_server(self) -> None:
        self._adb("start-server", timeout=20)

    def list_devices(self) -> list[Device]:
        cp = self._adb("devices", "-l")
        devices: list[Device] = []
        for line in cp.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            model = ""
            for p in parts[2:]:
                if p.startswith("model:"):
                    model = p.split(":", 1)[1].replace("_", " ")
            is_wireless = bool(re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", serial)) or \
                          serial.endswith("._tcp") or "adb-tls" in serial
            devices.append(Device(serial, state, is_wireless, model))
        return devices

    def pair(self, host_port: str, code: str) -> str:
        """จับคู่แบบไร้สาย (Android 11+) ด้วย IP:PORT + รหัส 6 หลัก"""
        cp = self._adb("pair", host_port, code, timeout=30, log=True)
        out = (cp.stdout + cp.stderr).strip()
        if "Successfully paired" not in out:
            raise ToolError(out or "จับคู่ไม่สำเร็จ")
        return out

    def connect(self, host_port: str) -> str:
        cp = self._adb("connect", host_port, timeout=20, log=True)
        out = (cp.stdout + cp.stderr).strip()
        if "connected" not in out.lower():
            raise ToolError(out or "เชื่อมต่อไม่สำเร็จ")
        return out

    def disconnect(self, host_port: Optional[str] = None) -> None:
        self._adb("disconnect", *( [host_port] if host_port else [] ), timeout=15, log=True)

    def mdns_connect_target(self) -> Optional[str]:
        """ค้นหาพอร์ตเชื่อมต่อไร้สายอัตโนมัติผ่าน mDNS (หลังจาก pair สำเร็จ)"""
        for kind, hostport in self.discover():
            if kind == "connect":
                return hostport
        return None

    def discover(self) -> list[tuple[str, str]]:
        """
        ค้นหาอุปกรณ์ในวง WiFi ผ่าน mDNS ที่ adb มีในตัว
        คืน list ของ (kind, 'ip:port') โดย kind = 'connect' หรือ 'pairing'
        """
        cp = self._adb("mdns", "services", timeout=10)
        found: list[tuple[str, str]] = []
        for line in cp.stdout.splitlines():
            m = re.search(r"_adb-tls-(connect|pairing).*?(\d+\.\d+\.\d+\.\d+:\d+)", line)
            if m:
                found.append((m.group(1), m.group(2)))
        # ตัดซ้ำแต่คงลำดับ
        seen, uniq = set(), []
        for item in found:
            if item not in seen:
                seen.add(item)
                uniq.append(item)
        return uniq

    def screenshot(self, serial: str, out_path: "Path") -> "Path":
        """ถ่ายภาพหน้าจอมือถือเป็น PNG (ใช้ adb exec-out screencap — binary-safe)"""
        if not self.adb_path:
            raise ToolError("ยังไม่มี adb")
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as f:
            cp = subprocess.run(
                [str(self.adb_path), "-s", serial, "exec-out", "screencap", "-p"],
                stdout=f, stderr=subprocess.PIPE, timeout=20,
                creationflags=_CREATE_NO_WINDOW,
            )
        if cp.returncode != 0 or out_path.stat().st_size == 0:
            err = cp.stderr.decode("utf-8", "replace").strip() if cp.stderr else ""
            raise ToolError(err or "ถ่ายภาพหน้าจอไม่สำเร็จ")
        self._log(f"📸 บันทึกภาพ: {out_path}")
        return out_path

    def enable_tcpip(self, serial: str, port: int = 5555) -> None:
        """สั่งให้อุปกรณ์ USB เปิดโหมด adb-over-wifi"""
        cp = self._adb("-s", serial, "tcpip", str(port), timeout=20, log=True)
        out = (cp.stdout + cp.stderr).lower()
        if "error" in out:
            raise ToolError(cp.stdout + cp.stderr)

    def device_ip(self, serial: str) -> Optional[str]:
        """หา IP ของอุปกรณ์ (wlan0) สำหรับสลับมาเชื่อมไร้สาย"""
        cp = self._adb("-s", serial, "shell", "ip", "-f", "inet", "addr", "show", "wlan0")
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", cp.stdout)
        if m:
            return m.group(1)
        # fallback
        cp = self._adb("-s", serial, "shell", "ip", "route")
        m = re.search(r"src (\d+\.\d+\.\d+\.\d+)", cp.stdout)
        return m.group(1) if m else None

    # ---------------------------------------------------------------- scrcpy
    def mirror(self, serial: str, title: str = "ScreenCast Studio",
               extra: Optional[list[str]] = None) -> subprocess.Popen:
        """เปิดหน้าต่างมิเรอร์ (process แยก) — คืน Popen ให้ caller ถือไว้"""
        if not self.scrcpy_path:
            raise ToolError("ยังไม่มี scrcpy")
        args = [
            str(self.scrcpy_path),
            "-s", serial,
            "--window-title", title,
        ]
        if extra:
            args += extra
        env = os.environ.copy()
        # ให้ scrcpy หา adb ตัวเดียวกับเรา
        if self.adb_path:
            env["ADB"] = str(self.adb_path)

        self._log(f"$ scrcpy -s {serial}")
        # ถ้ามี logger -> ดึง output ของ scrcpy เข้า console (ต้อง drain ไม่งั้น buffer ตัน)
        if self.logger:
            proc = subprocess.Popen(
                args, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=_CREATE_NO_WINDOW,
            )
            threading.Thread(target=self._pump_output, args=(proc,), daemon=True).start()
            return proc
        return subprocess.Popen(args, env=env, creationflags=_CREATE_NO_WINDOW)

    def _pump_output(self, proc: subprocess.Popen) -> None:
        """อ่าน output ของ scrcpy ทีละบรรทัดส่งเข้า logger + ดึงค่า FPS"""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                # ดึงเลข fps จากบรรทัดที่ scrcpy พิมพ์ออกมา (จาก --print-fps)
                # แล้วไม่ log บรรทัด fps ลง console (กันรก เพราะพิมพ์ทุกวินาที)
                if "fps" in line:
                    m = re.search(r"(\d+)\s*fps", line)
                    if m:
                        if self.fps_callback:
                            try:
                                self.fps_callback(int(m.group(1)))
                            except Exception:  # noqa: BLE001
                                pass
                        continue
                self._log("[scrcpy] " + line)
        except Exception:  # noqa: BLE001
            pass

    # ----------------------------------------------------- ข้อมูลสถานะอุปกรณ์
    def device_model(self, serial: str) -> str:
        """ชื่อรุ่นมือถือ (เช่น 'Pixel 7')"""
        try:
            cp = self._adb("-s", serial, "shell", "getprop", "ro.product.model", timeout=8)
            return cp.stdout.strip()
        except Exception:  # noqa: BLE001
            return ""

    def battery_level(self, serial: str) -> tuple[int, bool]:
        """คืน (เปอร์เซ็นต์แบต, กำลังชาร์จ?) — (-1, False) ถ้าอ่านไม่ได้"""
        level, charging = -1, False
        try:
            cp = self._adb("-s", serial, "shell", "dumpsys", "battery", timeout=8)
            for line in cp.stdout.splitlines():
                s = line.strip()
                if s.startswith("level:"):
                    try:
                        level = int(s.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                elif s.startswith("status:"):
                    # 2=charging, 5=full
                    charging = s.split(":", 1)[1].strip() in ("2", "5") or charging
                elif s.startswith("AC powered:") and "true" in s:
                    charging = True
                elif s.startswith("USB powered:") and "true" in s:
                    charging = True
        except Exception:  # noqa: BLE001
            pass
        return level, charging

    def ping_ms(self, ip: str) -> int:
        """ping ไป IP มือถือ คืนค่าหน่วง (ms) — -1 ถ้า ping ไม่ได้"""
        try:
            cp = subprocess.run(
                ["ping", "-n", "1", "-w", "1000", ip],
                capture_output=True, text=True, timeout=4,
                encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW,
            )
            m = re.search(r"[<=]\s*(\d+)\s*ms", cp.stdout)
            if m:
                return int(m.group(1))
        except Exception:  # noqa: BLE001
            pass
        return -1

    # ------------------------------------------------ คุมมือถือ (สำหรับบอท/ปลั๊กอิน)
    def invalidate_screencap(self, serial: Optional[str] = None) -> None:
        """ทิ้งแคชภาพหน้าจอ (serial เดียว หรือทั้งหมดถ้า None) — เรียกหลังสั่ง input"""
        with self._screencap_lock:
            if serial is None:
                self._screencap_cache.clear()
            else:
                self._screencap_cache.pop(serial, None)

    def screencap_bytes(self, serial: str, use_cache: bool = True) -> bytes:
        """
        จับภาพหน้าจอเป็น PNG (bytes) — ไม่เขียนไฟล์ (เหมาะกับบอท/AI)

        use_cache=True: คืนภาพเดิมถ้าเพิ่งจับไปไม่เกิน screencap_ttl วินาที
        (ช่วยตอนหา template หลายรูปติด ๆ กัน — ยิง adb ครั้งเดียว)
        """
        if not self.adb_path:
            raise ToolError("ยังไม่มี adb")
        if use_cache:
            with self._screencap_lock:
                hit = self._screencap_cache.get(serial)
                if hit and (time.monotonic() - hit[0]) < self.screencap_ttl:
                    return hit[1]
        cp = subprocess.run(
            [str(self.adb_path), "-s", serial, "exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
            creationflags=_CREATE_NO_WINDOW,
        )
        if cp.returncode != 0 or not cp.stdout:
            err = cp.stderr.decode("utf-8", "replace").strip() if cp.stderr else ""
            raise ToolError(err or "จับภาพหน้าจอไม่สำเร็จ")
        if use_cache:
            with self._screencap_lock:
                self._screencap_cache[serial] = (time.monotonic(), cp.stdout)
        return cp.stdout

    def screen_size(self, serial: str) -> tuple[int, int]:
        """ความละเอียดหน้าจอมือถือ (กว้าง, สูง) — (0,0) ถ้าอ่านไม่ได้"""
        try:
            cp = self._adb("-s", serial, "shell", "wm", "size", timeout=8)
            m = re.search(r"(\d+)\s*x\s*(\d+)", cp.stdout)
            if m:
                return (int(m.group(1)), int(m.group(2)))
        except Exception:  # noqa: BLE001
            pass
        return (0, 0)

    def input_tap(self, serial: str, x: int, y: int) -> None:
        self._adb("-s", serial, "shell", "input", "tap", str(int(x)), str(int(y)), timeout=10)
        self.invalidate_screencap(serial)   # จอเปลี่ยนแล้ว — แคชเก่าใช้ไม่ได้

    def input_swipe(self, serial: str, x1: int, y1: int, x2: int, y2: int,
                    duration_ms: int = 200) -> None:
        self._adb("-s", serial, "shell", "input", "swipe",
                  str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
                  str(int(duration_ms)), timeout=10)
        self.invalidate_screencap(serial)

    def input_keyevent(self, serial: str, keycode) -> None:
        """ส่งปุ่ม (เลข keycode หรือชื่อ เช่น 'KEYCODE_HOME')"""
        self._adb("-s", serial, "shell", "input", "keyevent", str(keycode), timeout=10)
        self.invalidate_screencap(serial)

    def input_text(self, serial: str, text: str) -> None:
        """พิมพ์ข้อความ (เว้นวรรคแทนด้วย %s ตามที่ adb ต้องการ)"""
        self._adb("-s", serial, "shell", "input", "text",
                  text.replace(" ", "%s"), timeout=10)
        self.invalidate_screencap(serial)


# ------------------------------------------------------------------ helpers
def local_ip() -> str:
    """IP ของ PC ในวง LAN (ไว้โชว์ให้ผู้ใช้ตรวจว่าอยู่วงเดียวกับมือถือ)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"
    finally:
        s.close()
