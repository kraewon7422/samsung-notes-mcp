# ──────────────────────────────────────────────────────────────
# 삼성 노트 × Claude — 원클릭 설치 스크립트
# (설치하기.bat 가 이 파일을 실행합니다)
# ──────────────────────────────────────────────────────────────
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPy = Join-Path $here "server.py"

function Step($msg)  { Write-Host ""; Write-Host "▶ $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "  ✅ $msg" -ForegroundColor Green }
function Fail($msg)  { Write-Host ""; Write-Host "❌ $msg" -ForegroundColor Red }

Write-Host "=============================================" -ForegroundColor Yellow
Write-Host "   삼성 노트 × Claude 설치를 시작합니다"        -ForegroundColor Yellow
Write-Host "=============================================" -ForegroundColor Yellow

# ── 1. 삼성 노트 앱 확인 ─────────────────────────────────────
Step "삼성 노트 Windows 앱 확인"
$pkg = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -Filter "SAMSUNGELECTRONICSCoLtd.SamsungNotes_*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $pkg) {
    Fail "삼성 노트 앱이 설치되어 있지 않습니다."
    Write-Host "   1) Microsoft Store에서 'Samsung Notes'를 설치하세요"
    Write-Host "   2) 앱을 열고 삼성 계정으로 로그인해 노트가 보이는지 확인하세요"
    Write-Host "   3) 그 다음 이 설치를 다시 실행하세요"
    exit 1
}
$db = Join-Path $pkg.FullName "LocalState\Storage.sqlite"
if (-not (Test-Path $db)) {
    Fail "삼성 노트 앱은 있지만 노트 데이터가 없습니다."
    Write-Host "   삼성 노트 앱을 열고 삼성 계정 로그인 + 동기화를 마친 뒤 다시 실행하세요."
    exit 1
}
Ok "삼성 노트 데이터 발견"

# ── 2. Python 확인 (없으면 설치) ─────────────────────────────
Step "Python 확인"
$python = $null
foreach ($cand in @("python", "py")) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $v = & $cmd.Source --version 2>$null
            if ($v -match "Python 3\.(\d+)") {
                if ([int]$Matches[1] -ge 10) { $python = $cmd.Source; break }
            }
        } catch {}
    }
}
if (-not $python) {
    Write-Host "  Python이 없어서 자동으로 설치합니다 (1~2분)..."
    $winget = "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe"
    if (-not (Test-Path $winget)) { $winget = "winget" }
    & $winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    Write-Host ""
    Write-Host "  Python 설치가 끝났습니다." -ForegroundColor Yellow
    Write-Host "  ⚠ 이 창을 닫고 '설치하기.bat'를 한 번 더 실행해 주세요. (경로 갱신 때문)" -ForegroundColor Yellow
    exit 0
}
Ok "Python 발견: $python"

# ── 3. 필요한 패키지 설치 ────────────────────────────────────
Step "필요한 구성요소 설치 (mcp, pillow)"
& $python -m pip install --quiet --upgrade "mcp[cli]" pillow
Ok "구성요소 설치 완료"

# ── 4. 동작 자가 테스트 ──────────────────────────────────────
Step "내 노트 읽기 테스트"
$env:PYTHONIOENCODING = "utf-8"
$env:SN_HERE = $here
$test = & $python -c "import sys, os, json; sys.path.insert(0, os.environ['SN_HERE']); import server; d = json.loads(server.samsung_notes_list_folders()); print(d['folder_count'])"
if ($LASTEXITCODE -ne 0) {
    Fail "노트 읽기 테스트가 실패했습니다. 삼성 노트 앱에서 동기화가 됐는지 확인하세요."
    exit 1
}
Ok "노트 폴더 $test 개 확인 — 정상 동작!"

# ── 5. Claude Desktop 등록 ───────────────────────────────────
Step "Claude Desktop에 등록"
if (Test-Path "$env:APPDATA\Claude") {
    $env:SN_SERVER = $serverPy
    $env:SN_PY = $python
    & $python -c @"
import json, os, pathlib
p = pathlib.Path(os.environ['APPDATA']) / 'Claude' / 'claude_desktop_config.json'
cfg = json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}
cfg.setdefault('mcpServers', {})['samsung-notes'] = {
    'command': os.environ['SN_PY'], 'args': [os.environ['SN_SERVER']]}
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
"@
    Ok "Claude Desktop 등록 완료 (Claude Desktop을 껐다 켜세요)"
} else {
    Write-Host "  ℹ Claude Desktop이 없는 것 같아 건너뜁니다. (https://claude.ai/download)"
}

# ── 6. Claude Code 등록 (있으면) ─────────────────────────────
Step "Claude Code에 등록"
$claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
if ($claudeCmd) {
    # PowerShell이 인자를 직접 전달 — 경로에 공백/한글이 있어도 안전
    try { & $claudeCmd.Source mcp remove --scope user samsung-notes *> $null } catch {}
    & $claudeCmd.Source mcp add --scope user samsung-notes -- $python $serverPy
    if ($LASTEXITCODE -eq 0) {
        Ok "Claude Code 등록 완료 (새 세션부터 사용 가능)"
    } else {
        Write-Host "  ⚠ Claude Code 등록이 실패했습니다. Claude Code에서 직접 실행해 보세요:" -ForegroundColor Yellow
        Write-Host "    claude mcp add --scope user samsung-notes -- `"$python`" `"$serverPy`""
    }
} else {
    Write-Host "  ℹ Claude Code가 없는 것 같아 건너뜁니다."
}

# ── 완료 ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "=============================================" -ForegroundColor Green
Write-Host "   🎉 설치 완료!"                               -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Claude Desktop을 재시작한 뒤 이렇게 말해보세요:"
Write-Host '   "내 삼성 노트 폴더 보여줘"'
Write-Host '   "수학 노트에서 이차방정식 검색해줘"'
Write-Host '   "○○ 노트 첫 페이지 보여줘"  ← 손글씨도 보여요'
Write-Host ""
Write-Host "⚠ 주의: 이 폴더를 옮기면 등록이 끊깁니다. 옮겼다면 설치하기.bat를 다시 실행하세요."
