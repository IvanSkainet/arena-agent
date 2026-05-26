# ============================================================================
# Arena Local Agent v1.5.0 — Windows Installer
# Proper background service via NSSM + Scheduled Task fallback
# Run as: powershell -ExecutionPolicy Bypass -File install_v150.ps1
# ============================================================================
$ErrorActionPreference = "Continue"
[Console::OutputEncoding] = [System.Text.Encoding]::UTF8

$VERSION = "1.5.0"
$HOME_DIR = $env:USERPROFILE
$BRIDGE_DIR = "$HOME_DIR\arena-local-bridge"
$AGENT_DIR = "$HOME_DIR\arena-agent"
$TOKEN_FILE = "$BRIDGE_DIR\token.txt"
$BIN_DIR = "$AGENT_DIR\bin"
$LOG_DIR = "$AGENT_DIR\logs"
$DASHBOARD_DIR = "$AGENT_DIR\dashboard"

function Ok($msg)   { Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Warn($msg) { Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Err($msg)  { Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $msg }
function Info($msg) { Write-Host "[INFO] " -ForegroundColor Cyan -NoNewline; Write-Host $msg }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Arena Local Agent - Unified Bridge v$VERSION" -ForegroundColor Cyan
Write-Host "  1 process, 1 port, background service" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 1. Find Python
# ============================================================================
$PYTHON = $null
$pythonCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
)
foreach ($p in $pythonCandidates) {
    if (Test-Path $p) { $PYTHON = $p; break }
}
if (-not $PYTHON) {
    $PYTHON = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if ($PYTHON) {
    $PY_VER = & $PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>$null
    Ok "Python: $PYTHON ($PY_VER)"
} else {
    Err "Python not found! Install Python 3.11+ and retry."
    exit 1
}

# ============================================================================
# 2. Install aiohttp if missing
# ============================================================================
Info "Checking aiohttp..."
$aiohttp_check = & $PYTHON -c "import aiohttp; print(aiohttp.__version__)" 2>$null
if (-not $aiohttp_check) {
    Info "Installing aiohttp..."
    & $PYTHON -m pip install aiohttp --quiet 2>$null
    $aiohttp_check = & $PYTHON -c "import aiohttp; print(aiohttp.__version__)" 2>$null
    if ($aiohttp_check) {
        Ok "aiohttp $aiohttp_check installed"
    } else {
        Err "Failed to install aiohttp. Run: pip install aiohttp"
        exit 1
    }
} else {
    Ok "aiohttp $aiohttp_check"
}

# ============================================================================
# 3. Create directories
# ============================================================================
Info "Creating directories..."
$dirs = @(
    $BRIDGE_DIR, $BIN_DIR, $LOG_DIR, $DASHBOARD_DIR,
    "$AGENT_DIR\memory", "$AGENT_DIR\missions", "$AGENT_DIR\reports\shots",
    "$AGENT_DIR\queue\inbox", "$AGENT_DIR\queue\running",
    "$AGENT_DIR\queue\done", "$AGENT_DIR\queue\failed",
    "$AGENT_DIR\tools", "$AGENT_DIR\hooks", "$AGENT_DIR\skills",
    "$AGENT_DIR\subagents", "$AGENT_DIR\agents", "$AGENT_DIR\backups",
    "$HOME_DIR\.arena-local-bridge"
)
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
Ok "Directories ready"

# ============================================================================
# 4. Deploy files
# ============================================================================
Info "Deploying v$VERSION files..."

$deployDir = $PSScriptRoot

# unified_bridge.py
$srcBridge = Join-Path $deployDir "unified_bridge.py"
if (Test-Path $srcBridge) {
    Copy-Item -Path $srcBridge -Destination "$BRIDGE_DIR\unified_bridge.py" -Force
    Ok "unified_bridge.py deployed"
} elseif (Test-Path "$BRIDGE_DIR\unified_bridge.py") {
    Warn "unified_bridge.py not in deploy dir, keeping existing"
} else {
    Err "unified_bridge.py not found!"
    exit 1
}

# index.html (dashboard)
$srcHtml = Join-Path $deployDir "index.html"
if (Test-Path $srcHtml) {
    Copy-Item -Path $srcHtml -Destination "$DASHBOARD_DIR\index.html" -Force
    Copy-Item -Path $srcHtml -Destination "$BRIDGE_DIR\index.html" -Force
    Ok "index.html deployed to dashboard + bridge dir"
} elseif (Test-Path "$DASHBOARD_DIR\index.html") {
    Warn "index.html not in deploy dir, keeping existing"
} else {
    Warn "index.html not found. Dashboard will use fallback."
}

# ============================================================================
# 5. Token
# ============================================================================
Info "Checking token..."
$token = $null
if (Test-Path $TOKEN_FILE) {
    $token = (Get-Content $TOKEN_FILE -First 1 -ErrorAction SilentlyContinue).Trim()
}
if (-not $token -or $token.Length -lt 16) {
    Info "Generating new token..."
    $token = & $PYTHON -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" 2>$null
    if ($token) {
        Set-Content -Path $TOKEN_FILE -Value $token -Encoding UTF8
        Ok "New token generated and saved"
    } else {
        Err "Failed to generate token"
        exit 1
    }
} else {
    Ok "Token exists ($($token.Length) chars)"
}

# ============================================================================
# 6. Stop existing bridge
# ============================================================================
Info "Stopping existing bridge..."
$bridgeProcesses = Get-Process -Name "python","pythonw","python3.14" -ErrorAction SilentlyContinue |
    Where-Object {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
            $cmdLine -match "unified_bridge"
        } catch { $false }
    }
if ($bridgeProcesses) {
    foreach ($proc in $bridgeProcesses) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Ok "Bridge stopped"
} else {
    Info "No running bridge found"
}

# ============================================================================
# 7. Create start script
# ============================================================================
$startScript = @'
$ErrorActionPreference = "Continue"
Set-Location "$env:USERPROFILE\arena-local-bridge"
$tokenFile = "$env:USERPROFILE\arena-local-bridge\token.txt"
$token = $null
if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -First 1 -ErrorAction SilentlyContinue).Trim()
}
if (-not $token -or $token.Length -lt 16) {
    $pythonExe = $null
    foreach ($p in @(
        "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    )) {
        if (Test-Path $p) { $pythonExe = $p; break }
    }
    if (-not $pythonExe) { $pythonExe = "python" }
    $token = & $pythonExe -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" 2>$null
    if ($token) { Set-Content -Path $tokenFile -Value $token -Encoding UTF8 }
}
$PYTHON = $null
foreach ($p in @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
)) {
    if (Test-Path $p) { $PYTHON = $p; break }
}
if (-not $PYTHON) { $PYTHON = "python" }
& $PYTHON -u "$env:USERPROFILE\arena-local-bridge\unified_bridge.py" serve --root "$env:USERPROFILE" --profile owner-shell --token $token *>> "$env:USERPROFILE\arena-agent\logs\ArenaUnifiedBridge.log"
'@
Set-Content -Path "$BRIDGE_DIR\start_ArenaUnifiedBridge.ps1" -Value $startScript -Encoding UTF8
Ok "Start script created"

# ============================================================================
# 8. Setup background service
# ============================================================================
Info "Setting up background service..."

# Try NSSM first for proper Windows service
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if ($nssm) {
    Info "NSSM found, setting up Windows service..."
    & nssm install ArenaBridge $PYTHON "-u" "$BRIDGE_DIR\unified_bridge.py" "serve" "--root" "$HOME_DIR" "--profile" "owner-shell" "--token" $token 2>$null
    & nssm set ArenaBridge AppDirectory $BRIDGE_DIR 2>$null
    & nssm set ArenaBridge DisplayName "Arena Unified Bridge v$VERSION" 2>$null
    & nssm set ArenaBridge Description "Arena Local Agent - Unified Bridge Service" 2>$null
    & nssm set ArenaBridge Start SERVICE_AUTO_START 2>$null
    & nssm set ArenaBridge AppStdout "$LOG_DIR\ArenaUnifiedBridge.log" 2>$null
    & nssm set ArenaBridge AppStderr "$LOG_DIR\ArenaUnifiedBridge.err" 2>$null
    & nssm set ArenaBridge AppRotateFiles 1 2>$null
    & nssm set ArenaBridge AppRotateBytes 10485760 2>$null
    & nssm start ArenaBridge 2>$null
    Ok "NSSM Windows service configured and started"
} else {
    Info "NSSM not found, using Scheduled Task..."

    # Remove old task if exists
    Unregister-ScheduledTask -TaskName "ArenaUnifiedBridge" -Confirm:$false -ErrorAction SilentlyContinue 2>$null

    # Create scheduled task
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$BRIDGE_DIR\start_ArenaUnifiedBridge.ps1`"" `
        -WorkingDirectory $BRIDGE_DIR
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 0)

    Register-ScheduledTask -TaskName "ArenaUnifiedBridge" -Action $action -Trigger $trigger -Settings $settings `
        -Description "Arena Unified Bridge v$VERSION" -Force | Out-Null
    Start-ScheduledTask -TaskName "ArenaUnifiedBridge" 2>$null
    Ok "Scheduled task registered and started"
}

# ============================================================================
# 9. Create helper scripts
# ============================================================================

# status.bat
$statusBat = @"
@echo off
echo === Arena Unified Bridge v$VERSION Status ===
echo.
echo [Health Check]
curl -s http://127.0.0.1:8765/health 2>nul
echo.
echo.
echo [Service Status]
nssm status ArenaBridge 2>nul || schtasks /Query /tn ArenaUnifiedBridge /fo List 2>nul
echo.
echo [Token Location]
echo $TOKEN_FILE
"@
Set-Content -Path "$BRIDGE_DIR\status.bat" -Value $statusBat -Encoding ASCII
Ok "status.bat created"

# stop.bat
$stopBat = @"
@echo off
echo Stopping Arena Unified Bridge...
nssm stop ArenaBridge 2>nul || schtasks /End /tn ArenaUnifiedBridge 2>nul
timeout /t 2 /nobreak >nul
echo Done.
"@
Set-Content -Path "$BRIDGE_DIR\stop.bat" -Value $stopBat -Encoding ASCII
Ok "stop.bat created"

# start.bat
$startBat = @"
@echo off
title Arena Bridge - Start
echo Starting Arena Unified Bridge v$VERSION...
nssm start ArenaBridge 2>nul || schtasks /Run /tn ArenaUnifiedBridge 2>nul
timeout /t 3 /nobreak >nul
curl -s http://127.0.0.1:8765/health 2>nul
echo.
pause
"@
Set-Content -Path "$BRIDGE_DIR\start.bat" -Value $startBat -Encoding ASCII
Ok "start.bat created"

# ============================================================================
# 10. Verify
# ============================================================================
Info "Waiting for bridge to start..."
for ($i = 0; $i -lt 15; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2 -ErrorAction Stop
        if ($r.ok) {
            Ok "Bridge v$($r.version) is healthy! Uptime: $([math]::Round($r.uptime_seconds, 1))s"
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

# Final health check
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 5 -ErrorAction Stop
    $info = Invoke-RestMethod -Uri "http://127.0.0.1:8765/v1/info" -Headers @{Authorization="Bearer $token"} -TimeoutSec 5 -ErrorAction Stop
    Ok "Health: v$($health.version), Profile: $($info.profile)"
} catch {
    Warn "Bridge not responding yet. It may still be starting up."
}

# ============================================================================
# Summary
# ============================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ARENA LOCAL AGENT v$VERSION - INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:   http://127.0.0.1:8765/gui" -ForegroundColor White
Write-Host "  Health:      http://127.0.0.1:8765/health" -ForegroundColor White
Write-Host "  API:         http://127.0.0.1:8765/" -ForegroundColor White
Write-Host "  Token:       $TOKEN_FILE" -ForegroundColor White
Write-Host "  Log:         $LOG_DIR\ArenaUnifiedBridge.log" -ForegroundColor White
Write-Host ""
Write-Host "  Service:     $(if($nssm){'NSSM Windows Service'}else{'Scheduled Task'})" -ForegroundColor Gray
Write-Host "  Auto-starts at logon, hidden window, auto-restart" -ForegroundColor Gray
Write-Host ""
Write-Host "  Start:   $BRIDGE_DIR\start.bat" -ForegroundColor Gray
Write-Host "  Stop:    $BRIDGE_DIR\stop.bat" -ForegroundColor Gray
Write-Host "  Status:  $BRIDGE_DIR\status.bat" -ForegroundColor Gray
Write-Host ""
Write-Host "  50 API endpoints | 17 dashboard tabs | Cross-platform" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
