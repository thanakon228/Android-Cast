"""เก็บการตั้งค่าเล็กๆ เช่น อุปกรณ์ไร้สายล่าสุด ไว้ที่ settings.json"""
from __future__ import annotations

import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent / "settings.json"


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_settings(data: dict) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
