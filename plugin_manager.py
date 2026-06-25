"""
plugin_manager.py
=================
ค้นหา / โหลด / รัน / หยุด ปลั๊กอินบอท

การค้นหา (discovery):
  สแกนโฟลเดอร์ plugins/ หา
    - ไฟล์เดี่ยว  เช่น  plugins/auto_tap.py
    - แพ็กเกจ     เช่น  plugins/my_bot/__init__.py
  แล้วหา "คลาสที่สืบทอดจาก BotPlugin" ในแต่ละโมดูล (ตัวแรกที่เจอ)

การรัน:
  แต่ละบอทรันใน PluginRunner (QThread) แยกจาก UI — สื่อสารกลับด้วย signal
  ผู้ใช้สั่งหยุดผ่าน threading.Event (ctx.should_stop())
"""
from __future__ import annotations

import importlib.util
import inspect
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from plugin_api import AIRegistry, BotContext, BotPlugin, PluginMeta


@dataclass
class LoadedPlugin:
    """ผลการค้นพบปลั๊กอิน 1 ตัว"""
    key: str                       # ใช้เป็น id ภายใน (มาจากชื่อไฟล์/โฟลเดอร์)
    meta: PluginMeta
    cls: Optional[type]            # คลาส BotPlugin (None ถ้าโหลดพลาด)
    source: Path
    error: str = ""                # ข้อความ error ถ้าโหลดไม่สำเร็จ

    @property
    def ok(self) -> bool:
        return self.cls is not None and not self.error


class PluginRunner(QThread):
    """รันบอท 1 ตัวในเธรดแยก"""
    log_line = pyqtSignal(str)            # ข้อความ log (พร้อม prefix ชื่อบอท)
    state_changed = pyqtSignal(str, str)  # (plugin_key, state) state: running|stopped|error

    def __init__(self, key: str, plugin: BotPlugin, ctx: BotContext,
                 stop_event: threading.Event):
        super().__init__()
        self.key = key
        self.plugin = plugin
        self.ctx = ctx
        self._stop = stop_event

    def request_stop(self):
        self._stop.set()

    def run(self):
        name = self.plugin.meta.name
        self.state_changed.emit(self.key, "running")
        self.log_line.emit(f"▶️ เริ่มบอท: {name}")
        try:
            self.plugin.run(self.ctx)
            self.log_line.emit(f"✅ บอทจบการทำงาน: {name}")
            self.state_changed.emit(self.key, "stopped")
        except Exception:  # noqa: BLE001
            self.log_line.emit(f"💥 บอท {name} ขัดข้อง:\n{traceback.format_exc()}")
            self.state_changed.emit(self.key, "error")
        finally:
            try:
                self.plugin.on_stop()
            except Exception:  # noqa: BLE001
                pass


class PluginManager:
    """จัดการวงจรชีวิตปลั๊กอินทั้งหมด"""

    def __init__(self, plugins_dir: Path, mgr, logger, config_store: dict,
                 save_settings_cb):
        self.dir = Path(plugins_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mgr = mgr                       # ScrcpyManager
        self.logger = logger                 # callable(str) -> console
        self.ai = AIRegistry()               # ทะเบียน AI ส่วนกลาง
        # config ต่อปลั๊กอิน เก็บใน settings.json ใต้คีย์ "plugins"
        self._config_store = config_store    # dict {key: {...}}
        self._save_settings = save_settings_cb
        self.runners: dict[str, PluginRunner] = {}
        # ให้ปลั๊กอิน import โมดูลข้าง ๆ กันได้
        if str(self.dir) not in sys.path:
            sys.path.insert(0, str(self.dir))

    # ------------------------------------------------------------- discovery
    def discover(self) -> list[LoadedPlugin]:
        found: list[LoadedPlugin] = []
        for entry in sorted(self.dir.iterdir()):
            if entry.name.startswith(("_", ".")):
                continue
            if entry.is_file() and entry.suffix == ".py":
                found.append(self._load_module(entry.stem, entry))
            elif entry.is_dir() and (entry / "__init__.py").exists():
                found.append(self._load_module(entry.name, entry / "__init__.py"))
        return found

    def _load_module(self, key: str, path: Path) -> LoadedPlugin:
        try:
            mod_name = f"sc_plugin_{key}"
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            assert spec and spec.loader
            spec.loader.exec_module(module)
            cls = self._find_plugin_class(module)
            if cls is None:
                return LoadedPlugin(key, PluginMeta(name=key), None, path,
                                    error="ไม่พบคลาสที่สืบทอดจาก BotPlugin")
            meta = getattr(cls, "meta", None) or PluginMeta(name=key)
            return LoadedPlugin(key, meta, cls, path)
        except Exception:  # noqa: BLE001
            return LoadedPlugin(key, PluginMeta(name=key), None, path,
                                error=traceback.format_exc())

    @staticmethod
    def _find_plugin_class(module) -> Optional[type]:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (issubclass(obj, BotPlugin) and obj is not BotPlugin
                    and obj.__module__ == module.__name__):
                return obj
        return None

    # ------------------------------------------------------------- lifecycle
    def is_running(self, key: str) -> bool:
        r = self.runners.get(key)
        return bool(r and r.isRunning())

    def start(self, loaded: LoadedPlugin, serial: str) -> PluginRunner:
        if self.is_running(loaded.key):
            raise RuntimeError("บอทนี้กำลังทำงานอยู่")
        if not loaded.ok:
            raise RuntimeError(loaded.error or "ปลั๊กอินโหลดไม่สำเร็จ")
        if not serial:
            raise RuntimeError("ยังไม่มีอุปกรณ์ที่เชื่อมต่อ — ต่อมือถือก่อน")

        plugin: BotPlugin = loaded.cls()           # type: ignore[call-arg]
        stop_event = threading.Event()
        config = self._config_store.setdefault(loaded.key, {})

        def _log(msg: str):
            self.logger(f"[{loaded.meta.name}] {msg}")

        def _save():
            self._save_settings()

        ctx = BotContext(self.mgr, serial, logger=_log, stop_event=stop_event,
                         config=config, save_config=_save, ai=self.ai)
        try:
            plugin.on_load(ctx)
        except Exception:  # noqa: BLE001
            _log("on_load ขัดข้อง: " + traceback.format_exc())

        runner = PluginRunner(loaded.key, plugin, ctx, stop_event)
        self.runners[loaded.key] = runner
        return runner

    def stop(self, key: str, wait_ms: int = 4000) -> None:
        r = self.runners.get(key)
        if r and r.isRunning():
            r.request_stop()
            r.wait(wait_ms)

    def stop_all(self) -> None:
        for key in list(self.runners):
            self.stop(key)
