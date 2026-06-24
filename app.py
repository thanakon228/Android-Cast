r"""
ScreenCast Studio
=================
แคสหน้าจอ Android ขึ้นหน้าต่าง PC แบบไร้สาย — UI สไตล์ TikTok Live
ใช้ scrcpy + adb เป็นเครื่องยนต์ (ดาวน์โหลดให้อัตโนมัติ)

วิธีเชื่อมต่อ (ไร้สาย ไม่ต้องใช้สาย หลังตั้งค่าครั้งแรก):
  มือถือ -> Settings -> About phone -> แตะ Build number 7 ครั้ง (เปิด Developer options)
  -> Developer options -> Wireless debugging -> เปิด
  -> "Pair device with pairing code"  (จะได้ IP:PORT + รหัส 6 หลัก)
  เอามากรอกในแอปนี้แท็บ "WiFi" -> กดเชื่อมต่อ -> มิเรอร์ขึ้นจอ

รัน:  ScreenCastStudio\.venv\Scripts\python.exe app.py   (หรือดับเบิลคลิก run.bat)
"""

from __future__ import annotations

import sys
import threading
import time

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QFont
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QLineEdit, QStackedWidget, QFrame, QProgressBar, QMessageBox, QSizePolicy,
)

import qrcode

from scrcpy_manager import ScrcpyManager, ToolError, local_ip
from settings_store import load_settings, save_settings

APP_NAME = "ScreenCast Studio"

# พารามิเตอร์ส่งให้ scrcpy ตอนเปิดมิเรอร์ (ปรับความลื่น/คุณภาพได้ที่นี่)
MIRROR_EXTRA = ["--video-bit-rate", "8M", "--max-fps", "60"]


# ---------------------------------------------------------------------------
# Worker thread กลาง — รันงาน blocking โดยไม่ค้าง UI
# ---------------------------------------------------------------------------
class Worker(QThread):
    done = pyqtSignal(object)        # ส่งผลลัพธ์
    failed = pyqtSignal(str)         # ส่งข้อความ error
    progress = pyqtSignal(str, int)  # (ข้อความ, เปอร์เซ็นต์)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.done.emit(result)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Supervisor — เฝ้าการเชื่อมต่อ + ต่อใหม่อัตโนมัติเมื่อหลุด
# ---------------------------------------------------------------------------
class ConnectionSupervisor(QThread):
    """
    เปิดหน้าต่างมิเรอร์แล้วเฝ้าไว้:
      - ถ้า scrcpy ปิดเองแต่ adb ยังเห็นอุปกรณ์ = ผู้ใช้ปิดหน้าต่างเอง -> หยุด
      - ถ้า scrcpy ปิดและอุปกรณ์หายไป = หลุดจริง -> เชื่อมต่อใหม่ (มี backoff) แล้วเปิดมิเรอร์ใหม่
    """
    status = pyqtSignal(str, str)   # (state, message); state: live|reconnecting|stopped|gaveup

    MAX_ATTEMPTS = 40
    POLL_SEC = 1.5
    MIN_LIVE_SEC = 3.0   # ถ้าหน้าต่างอยู่ได้นานกว่านี้แล้วถูกปิดทั้งที่อุปกรณ์ยังต่ออยู่ = ผู้ใช้ปิดเอง

    def __init__(self, mgr, target: str, title: str, extra: list[str]):
        super().__init__()
        self.mgr = mgr
        self.target = target
        self.title = title
        self.extra = extra
        self.proc = None
        self._launched_at = 0.0
        self._stop = threading.Event()

    # -- ควบคุมจากภายนอก -------------------------------------------------
    def stop(self):
        """ผู้ใช้สั่งหยุด session"""
        self._stop.set()
        self._kill_proc()

    # -- ลูปหลัก ---------------------------------------------------------
    def run(self):
        self._launch()
        attempts = 0
        while not self._stop.is_set():
            if self._stop.wait(self.POLL_SEC):
                break

            if self.proc and self.proc.poll() is None:
                attempts = 0            # ยังแคสอยู่ปกติ
                continue

            # scrcpy ปิดไปแล้ว — แยกแยะสาเหตุ
            lived = time.monotonic() - self._launched_at
            connected = self._device_connected()

            if connected and lived >= self.MIN_LIVE_SEC:
                # อุปกรณ์ยังต่ออยู่ + เปิดมานานพอ = ผู้ใช้ปิดหน้าต่างเอง
                self.status.emit("stopped", "ปิดหน้าต่างมิเรอร์แล้ว — หยุดแคส")
                break

            attempts += 1
            if attempts > self.MAX_ATTEMPTS:
                self.status.emit("gaveup", "🔴 เชื่อมต่อใหม่ไม่สำเร็จหลายครั้ง — หยุดแล้ว")
                break

            if connected:
                # อุปกรณ์ยังอยู่แต่ scrcpy ปิดเร็วผิดปกติ → แค่เปิดมิเรอร์ใหม่
                self.status.emit("reconnecting", f"⚠️ มิเรอร์หลุด — กำลังเปิดใหม่ (ครั้งที่ {attempts})...")
                self._launch()
            else:
                # หลุดจริง → ต่อ adb ใหม่ก่อน
                self.status.emit(
                    "reconnecting",
                    f"🔴 หลุด — กำลังเชื่อมต่อใหม่ ครั้งที่ {attempts}/{self.MAX_ATTEMPTS}...",
                )
                if self._try_reconnect():
                    self._launch()
                else:
                    # backoff แบบค่อย ๆ ถี่ห่างขึ้น (สูงสุด ~12 วิ)
                    self._stop.wait(min(2 + attempts, 12))

    # -- ภายใน -----------------------------------------------------------
    def _launch(self):
        try:
            self.proc = self.mgr.mirror(self.target, title=self.title, extra=self.extra)
            self._launched_at = time.monotonic()
            self.status.emit("live", f"🟢 กำลังแคส {self.target}")
        except Exception as e:  # noqa: BLE001
            self.status.emit("gaveup", f"เปิดมิเรอร์ไม่สำเร็จ: {e}")
            self._stop.set()

    def _device_connected(self) -> bool:
        try:
            return any(
                d.serial == self.target and d.state == "device"
                for d in self.mgr.list_devices()
            )
        except Exception:  # noqa: BLE001
            return False

    def _try_reconnect(self) -> bool:
        try:
            self.mgr.disconnect(self.target)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.mgr.connect(self.target)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _kill_proc(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# สไตล์ (QSS) ธีมดำชมพูแบบ TikTok
# ---------------------------------------------------------------------------
STYLE = """
* { font-family: 'Segoe UI', 'Leelawadee UI', sans-serif; color: #f1f1f1; }
QWidget#root { background: #0e0e10; }
QLabel#title { font-size: 26px; font-weight: 800; }
QLabel#subtitle { color: #9aa0a6; font-size: 13px; }
QLabel#sectionTitle { font-size: 16px; font-weight: 700; }
QLabel#hint { color: #9aa0a6; font-size: 12px; }
QLabel#statusDot { font-size: 13px; }
QFrame#card {
    background: #18181b; border: 1px solid #26262b; border-radius: 16px;
}
QLineEdit {
    background: #232328; border: 1px solid #34343b; border-radius: 10px;
    padding: 11px 12px; font-size: 14px;
}
QLineEdit:focus { border: 1px solid #fe2c55; }
QPushButton#primary {
    background: #fe2c55; border: none; border-radius: 12px;
    padding: 13px; font-size: 15px; font-weight: 700;
}
QPushButton#primary:hover { background: #ff4d70; }
QPushButton#primary:disabled { background: #5a2330; color: #b98; }
QPushButton#ghost {
    background: transparent; border: 1px solid #34343b; border-radius: 10px;
    padding: 9px 14px; font-size: 13px;
}
QPushButton#ghost:hover { background: #232328; }
QPushButton#tab {
    background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 10px 6px; font-size: 14px; font-weight: 600; color: #9aa0a6;
}
QPushButton#tab:checked { color: #ffffff; border-bottom: 2px solid #fe2c55; }
QProgressBar {
    background: #232328; border: none; border-radius: 6px; height: 8px; text-align: center;
}
QProgressBar::chunk { background: #fe2c55; border-radius: 6px; }
QFrame#liveBar {
    background: #14241b; border: 1px solid #1f5138; border-radius: 12px;
}
QLabel#liveText { font-size: 13px; font-weight: 600; }
QPushButton#stop {
    background: #2a2a30; border: 1px solid #44444c; border-radius: 9px;
    padding: 8px 16px; font-size: 13px; font-weight: 700;
}
QPushButton#stop:hover { background: #3a2326; border: 1px solid #fe2c55; }
"""


def make_qr_pixmap(data: str, size: int = 190) -> QPixmap:
    qr = qrcode.QRCode(border=2, box_size=8)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0e0e10", back_color="#ffffff").convert("RGB")
    w, h = img.size
    qimg = QImage(img.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


# ---------------------------------------------------------------------------
# หน้าต่างหลัก
# ---------------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.mgr = ScrcpyManager()
        self.settings = load_settings()
        self.worker: Worker | None = None
        self.supervisor: ConnectionSupervisor | None = None

        self.setObjectName("root")
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(560, 720))
        self._build_ui()
        self._refresh_status()

        # เตรียมเครื่องมือ (ดาวน์โหลด scrcpy ถ้ายังไม่มี)
        if not self.mgr.is_ready:
            self._download_tools()
        else:
            self._set_busy(False, "พร้อมใช้งาน scrcpy แล้ว")

    # ----------------------------------------------------------------- build
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 24)
        root.setSpacing(16)

        # header
        title = QLabel("📡 ScreenCast Studio")
        title.setObjectName("title")
        subtitle = QLabel("แคสหน้าจอ Android ขึ้น PC แบบไร้สาย")
        subtitle.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        # status row
        status_row = QHBoxLayout()
        self.status_dot = QLabel("● กำลังเตรียม...")
        self.status_dot.setObjectName("statusDot")
        self.pc_ip = QLabel(f"PC: {local_ip()}")
        self.pc_ip.setObjectName("hint")
        status_row.addWidget(self.status_dot)
        status_row.addStretch(1)
        status_row.addWidget(self.pc_ip)
        root.addLayout(status_row)

        # progress (ตอนดาวน์โหลด/ทำงาน)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        root.addWidget(self.progress)

        # tabs
        tab_row = QHBoxLayout()
        tab_row.setSpacing(18)
        self.tab_wifi = QPushButton("📶  WiFi (ไร้สาย)")
        self.tab_usb = QPushButton("🔌  USB (ครั้งแรกง่ายสุด)")
        for i, t in enumerate((self.tab_wifi, self.tab_usb)):
            t.setObjectName("tab")
            t.setCheckable(True)
            t.clicked.connect(lambda _, idx=i: self._switch_tab(idx))
        self.tab_wifi.setChecked(True)
        tab_row.addWidget(self.tab_wifi)
        tab_row.addWidget(self.tab_usb)
        tab_row.addStretch(1)
        root.addLayout(tab_row)

        # stacked pages
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_wifi_page())
        self.stack.addWidget(self._build_usb_page())
        root.addWidget(self.stack, 1)

        # live bar (โผล่เฉพาะตอนกำลังแคส)
        self.live_bar = QFrame()
        self.live_bar.setObjectName("liveBar")
        lb = QHBoxLayout(self.live_bar)
        lb.setContentsMargins(14, 10, 12, 10)
        self.live_text = QLabel("")
        self.live_text.setObjectName("liveText")
        self.live_text.setWordWrap(True)
        self.btn_stop = QPushButton("หยุดแคส")
        self.btn_stop.setObjectName("stop")
        self.btn_stop.clicked.connect(self._stop_session)
        lb.addWidget(self.live_text, 1)
        lb.addWidget(self.btn_stop)
        self.live_bar.hide()
        root.addWidget(self.live_bar)

        # log line
        self.log = QLabel("")
        self.log.setObjectName("hint")
        self.log.setWordWrap(True)
        root.addWidget(self.log)

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(12)
        return card, lay

    def _build_wifi_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(14)

        # การ์ดเชื่อมต่อด่วน (อุปกรณ์ที่จำไว้)
        last = self.settings.get("last_wifi_target")
        if last:
            card, lay = self._card()
            lay.addWidget(self._h("⚡ เชื่อมต่อด่วน (อุปกรณ์ที่เคยใช้)"))
            lbl = QLabel(last)
            lbl.setObjectName("hint")
            lay.addWidget(lbl)
            btn = QPushButton("เชื่อมต่อ & แคสเลย")
            btn.setObjectName("primary")
            btn.clicked.connect(lambda: self._wifi_quick_connect(last))
            lay.addWidget(btn)
            outer.addWidget(card)

        # การ์ดจับคู่ครั้งแรก
        card, lay = self._card()
        lay.addWidget(self._h("🔗 จับคู่ครั้งแรก (Android 11+)"))
        steps = QLabel(
            "1. มือถือ → Settings → Developer options → Wireless debugging → เปิด\n"
            "2. แตะ \"Pair device with pairing code\"\n"
            "3. เอา IP:PORT และรหัส 6 หลัก ที่ขึ้นมากรอกด้านล่าง"
        )
        steps.setObjectName("hint")
        lay.addWidget(steps)

        self.in_pair_addr = QLineEdit()
        self.in_pair_addr.setPlaceholderText("IP:PORT สำหรับจับคู่  เช่น 192.168.1.50:37419")
        self.in_pair_code = QLineEdit()
        self.in_pair_code.setPlaceholderText("รหัสจับคู่ 6 หลัก  เช่น 123456")
        lay.addWidget(self.in_pair_addr)
        lay.addWidget(self.in_pair_code)

        self.btn_pair = QPushButton("จับคู่ & เชื่อมต่อ & แคส")
        self.btn_pair.setObjectName("primary")
        self.btn_pair.clicked.connect(self._wifi_pair_connect)
        lay.addWidget(self.btn_pair)
        outer.addWidget(card)

        outer.addStretch(1)
        return page

    def _build_usb_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(14)

        card, lay = self._card()
        lay.addWidget(self._h("🔌 เสียบ USB ครั้งเดียว → ใช้ไร้สายต่อ"))
        steps = QLabel(
            "1. เปิด Developer options → USB debugging\n"
            "2. เสียบสาย USB เข้ากับ PC แล้วอนุญาตบนมือถือ\n"
            "3. กดปุ่มด้านล่าง — แอปจะเปิดโหมดไร้สายให้ แล้วถอดสายได้เลย"
        )
        steps.setObjectName("hint")
        lay.addWidget(steps)

        btn_scan = QPushButton("ตรวจหาอุปกรณ์ USB")
        btn_scan.setObjectName("ghost")
        btn_scan.clicked.connect(self._usb_scan)
        lay.addWidget(btn_scan)

        self.usb_info = QLabel("ยังไม่พบอุปกรณ์")
        self.usb_info.setObjectName("hint")
        lay.addWidget(self.usb_info)

        self.btn_usb_go = QPushButton("เปิดไร้สาย & แคสเลย")
        self.btn_usb_go.setObjectName("primary")
        self.btn_usb_go.setEnabled(False)
        self.btn_usb_go.clicked.connect(self._usb_go_wireless)
        lay.addWidget(self.btn_usb_go)
        outer.addWidget(card)

        outer.addStretch(1)
        return page

    def _h(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionTitle")
        return lbl

    # ---------------------------------------------------------------- helpers
    def _switch_tab(self, idx: int):
        self.tab_wifi.setChecked(idx == 0)
        self.tab_usb.setChecked(idx == 1)
        self.stack.setCurrentIndex(idx)

    def _set_busy(self, busy: bool, msg: str = ""):
        for b in (getattr(self, "btn_pair", None), getattr(self, "btn_usb_go", None)):
            if b:
                b.setEnabled(not busy)
        if msg:
            self.log.setText(msg)

    def _refresh_status(self):
        if self.mgr.is_ready:
            self.status_dot.setText("● พร้อมใช้งาน")
            self.status_dot.setStyleSheet("color:#36d399;")
        else:
            self.status_dot.setText("● กำลังเตรียมเครื่องมือ...")
            self.status_dot.setStyleSheet("color:#fbbd23;")

    def _toast(self, title: str, msg: str, icon=QMessageBox.Icon.Information):
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(msg)
        box.exec()

    def _run(self, fn, *args, on_done=None, busy_msg="กำลังทำงาน...", **kwargs):
        """เรียกงาน blocking ใน worker thread"""
        self._set_busy(True, busy_msg)
        self.worker = Worker(fn, *args, **kwargs)
        if on_done:
            self.worker.done.connect(on_done)
        self.worker.done.connect(lambda *_: self._set_busy(False))
        self.worker.failed.connect(self._on_fail)
        self.worker.progress.connect(self._on_progress)
        self.worker.start()

    def _on_fail(self, msg: str):
        self._set_busy(False)
        self.progress.hide()
        self._refresh_status()
        self._toast("เกิดข้อผิดพลาด", msg, QMessageBox.Icon.Warning)

    def _on_progress(self, msg: str, pct: int):
        self.progress.show()
        self.progress.setValue(pct)
        self.log.setText(msg)

    # ------------------------------------------------------------- tool setup
    def _download_tools(self):
        self.progress.show()
        self.worker = Worker(self.mgr.ensure_tools, self._emit_progress)
        self.worker.done.connect(self._tools_ready)
        self.worker.failed.connect(self._on_fail)
        self.worker.start()

    def _emit_progress(self, msg: str, pct: int):
        # ถูกเรียกจาก worker thread -> ส่งสัญญาณกลับ main
        if self.worker:
            self.worker.progress.emit(msg, pct)

    def _tools_ready(self, _):
        self.progress.hide()
        self.mgr.start_server()
        self._refresh_status()
        self._set_busy(False, "พร้อมใช้งานแล้ว — เลือกวิธีเชื่อมต่อด้านบน")

    # ------------------------------------------------------------------- WiFi
    def _wifi_pair_connect(self):
        addr = self.in_pair_addr.text().strip()
        code = self.in_pair_code.text().strip()
        if not addr or not code:
            self._toast("ข้อมูลไม่ครบ", "กรุณากรอก IP:PORT และรหัสจับคู่", QMessageBox.Icon.Warning)
            return

        def task():
            self.mgr.pair(addr, code)
            # หา target สำหรับเชื่อมต่อ: ลอง mDNS ก่อน, ถ้าไม่ได้ใช้ IP เดิม:5555
            target = self.mgr.mdns_connect_target()
            if not target:
                ip = addr.split(":")[0]
                target = f"{ip}:5555"
            self.mgr.connect(target)
            return target

        self._run(task, on_done=self._after_connect, busy_msg="กำลังจับคู่และเชื่อมต่อ...")

    def _wifi_quick_connect(self, target: str):
        def task():
            self.mgr.connect(target)
            return target
        self._run(task, on_done=self._after_connect, busy_msg=f"กำลังเชื่อมต่อ {target}...")

    def _after_connect(self, target: str):
        self.settings["last_wifi_target"] = target
        save_settings(self.settings)
        self.log.setText(f"เชื่อมต่อสำเร็จ: {target} — กำลังเปิดหน้าจอ...")
        self._start_session(target)

    # -------------------------------------------------------------------- USB
    def _usb_scan(self):
        def task():
            self.mgr.start_server()
            return [d for d in self.mgr.list_devices() if not d.is_wireless and d.state == "device"]
        self._run(task, on_done=self._usb_found, busy_msg="กำลังตรวจหาอุปกรณ์ USB...")

    def _usb_found(self, devices):
        if not devices:
            self.usb_info.setText("ไม่พบอุปกรณ์ — เช็คสาย/อนุญาต USB debugging บนมือถือ")
            self.btn_usb_go.setEnabled(False)
            self._usb_device = None
            return
        d = devices[0]
        self._usb_device = d
        self.usb_info.setText(f"พบ: {d.label}  [{d.serial}]")
        self.btn_usb_go.setEnabled(True)

    def _usb_go_wireless(self):
        d = getattr(self, "_usb_device", None)
        if not d:
            return

        def task():
            ip = self.mgr.device_ip(d.serial)
            if not ip:
                raise ToolError("หา IP ของมือถือไม่เจอ — ต่อ WiFi วงเดียวกับ PC ก่อน")
            self.mgr.enable_tcpip(d.serial, 5555)
            import time
            time.sleep(1.2)
            target = f"{ip}:5555"
            self.mgr.connect(target)
            return target

        self._run(task, on_done=self._after_connect, busy_msg="กำลังเปิดโหมดไร้สาย...")

    # ------------------------------------------------------- mirror session
    def _start_session(self, target: str):
        """เริ่มแคส + เปิด supervisor ที่จะต่อใหม่อัตโนมัติเมื่อหลุด"""
        self._stop_session()  # เคลียร์ session เก่า (ถ้ามี)
        title = f"{APP_NAME} — {target}"
        self.supervisor = ConnectionSupervisor(self.mgr, target, title, MIRROR_EXTRA)
        self.supervisor.status.connect(self._on_session_status)
        self.supervisor.finished.connect(self._on_session_finished)
        self.supervisor.start()
        self.live_bar.show()

    def _stop_session(self):
        sup = self.supervisor
        if sup and sup.isRunning():
            sup.stop()
            sup.wait(4000)
        self.supervisor = None
        self.live_bar.hide()

    def _on_session_status(self, state: str, message: str):
        self.live_text.setText(message)
        if state == "live":
            self.live_bar.setStyleSheet("")            # ใช้ธีมเขียวปกติ
            self.btn_stop.setEnabled(True)
        elif state == "reconnecting":
            self.live_bar.setStyleSheet(
                "QFrame#liveBar{background:#2a1418;border:1px solid #fe2c55;border-radius:12px;}"
            )
        elif state in ("stopped", "gaveup"):
            self.log.setText(message)

    def _on_session_finished(self):
        # supervisor จบลูปแล้ว (ผู้ใช้ปิดหน้าต่าง / ยอมแพ้ / สั่งหยุด)
        self.live_bar.hide()
        self.live_bar.setStyleSheet("")

    def closeEvent(self, event):
        self._stop_session()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
