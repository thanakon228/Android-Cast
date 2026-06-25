# งานสำหรับ Claude Code (ห้ามใช้ Cursor แก้โค้ด)

## Branch
- **ชื่อ:** `feature/agent-review-improvements`
- **ฐาน:** `origin/AutoMation`
- **ห้าม** merge ไป `main` — ผู้ใช้จะ review/merge เอง

## ข้อเสนอจาก Agent Review (ทำครบ)

| # | ไฟล์ | งาน |
|---|------|-----|
| 1 | `plugin_api.py` | `find_all_templates`, `wait_for_template` |
| 2 | `scrcpy_manager.py` | screencap cache TTL ~150ms, invalidate หลัง input |
| 3 | `ai_providers.py` | OCR stub + `register_builtin_providers` ใน `plugin_manager.py` |
| 4 | `plugins/macro_recorder.py` | เล่น actions จาก config |
| 5 | `bot_http_api.py` | REST เล็ก ๆ บน localhost |
| 6 | `app.py` | F5/F6 hotkey, confirm dialog ปลั๊กอิน, toggle HTTP API |
| 7 | `plugins/README.md` | เอกสาร API ใหม่ |

## คำสั่งรัน (เมื่อ quota reset แล้ว)

```powershell
cd C:\Users\thana\Android-Cast
git checkout -B feature/agent-review-improvements origin/AutoMation
claude -p --dangerously-skip-permissions "$(Get-Content CLAUDE_TASK.md -Raw)"
```

หรือรออัตโนมัติ:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\claude-implement-review.ps1
```

## หลังเสร็จ

```powershell
git push -u origin feature/agent-review-improvements
```

สร้าง PR บน GitHub: `feature/agent-review-improvements` → `main` (ผู้ใช้กด merge เอง)
