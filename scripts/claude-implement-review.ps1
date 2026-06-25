# Run implementation via Claude Code only - waits for quota reset then pushes branch
# Usage: powershell -ExecutionPolicy Bypass -File scripts\claude-implement-review.ps1

$ErrorActionPreference = "Stop"
$Repo = "C:\Users\thana\Android-Cast"
$Branch = "feature/agent-review-improvements"
$Log = Join-Path $Repo "scripts\claude-run.log"

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

Set-Location $Repo

Write-Log "Checking Claude Code quota..."
$maxWaitMin = 120
$waited = 0
while ($waited -lt $maxWaitMin) {
    $test = claude -p "reply OK only" 2>&1 | Out-String
    if ($test -notmatch "session limit|rate limit|rate_limit") {
        Write-Log "Claude Code is available"
        break
    }
    Write-Log "Rate limited - waiting 5 min ($waited / $maxWaitMin min)"
    Start-Sleep -Seconds 300
    $waited += 5
}
if ($waited -ge $maxWaitMin) {
    Write-Log "ERROR: timed out after $maxWaitMin minutes"
    exit 1
}

git fetch origin
if (-not (git branch --list $Branch)) {
    git checkout -b $Branch origin/AutoMation
} else {
    git checkout $Branch
    git pull --ff-only origin $Branch 2>$null
}

$taskFile = Join-Path $Repo "CLAUDE_TASK.md"
if (-not (Test-Path $taskFile)) {
    Write-Log "ERROR: CLAUDE_TASK.md not found"
    exit 1
}
$Prompt = Get-Content $taskFile -Raw -Encoding UTF8

Write-Log "Starting Claude Code implementation..."
claude -p --dangerously-skip-permissions $Prompt 2>&1 | Tee-Object -FilePath $Log -Append
if ($LASTEXITCODE -ne 0) {
    Write-Log "ERROR: claude exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Log "Done"
git status -sb
git log -1 --oneline
