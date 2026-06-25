# รันงานด้วย Claude Code เท่านั้น — รอจน quota reset แล้ว implement + push branch
# ใช้: powershell -ExecutionPolicy Bypass -File scripts\claude-implement-review.ps1

$ErrorActionPreference = "Stop"
$Repo = "C:\Users\thana\Android-Cast"
$Branch = "feature/agent-review-improvements"
$Log = Join-Path $Repo "scripts\claude-run.log"

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line
}

Set-Location $Repo

# --- รอจน Claude Code ใช้ได้ ---
Write-Log "เช็ค quota Claude Code..."
$maxWaitMin = 120
$waited = 0
while ($waited -lt $maxWaitMin) {
    $test = claude -p "ตอบคำเดียว: OK" 2>&1 | Out-String
    if ($test -notmatch "session limit|rate limit|rate_limit") {
        Write-Log "Claude Code พร้อมใช้งาน"
        break
    }
    Write-Log "ยังโดน limit — รอ 5 นาที... ($waited/$maxWaitMin นาที)"
    Start-Sleep -Seconds 300
    $waited += 5
}
if ($waited -ge $maxWaitMin) {
    Write-Log "ERROR: รอเกิน $maxWaitMin นาที — หยุด"
    exit 1
}

# --- เตรียม branch ---
git fetch origin
if (-not (git branch --list $Branch)) {
    git checkout -b $Branch origin/AutoMation
} else {
    git checkout $Branch
    git reset --hard origin/AutoMation
}

$Prompt = @'
คุณอยู่ใน repo Android-Cast branch feature/agent-review-improvements (แยกจาก main)

ทำตามข้อเสนอจาก code review นี้ทั้งหมด แล้ว commit + push ขึ้น GitHub branch เดิม (ห้าม merge main):

1. plugin_api.py — เพิ่ม find_all_templates, wait_for_template ใน Vision
2. scrcpy_manager.py — cache screencap สั้น ๆ + invalidate หลัง tap/swipe
3. ai_providers.py — OCR stub (pytesseract ถ้ามี) ลงทะเบียนใน plugin_manager
4. plugins/macro_recorder.py — เล่น macro จาก config (tap/swipe/key/text/wait_template)
5. bot_http_api.py — HTTP API เล็ก ๆ (GET /status, POST /start/<key>, POST /stop)
6. app.py — hotkey F5 เริ่มบอทล่าสุด, F6 หยุด; dialog ยืนยันก่อนรันปลั๊กอินครั้งแรก; เปิด HTTP API จากแท็บบอท (checkbox + port)
7. plugins/README.md — อัปเดต API ใหม่

กฎ:
- แก้เฉพาะที่จำเป็น อย่า over-engineer
- ทดสอบ syntax: python -m py_compile ไฟล์ที่แก้
- commit message ภาษาไทยหรืออังกฤษสั้น ๆ อธิบาย why
- push: git push -u origin feature/agent-review-improvements
- ห้าม merge หรือ push ไป main
'@

Write-Log "เริ่ม Claude Code session..."
claude -p --dangerously-skip-permissions $Prompt 2>&1 | Tee-Object -FilePath $Log -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: claude exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Log "เสร็จ — ตรวจ git status"
git status -sb
git log -1 --oneline
