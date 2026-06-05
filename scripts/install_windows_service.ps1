# ============================================================================
# Arena Local Agent - Windows Installer v1.3.0
# With auto token regeneration + version checking for all components
# ============================================================================
# Run as: powershell -ExecutionPolicy Bypass -File install_windows_service.ps1
# ============================================================================

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$VERSION = "1.3.0"
$HOME_DIR = $env:USERPROFILE
$BRIDGE_DIR = "$HOME_DIR\arena-bridge"
$AGENT_DIR = "$HOME_DIR\arena-bridge"
$TOKEN_FILE = "$BRIDGE_DIR\token.txt"
$BIN_DIR = "$AGENT_DIR\bin"
$LOG_DIR = "$AGENT_DIR\logs"

function Ok($msg)   { Write-Host "[OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Warn($msg) { Write-Host "[WARN] " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Err($msg)  { Write-Host "[ERROR] " -ForegroundColor Red -NoNewline; Write-Host $msg }
function Info($msg) { Write-Host "[INFO] " -ForegroundColor Cyan -NoNewline; Write-Host $msg }

# Helper: Compare version strings (returns 1 if $v1 > $v2, 0 if equal, -1 if less)
function Compare-Version($v1, $v2) {
    if ([string]::IsNullOrWhiteSpace($v1) -or [string]::IsNullOrWhiteSpace($v2)) { return 0 }
    $a1 = $v1.Split('.')
    $a2 = $v2.Split('.')
    $maxLen = [Math]::Max($a1.Length, $a2.Length)
    for ($i = 0; $i -lt $maxLen; $i++) {
        $n1 = if ($i -lt $a1.Length) { [int]$a1[$i] } else { 0 }
        $n2 = if ($i -lt $a2.Length) { [int]$a2[$i] } else { 0 }
        if ($n1 -gt $n2) { return 1 }
        if ($n1 -lt $n2) { return -1 }
    }
    return 0
}

# Helper: Get installed version of a package
function Get-InstalledVersion($cmd) {
    try {
        $output = & $cmd --version 2>$null
        if ($LASTEXITCODE -eq 0 -or $null -ne $output) {
            $ver = ($output | Select-String -Pattern '[\d]+\.[\d]+[\.\d]*' | Select-Object -First 1).Matches.Value
            return $ver
        }
    } catch {}
    return $null
}

# ============================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Arena Local Agent - Unified Bridge v$VERSION" -ForegroundColor Cyan
Write-Host "  1 process, 1 port, 1 scheduled task" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# 1. Core: Python
# ============================================================================
$PYTHON = $null
$pythonCandidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe"
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
    $PY_MINOR = $PY_VER.Split('.')[1]
    if ([int]$PY_MINOR -lt 10) {
        Warn "Python $PY_VER found but 3.10+ recommended. Consider upgrading."
    }
} else {
    Err "Python not found. Install Python 3.10+ from https://python.org"
    Read-Host "Press Enter to exit"
    exit 1
}

# ============================================================================
# 2. Core: Node.js (with version check)
# ============================================================================
$NODE = (Get-Command node -ErrorAction SilentlyContinue).Source
if ($NODE) {
    $NODE_VER_RAW = & node --version 2>$null
    $NODE_VER = $NODE_VER_RAW -replace 'v', ''
    $NODE_MAJOR = $NODE_VER.Split('.')[0]
    if ([int]$NODE_MAJOR -lt 18) {
        Warn "Node.js $NODE_VER_RAW found but 18+ recommended. Updating..."
        winget upgrade OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements 2>$null
        Ok "Node.js updated"
    } else {
        Ok "Node.js: $NODE ($NODE_VER_RAW)"
    }
} else {
    Info "Node.js not found. Installing via winget..."
    winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements 2>$null
    $NODE = (Get-Command node -ErrorAction SilentlyContinue).Source
    if ($NODE) { Ok "Node.js installed: $(node --version)" } else { Warn "Node.js install failed" }
}

# ============================================================================
# 3. Python packages (with version check for aiohttp)
# ============================================================================
Info "Installing/Updating Python packages..."
$AIOHTTP_VER = & $PYTHON -c "import aiohttp; print(aiohttp.__version__)" 2>$null
if ($AIOHTTP_VER) {
    Info "aiohttp $AIOHTTP_VER found. Checking for update..."
}
& $PYTHON -m pip install --quiet --upgrade aiohttp 2>$null
$AIOHTTP_NEW = & $PYTHON -c "import aiohttp; print(aiohttp.__version__)" 2>$null
if ($AIOHTTP_VER -and ($AIOHTTP_VER -ne $AIOHTTP_NEW)) {
    Ok "aiohttp updated: $AIOHTTP_VER -> $AIOHTTP_NEW"
} else {
    Ok "Python packages ready (aiohttp $AIOHTTP_NEW)"
}

# ============================================================================
# 4. Project structure
# ============================================================================
$dirs = @($BRIDGE_DIR, $BIN_DIR, $LOG_DIR, "$AGENT_DIR\memory", "$AGENT_DIR\queue\inbox", "$AGENT_DIR\queue\running", "$AGENT_DIR\queue\done", "$AGENT_DIR\queue\failed", "$AGENT_DIR\tools", "$AGENT_DIR\reports\shots")
foreach ($d in $dirs) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

# ============================================================================
# 5. Token — AUTO-REGENERATE on every install run
# ============================================================================
Info "Regenerating auth token..."
$newToken = & $PYTHON -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" 2>$null
if ($newToken -and $newToken.Length -ge 16) {
    Set-Content -Path $TOKEN_FILE -Value $newToken -Encoding UTF8
    Ok "New token generated and saved to $TOKEN_FILE"
} else {
    # Fallback: keep existing token if generation fails
    if (Test-Path $TOKEN_FILE) {
        $existingToken = (Get-Content $TOKEN_FILE -First 1 -ErrorAction SilentlyContinue).Trim()
        if ($existingToken -and $existingToken.Length -ge 16) {
            Warn "Token generation failed, keeping existing token"
            $newToken = $existingToken
        }
    }
    if (-not $newToken) {
        Err "Failed to generate token"
        Read-Host "Press Enter to exit"
        exit 1
    }
}

# Read the token for startup script
$TOKEN = (Get-Content $TOKEN_FILE -First 1).Trim()

# ============================================================================
# 6. agentctl wrapper
# ============================================================================
$agentctl = @"
@echo off
"$PYTHON" "$BRIDGE_DIR\unified_bridge.py" %*
"@
Set-Content -Path "$BIN_DIR\agentctl.bat" -Value $agentctl -Encoding ASCII
Ok "agentctl wrapper created"

# ============================================================================
# 7. Copy/update unified_bridge.py to bridge directory
# ============================================================================
$SCRIPT_SOURCE = "$PSScriptRoot\unified_bridge.py"
if (Test-Path $SCRIPT_SOURCE) {
    Copy-Item -Path $SCRIPT_SOURCE -Destination "$BRIDGE_DIR\unified_bridge.py" -Force
    Ok "unified_bridge.py copied to $BRIDGE_DIR"
} else {
    # Check if bridge code exists at destination
    if (Test-Path "$BRIDGE_DIR\unified_bridge.py") {
        Ok "unified_bridge.py already in $BRIDGE_DIR"
    } else {
        Warn "unified_bridge.py not found. Please copy it to $BRIDGE_DIR"
    }
}

# ============================================================================
# 8. Optional: Git (with version check)
# ============================================================================
Write-Host ""
Write-Host "--- Optional: Git ---" -ForegroundColor Yellow

$GIT = (Get-Command git -ErrorAction SilentlyContinue).Source
if ($GIT) {
    $GIT_VER = Get-InstalledVersion "git"
    if ($GIT_VER) {
        Ok "Git $GIT_VER found"
        # Check for updates via winget
        Info "Checking for Git update..."
        $gitUpdateResult = winget upgrade Git.Git --accept-source-agreements --accept-package-agreements 2>&1
        if ($gitUpdateResult -match "No applicable update") {
            Ok "Git is up to date"
        } else {
            Ok "Git update checked"
        }
    } else {
        Ok "Git found"
    }
} else {
    $answer = Read-Host "Install Git? [Y/n]"
    if ($answer -notmatch "^[Nn]") {
        winget install Git.Git --accept-source-agreements --accept-package-agreements 2>$null
        Ok "Git installed"
    }
}

# ============================================================================
# 9. Optional: Tailscale (with version check)
# ============================================================================
Write-Host ""
Write-Host "--- Optional: Tailscale (VPN/Funnel) ---" -ForegroundColor Yellow

$TS = (Get-Command tailscale -ErrorAction SilentlyContinue).Source
if ($TS) {
    $TS_VER = & tailscale version 2>$null | Select-Object -First 1
    Ok "Tailscale found: $TS_VER"
    # Check for update
    Info "Checking for Tailscale update..."
    winget upgrade Tailscale.Tailscale --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
    $tsStatus = & tailscale status 2>$null
    if ($tsStatus -match "stopped") {
        Warn "Tailscale installed but not running. Start it and login."
    } else {
        Ok "Tailscale is active"
    }
} else {
    $answer = Read-Host "Install Tailscale? [Y/n]"
    if ($answer -notmatch "^[Nn]") {
        winget install Tailscale.Tailscale --accept-source-agreements --accept-package-agreements 2>$null
        Ok "Tailscale installed. Run: tailscale up"
    }
}

# ============================================================================
# 10. Optional: Browser (Edge/Chrome) - with proper detection + version
# ============================================================================
Write-Host ""
Write-Host "--- Optional: Browser Automation ---" -ForegroundColor Yellow

$EDGE_PATHS = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
)
$CHROME_PATHS = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
$LIBREWOLF_PATHS = @(
    "$env:ProgramFiles\LibreWolf\librewolf.exe"
)

$browserFound = $null
$browserName = ""

foreach ($p in $EDGE_PATHS) {
    if (Test-Path $p) { $browserFound = $p; $browserName = "Edge"; break }
}
if (-not $browserFound) {
    foreach ($p in $CHROME_PATHS) {
        if (Test-Path $p) { $browserFound = $p; $browserName = "Chrome"; break }
    }
}
if (-not $browserFound) {
    foreach ($p in $LIBREWOLF_PATHS) {
        if (Test-Path $p) { $browserFound = $p; $browserName = "LibreWolf"; break }
    }
}

if ($browserFound) {
    try {
        $ver = (Get-Item $browserFound).VersionInfo.ProductVersion
        Ok "$browserName found: $browserFound ($ver)"
    } catch {
        Ok "$browserName found: $browserFound"
    }
} else {
    $answer = Read-Host "No browser found. Install Microsoft Edge? [Y/n]"
    if ($answer -notmatch "^[Nn]") {
        Info "Installing Edge..."
        winget install Microsoft.Edge --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        # Re-check after install
        foreach ($p in $EDGE_PATHS) {
            if (Test-Path $p) { $browserFound = $p; Ok "Edge found: $p"; break }
        }
        if (-not $browserFound) {
            Warn "Edge install may have failed. Check manually."
        }
    }
}

# ============================================================================
# 11. Optional: Dev tools (VSCode, 7-Zip, Windows Terminal) with version check
# ============================================================================
Write-Host ""
Write-Host "--- Optional: Dev Tools ---" -ForegroundColor Yellow

$answer = Read-Host "Install/update dev tools? (VSCode, 7-Zip, Windows Terminal) [y/N]"
if ($answer -match "^[Yy]") {
    # VSCode
    $VSCODE = (Get-Command code -ErrorAction SilentlyContinue).Source
    if ($VSCODE) {
        $VSCODE_VER = Get-InstalledVersion "code"
        Info "VSCode $VSCODE_VER found. Checking for update..."
        winget upgrade Microsoft.VisualStudioCode --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "VSCode updated"
    } else {
        winget install Microsoft.VisualStudioCode --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "VSCode installed"
    }

    # 7-Zip
    $SZ = (Get-Command 7z -ErrorAction SilentlyContinue).Source
    if ($SZ) {
        Info "7-Zip found. Checking for update..."
        winget upgrade 7zip.7zip --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "7-Zip updated"
    } else {
        winget install 7zip.7zip --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "7-Zip installed"
    }

    # Windows Terminal
    $WT = (Get-Command wt -ErrorAction SilentlyContinue).Source
    if ($WT) {
        Info "Windows Terminal found. Checking for update..."
        winget upgrade Microsoft.WindowsTerminal --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "Windows Terminal updated"
    } else {
        winget install Microsoft.WindowsTerminal --accept-source-agreements --accept-package-agreements 2>$null | Out-Null
        Ok "Windows Terminal installed"
    }
}

# ============================================================================
# 12. Optional: BrowserAct (AI Browser Automation) with version check
# ============================================================================
Write-Host ""
Write-Host "--- Optional: BrowserAct (AI Browser Automation) ---" -ForegroundColor Yellow

$BA = (Get-Command browser-act -ErrorAction SilentlyContinue).Source
if ($BA) {
    $BA_VER = & browser-act --version 2>$null
    Ok "BrowserAct CLI found: $BA_VER"
    # Check for update
    Info "Checking for BrowserAct update..."
    $BA_VER_BEFORE = $BA_VER
    npm update -g @anthropic-ai/browser-act 2>$null
    npm update -g browser-act 2>$null
    $BA_VER_AFTER = & browser-act --version 2>$null
    if ($BA_VER_BEFORE -ne $BA_VER_AFTER) {
        Ok "BrowserAct updated: $BA_VER_BEFORE -> $BA_VER_AFTER"
    } else {
        Ok "BrowserAct is up to date ($BA_VER_AFTER)"
    }
} else {
    $answer = Read-Host "Install BrowserAct CLI? [y/N]"
    if ($answer -match "^[Yy]") {
        Info "Installing BrowserAct..."
        npm install -g @anthropic-ai/browser-act 2>$null
        if (Get-Command browser-act -ErrorAction SilentlyContinue) {
            Ok "BrowserAct installed: $(browser-act --version 2>$null)"
        } else {
            # Try alternative package names
            npm install -g browser-act 2>$null
            if (Get-Command browser-act -ErrorAction SilentlyContinue) {
                Ok "BrowserAct installed"
            } else {
                Warn "BrowserAct install failed. Try manually: npm install -g @anthropic-ai/browser-act"
            }
        }
    }
}

# ============================================================================
# 13. Optional: Superpowers (obra/superpowers) with version check
# ============================================================================
Write-Host ""
Write-Host "--- Optional: Superpowers (AI Agent Skills) ---" -ForegroundColor Yellow

$SP_DIR = "$AGENT_DIR\tools\superpowers"
if (Test-Path "$SP_DIR\.git") {
    $SP_VER_BEFORE = & git -C $SP_DIR log -1 --format="%h %ci" 2>$null
    Ok "Superpowers found, updating..."
    Push-Location $SP_DIR
    git pull --ff-only 2>$null
    Pop-Location
    $SP_VER_AFTER = & git -C $SP_DIR log -1 --format="%h %ci" 2>$null
    if ($SP_VER_BEFORE -ne $SP_VER_AFTER) {
        Ok "Superpowers updated: $SP_VER_BEFORE -> $SP_VER_AFTER"
    } else {
        Ok "Superpowers is up to date ($SP_VER_AFTER)"
    }
} else {
    $answer = Read-Host "Install Superpowers (obra/superpowers)? [y/N]"
    if ($answer -match "^[Yy]") {
        if (Get-Command git -ErrorAction SilentlyContinue) {
            Info "Cloning obra/superpowers..."
            git clone https://github.com/obra/superpowers.git $SP_DIR 2>$null
            if (Test-Path $SP_DIR) { Ok "Superpowers installed to $SP_DIR" } else { Warn "Could not clone superpowers" }
        } else {
            Warn "Git required. Install Git first."
        }
    }
}

# ============================================================================
# 14. Setup: Scheduled Task (reads token from file, NOT hardcoded)
# ============================================================================
Write-Host ""
Write-Host "=== Setting up Unified Bridge ===" -ForegroundColor Cyan

# Create start script that READS token from file every time
$startScript = @"
`$ErrorActionPreference = "Continue"
Set-Location "$BRIDGE_DIR"
`$token = Get-Content "$TOKEN_FILE" -First 1 -ErrorAction SilentlyContinue
if (-not `$token) {
    `$token = & "$PYTHON" -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" 2>`$null
    Set-Content -Path "$TOKEN_FILE" -Value `$token -Encoding UTF8
}
# v2.1.0: Rotate log if over 10MB before starting (prevents disk fill)
`$logFile = "$LOG_DIR\ArenaUnifiedBridge.log"
if (Test-Path `$logFile) {
    if ((Get-Item `$logFile).Length -gt 10MB) {
        if (Test-Path "`$logFile.2") { Remove-Item "`$logFile.2" -Force -ErrorAction SilentlyContinue }
        if (Test-Path "`$logFile.1") { Move-Item "`$logFile.1" "`$logFile.2" -Force -ErrorAction SilentlyContinue }
        Move-Item "`$logFile" "`$logFile.1" -Force -ErrorAction SilentlyContinue
    }
}
& "$PYTHON" -u "$BRIDGE_DIR\unified_bridge.py" serve --root "$HOME_DIR" --profile owner-shell --token `$token *>> "$LOG_DIR\ArenaUnifiedBridge.log"
"@
Set-Content -Path "$BRIDGE_DIR\start_ArenaUnifiedBridge.ps1" -Value $startScript -Encoding UTF8
Ok "Created $BRIDGE_DIR\start_ArenaUnifiedBridge.ps1"

# Remove old task if exists
Unregister-ScheduledTask -TaskName "ArenaUnifiedBridge" -Confirm:$false -ErrorAction SilentlyContinue 2>$null
Ok "Removed old task: ArenaUnifiedBridge"

# Create new scheduled task — uses the PS1 script which reads token from file
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$BRIDGE_DIR\start_ArenaUnifiedBridge.ps1`"" -WorkingDirectory $BRIDGE_DIR
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask -TaskName "ArenaUnifiedBridge" -Action $action -Trigger $trigger -Settings $settings -Description "Arena Unified Bridge v$VERSION" -Force | Out-Null
Ok "Scheduled task registered: ArenaUnifiedBridge"

# Start immediately
Start-ScheduledTask -TaskName "ArenaUnifiedBridge" 2>$null
Ok "Started via Task Scheduler"

# Wait for bridge
Info "Waiting for bridge to start..."
for ($i = 0; $i -lt 15; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2 -ErrorAction Stop
        if ($r.ok) {
            Ok "Bridge is healthy! v$($r.version)"
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}

# ============================================================================
# 15. Create helper scripts
# ============================================================================

# Create regenerate_token.bat
$regenBat = @"
@echo off
:: Arena Local Bridge - Token Regeneration Script v1.3.0
:: Regenerates token and restarts bridge automatically

setlocal enabledelayedexpansion

set "BRIDGE_DIR=%USERPROFILE%\arena-bridge"
set "TOKEN_FILE=%BRIDGE_DIR%\token.txt"
set "PYTHON="

:: Find Python
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
) do (
    if exist %%p set "PYTHON=%%~p"
)
if not defined PYTHON (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python not found.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

echo ============================================================
echo   Arena Local Bridge - Token Regeneration v1.3.0
echo ============================================================
echo.

:: Stop the bridge
schtasks /End /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 2 /nobreak >nul

:: Generate new token
echo [1/3] Generating new token...
for /f "delims=" %%t in ('"%PYTHON%" -c "import base64,secrets;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip(\"=\"))"') do set "NEW_TOKEN=%%t"

if not defined NEW_TOKEN (
    echo [ERROR] Failed to generate token
    pause
    exit /b 1
)

:: Save token
echo [2/3] Saving token...
if not exist "%BRIDGE_DIR%" mkdir "%BRIDGE_DIR%"
echo %NEW_TOKEN%> "%TOKEN_FILE%"

:: Restart the bridge
echo [3/3] Restarting bridge...
schtasks /Run /tn ArenaUnifiedBridge >nul 2>&1
timeout /t 3 /nobreak >nul

:: Health check
curl -s http://127.0.0.1:8765/health 2>nul
echo.

echo.
echo ============================================================
echo   Token regenerated!
echo   New token: %NEW_TOKEN%
echo   Saved to: %TOKEN_FILE%
echo ============================================================
echo.
pause
"@
Set-Content -Path "$BRIDGE_DIR\regenerate_token.bat" -Value $regenBat -Encoding ASCII
Ok "Created regenerate_token.bat"

# Create status.bat
$statusBat = @"
@echo off
echo === Arena Unified Bridge Status ===
echo.
echo [Health Check]
curl -s http://127.0.0.1:8765/health 2>nul
echo.
echo.
echo [Scheduled Task]
schtasks /Query /tn ArenaUnifiedBridge /fo List 2>nul
echo.
echo [Token Location]
echo %USERPROFILE%\arena-bridge\token.txt
"@
Set-Content -Path "$BRIDGE_DIR\status.bat" -Value $statusBat -Encoding ASCII
Ok "Created status.bat"

# ============================================================================
# Summary
# ============================================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  ARENA LOCAL AGENT - INSTALLATION COMPLETE!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:   http://127.0.0.1:8765/gui"
Write-Host "  Health:      http://127.0.0.1:8765/health"
Write-Host "  Token:       $TOKEN_FILE (auto-regenerated)"
Write-Host "  Log:         $LOG_DIR\ArenaUnifiedBridge.log"
Write-Host ""
Write-Host "  Auto-starts at logon, hidden window, auto-restart"
Write-Host "  Stop:    schtasks /End /tn ArenaUnifiedBridge"
Write-Host "  Start:   schtasks /Run /tn ArenaUnifiedBridge"
Write-Host "  Status:  $BRIDGE_DIR\status.bat"
Write-Host "  Regen:   $BRIDGE_DIR\regenerate_token.bat"
Write-Host ""
Write-Host "  Cross-platform: install_linux.sh (Arch/Debian/Fedora/Gentoo/Alpine/openSUSE/NixOS)"
Write-Host "  BrowserAct:     browser-act --version"
Write-Host "  Superpowers:    $SP_DIR"
Write-Host "============================================================"
Write-Host ""

Write-Host "Installation completed successfully."
Write-Host "To open the dashboard, visit: http://127.0.0.1:8765/gui"
Write-Host ""
Read-Host "Press Enter to exit"
