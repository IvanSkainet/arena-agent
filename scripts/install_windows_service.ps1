# Arena Local Agent — Windows Installer v14.1 (Unified Bridge v1.1.0)
# Consolidates 5 separate processes into a single asyncio-based unified bridge.
# Installs 1 Scheduled Task instead of 5, runs in hidden window via pythonw.exe.
# Fully backward-compatible with v0.4.0 dashboard and API surface.
#
# Usage:    powershell -ExecutionPolicy Bypass -File install_windows_service.ps1
# Uninstall: powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Uninstall
# Update:   powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Update

param([switch]$Uninstall, [switch]$Update)

$ErrorActionPreference = "Stop"

$BridgePath = Join-Path $env:USERPROFILE "arena-local-bridge"
$AgentPath  = Join-Path $env:USERPROFILE "arena-agent"
$TokenPath  = Join-Path $BridgePath "token.txt"
$LogFile    = Join-Path $AgentPath "logs\ArenaUnifiedBridge.log"

# --- Unified task definition (1 task replaces 5) ---
$TaskName = "ArenaUnifiedBridge"

# ------------------- Helpers -------------------

function Ensure-Python {
    # Prefer Python 3.14+ if available
    $localPython = "$env:LOCALAPPDATA\Programs\Python"
    if (Test-Path $localPython) {
        $dirs = Get-ChildItem -Path $localPython -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $pyExe = Join-Path $d.FullName "python.exe"
            $pywExe = Join-Path $d.FullName "pythonw.exe"
            if (Test-Path $pyExe) {
                Write-Host "[OK] Found Python: $pyExe" -ForegroundColor Green
                return @{ Python = $pyExe; PythonW = $pywExe }
            }
        }
    }
    # Fallback to PATH
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        $pyDir = Split-Path $py.Source
        $pyw = Join-Path $pyDir "pythonw.exe"
        return @{ Python = $py.Source; PythonW = $pyw }
    }
    Write-Error "Python not found. Install from https://www.python.org/ and check 'Add python.exe to PATH'."
}

function Ensure-NodeJS {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { return $node.Source }
    Write-Host "=== Node.js not found. Installing LTS silently... ===" -ForegroundColor Yellow
    $msiUrl = "https://nodejs.org/dist/v20.15.1/node-v20.15.1-x64.msi"
    $msiFile = Join-Path $env:TEMP "node-lts.msi"
    try {
        Invoke-WebRequest -Uri $msiUrl -OutFile $msiFile -UseBasicParsing
        Start-Process msiexec.exe -ArgumentList "/i `"$msiFile`" /qn ADDLOCAL=ALL" -Wait -NoNewWindow
        Remove-Item $msiFile -Force
    } catch {
        Write-Warning "Automatic Node.js installation failed. Install manually from https://nodejs.org/"
        return $null
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $node = Get-Command node -ErrorAction SilentlyContinue
    return if ($node) { $node.Source } else { $null }
}

function Generate-Token {
    Write-Host "Generating a secure, unique access token..." -ForegroundColor Yellow
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    $bytes = New-Object Byte[] 43
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $token = ""
    foreach ($b in $bytes) {
        $token += $chars[$b % $chars.Length]
    }
    [System.IO.File]::WriteAllText($TokenPath, $token, [System.Text.Encoding]::ASCII)
    Write-Host "[OK] Access token saved to $TokenPath" -ForegroundColor Green
}

function Get-Token {
    if (Test-Path $TokenPath) {
        $data = [System.IO.File]::ReadAllBytes($TokenPath)
        $token = [System.Text.Encoding]::UTF8.GetString($data).Trim()
        # Remove BOM if present
        if ($token.StartsWith([char]0xFEFF)) { $token = $token.Substring(1) }
        return $token
    }
    return $null
}

function Stop-OldTasks {
    # Stop all v0.4 tasks (5 separate processes) + new unified task
    $oldNames = @("ArenaLocalBridge", "ArenaMcpStream", "ArenaMcpWs", "ArenaTaskRunner", "ArenaWebGateway", $TaskName)
    foreach ($name in $oldNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq "Running") {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
            Write-Host "[OK] Stopped task: $name" -ForegroundColor Yellow
        }
    }
    # Force-kill processes on old ports (8765-8769)
    foreach ($port in @(8765, 8767, 8768, 8769)) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conn) {
                foreach ($c in $conn) {
                    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                    Write-Host "[OK] Killed process on port $port (PID $($c.OwningProcess))" -ForegroundColor Yellow
                }
            }
        } catch {}
    }
    Start-Sleep -Seconds 2
}

function Remove-OldTasks {
    $oldNames = @("ArenaLocalBridge", "ArenaMcpStream", "ArenaMcpWs", "ArenaTaskRunner", "ArenaWebGateway", $TaskName)
    foreach ($name in $oldNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
            Write-Host "[OK] Removed task: $name"
        }
    }
}

function Create-UnifiedTask {
    param([hashtable]$PythonExes, [string]$Token)

    # Generate the startup PS1 script
    $startPs1 = Join-Path $BridgePath "start_$TaskName.ps1"
    $body = @()
    $body += '$ErrorActionPreference = "Continue"'
    $body += 'Set-Location "' + $BridgePath + '"'
    # Use pythonw.exe for hidden window (no console), -u for unbuffered
    # pythonw.exe: stdout/stderr handled by unified_bridge.py (devnull redirect at module level)
    $body += '& "' + $PythonExes.PythonW + '" -u "' + (Join-Path $BridgePath "unified_bridge.py") + '" serve --root "' + $env:USERPROFILE + '" --profile owner-shell --token "' + $Token + '" *>> "' + $LogFile + '"'
    Set-Content -Path $startPs1 -Value ($body -join "`r`n") -Encoding UTF8
    Write-Host "[OK] Created $startPs1" -ForegroundColor Green

    # Register Scheduled Task: runs at logon, hidden window, auto-restart
    $Action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"")
    $Trigger   = New-ScheduledTaskTrigger -AtLogOn
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    Write-Host "[OK] Registered scheduled task: $TaskName (hidden window, auto-restart, at-logon)" -ForegroundColor Green
}

function Start-UnifiedTask {
    # Start via Task Scheduler
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Write-Host "[OK] Started $TaskName via Task Scheduler" -ForegroundColor Green
    
    # Also start immediately in hidden window
    $startPs1 = Join-Path $BridgePath "start_$TaskName.ps1"
    if (Test-Path $startPs1) {
        Start-Process powershell.exe -ArgumentList ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"") -WindowStyle Hidden -ErrorAction SilentlyContinue
        Write-Host "[OK] Started $TaskName immediately (hidden window)" -ForegroundColor Green
    }
}

# ------------------- Main flow -------------------
if ($Uninstall) {
    Write-Host "`n=== UNINSTALLING Arena Unified Bridge ===" -ForegroundColor Red
    Stop-OldTasks
    Remove-OldTasks

    # Remove bin from User PATH if present
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $BinPath = Join-Path $AgentPath "bin"
    if ($UserPath -like "*$BinPath*") {
        $NewPath = ($UserPath -split ";" | Where-Object { $_ -ne $BinPath }) -join ";"
        [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
        Write-Host "[OK] Removed $BinPath from User PATH." -ForegroundColor Green
    }
    Write-Host "`n=== UNINSTALL COMPLETE ===" -ForegroundColor Green
    return
}

if ($Update) {
    Write-Host "`n=== UPDATING Arena Unified Bridge ===" -ForegroundColor Cyan
    Stop-OldTasks
    # Keep the task registered, just restart after update
    Start-Sleep -Seconds 2
    Start-UnifiedTask
    Write-Host "`n=== UPDATE COMPLETE ===" -ForegroundColor Green
    return
}

# Fresh install
Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Arena Local Agent — Unified Bridge v1.1.0       " -ForegroundColor Cyan
Write-Host "  Windows Installer (1 process, 1 port, 1 task)   " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Ensure directories
New-Item -ItemType Directory -Force -Path $BridgePath, $AgentPath, "$AgentPath\scripts", "$AgentPath\bin", "$AgentPath\logs" | Out-Null

# Python
$PythonExes = Ensure-Python
Write-Host "[OK] Python: $($PythonExes.Python)" -ForegroundColor Green
Write-Host "[OK] PythonW: $($PythonExes.PythonW)" -ForegroundColor Green

# Node.js
$null = Ensure-NodeJS

# Token: preserve existing or generate new
$existingToken = Get-Token
if ($existingToken) {
    Write-Host "[OK] Using existing token from $TokenPath" -ForegroundColor Green
} else {
    Generate-Token
    $existingToken = Get-Token
}

# Dependencies
Write-Host "Installing/Updating Python packages..." -ForegroundColor Cyan
try {
    Start-Process -FilePath $PythonExes.Python -ArgumentList "-m pip install --quiet --upgrade aiohttp httpx requests beautifulsoup4" -NoNewWindow -Wait
    Write-Host "[OK] Python packages ready." -ForegroundColor Green
} catch {
    Write-Warning "pip install failed. Run manually: pip install aiohttp httpx requests beautifulsoup4"
}

# agentctl.bat wrapper
$AgentBin = Join-Path $AgentPath "bin"
$AgentctlBat = Join-Path $AgentBin "agentctl.bat"
$BatContent = "@echo off`r`n`"$($PythonExes.Python)`" `"%~dp0agentctl`" %*"
Set-Content -Path $AgentctlBat -Value $BatContent -Encoding ASCII
Write-Host "[OK] Created agentctl wrapper: $AgentctlBat" -ForegroundColor Green

# Add bin to User PATH
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$AgentBin*") {
    $Separator = if ($UserPath.Length -eq 0 -or $UserPath.EndsWith(";")) { "" } else { ";" }
    [System.Environment]::SetEnvironmentVariable("Path", $UserPath + $Separator + $AgentBin, "User")
    Write-Host "[OK] Added $AgentBin to User PATH." -ForegroundColor Green
}

# Stop and remove all old tasks (5 separate v0.4 processes)
Write-Host "`n=== Migrating from v0.4.0 (5 processes) -> v1.1.0 (1 process) ===" -ForegroundColor Yellow
Stop-OldTasks
Remove-OldTasks

# Create unified task (1 scheduled task replaces 5)
Create-UnifiedTask -PythonExes $PythonExes -Token $existingToken

# Start!
Start-UnifiedTask

# Wait and verify
Write-Host "`nWaiting for bridge to start..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

$healthCheck = $null
try {
    $healthCheck = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 5 -ErrorAction Stop
} catch {}

if ($healthCheck -and $healthCheck.ok) {
    Write-Host "[OK] Bridge is healthy! v$($healthCheck.version) on port 8765" -ForegroundColor Green
} else {
    Write-Warning "Bridge health check failed. Check log: $LogFile"
}

# Print summary
Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host "  INSTALLATION COMPLETE!                          " -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://127.0.0.1:8765/gui" -ForegroundColor White
Write-Host "  Health:     http://127.0.0.1:8765/health" -ForegroundColor White
Write-Host "  API:        POST http://127.0.0.1:8765/v1/exec" -ForegroundColor White
Write-Host "  MCP:        POST http://127.0.0.1:8765/mcp" -ForegroundColor White
Write-Host "  Log:        $LogFile" -ForegroundColor White
Write-Host ""
Write-Host "  Scheduled task: $TaskName (auto-starts at logon)" -ForegroundColor White
Write-Host "  Manage:      schtasks /Run /tn $TaskName" -ForegroundColor White
Write-Host "               schtasks /End /tn $TaskName" -ForegroundColor White
Write-Host ""
Write-Host "  Stop:        powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Uninstall" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Green
