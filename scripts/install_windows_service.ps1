# Arena Local Agent - Windows Installer v15.0 (Unified Bridge v1.2.0)
# 1 process, 1 port, 1 scheduled task. Runs hidden via -WindowStyle Hidden.
# Fully cross-platform: also see install_linux.sh for Arch/CachyOS/Debian/Fedora.
#
# Usage:     powershell -ExecutionPolicy Bypass -File install_windows_service.ps1
# Uninstall: powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Uninstall
# Update:    powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Update

param([switch]$Uninstall, [switch]$Update)

$ErrorActionPreference = 'Stop'

$BridgePath = Join-Path $env:USERPROFILE 'arena-local-bridge'
$AgentPath  = Join-Path $env:USERPROFILE 'arena-agent'
$TokenPath  = Join-Path $BridgePath 'token.txt'
$LogFile    = Join-Path $AgentPath 'logs\ArenaUnifiedBridge.log'
$TaskName   = 'ArenaUnifiedBridge'

# ------------------- Helpers -------------------

function Ensure-Python {
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $localPython) {
        $dirs = Get-ChildItem -Path $localPython -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $pyExe = Join-Path $d.FullName 'python.exe'
            if (Test-Path $pyExe) {
                Write-Host "[OK] Python: $pyExe" -ForegroundColor Green
                return $pyExe
            }
        }
    }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    Write-Error 'Python not found. Install from https://www.python.org/ and check Add to PATH.'
}

function Ensure-NodeJS {
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { return $node.Source }
    Write-Host 'Node.js not found.' -ForegroundColor Yellow
    $answer = Read-Host 'Install Node.js LTS automatically? [Y/n]'
    if ($answer -eq '' -or $answer -eq 'Y' -or $answer -eq 'y') {
        $msiUrl = 'https://nodejs.org/dist/v20.15.1/node-v20.15.1-x64.msi'
        $msiFile = Join-Path $env:TEMP 'node-lts.msi'
        try {
            Invoke-WebRequest -Uri $msiUrl -OutFile $msiFile -UseBasicParsing
            Start-Process msiexec.exe -ArgumentList "/i `"$msiFile`" /qn ADDLOCAL=ALL" -Wait -NoNewWindow
            Remove-Item $msiFile -Force
            $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
            Write-Host '[OK] Node.js installed.' -ForegroundColor Green
        } catch {
            Write-Warning 'Node.js install failed. Install manually from https://nodejs.org/'
        }
    }
}

function Ensure-Git {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) { return }
    Write-Host 'Git not found.' -ForegroundColor Yellow
    $answer = Read-Host 'Install Git automatically? [Y/n]'
    if ($answer -eq '' -or $answer -eq 'Y' -or $answer -eq 'y') {
        $gitUrl = 'https://github.com/git-for-windows/git/releases/download/v2.45.0.windows.1/Git-2.45.0-64-bit.exe'
        $gitFile = Join-Path $env:TEMP 'git-setup.exe'
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $gitUrl -OutFile $gitFile -UseBasicParsing
            Start-Process $gitFile -ArgumentList '/VERYSILENT /NORESTART /NOCANCEL /SP-' -Wait -NoNewWindow
            Remove-Item $gitFile -Force
            $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('Path', 'User')
            Write-Host '[OK] Git installed.' -ForegroundColor Green
        } catch {
            Write-Warning 'Git install failed. Install manually from https://git-scm.com/'
        }
    }
}

function Ensure-Tailscale {
    $ts = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($ts) { return }
    Write-Host 'Tailscale not found.' -ForegroundColor Yellow
    $answer = Read-Host 'Install Tailscale for remote access? [Y/n]'
    if ($answer -eq '' -or $answer -eq 'Y' -or $answer -eq 'y') {
        $tsUrl = 'https://tailscale.com/install.ps1'
        try {
            Invoke-WebRequest -Uri $tsUrl -OutFile (Join-Path $env:TEMP 'install-tailscale.ps1') -UseBasicParsing
            Start-Process powershell -ArgumentList '-ExecutionPolicy Bypass -File',(Join-Path $env:TEMP 'install-tailscale.ps1') -Wait -NoNewWindow
            Write-Host '[OK] Tailscale installed.' -ForegroundColor Green
        } catch {
            Write-Warning 'Tailscale install failed. Install manually from https://tailscale.com/'
        }
    }
}

function Generate-Token {
    Write-Host 'Generating a secure access token...' -ForegroundColor Yellow
    $chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_'
    $bytes = New-Object Byte[] 43
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $token = ''
    foreach ($b in $bytes) {
        $token += $chars[$b % $chars.Length]
    }
    [System.IO.File]::WriteAllText($TokenPath, $token, [System.Text.Encoding]::ASCII)
    Write-Host '[OK] Access token saved' -ForegroundColor Green
}

function Get-Token {
    if (-not (Test-Path $TokenPath)) { return $null }
    # Read as bytes to avoid BOM corruption
    $bytes = [System.IO.File]::ReadAllBytes($TokenPath)
    $token = [System.Text.Encoding]::ASCII.GetString($bytes).Trim()
    # Remove BOM if present (UTF-8 BOM = EF BB BF)
    if ($token.Length -gt 0 -and $token[0] -eq [char]0xFEFF) {
        $token = $token.Substring(1)
    }
    return $token
}

function Stop-OldTasks {
    $oldNames = @('ArenaLocalBridge', 'ArenaMcpStream', 'ArenaMcpWs', 'ArenaTaskRunner', 'ArenaWebGateway', $TaskName)
    foreach ($name in $oldNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue | Out-Null
        }
    }
    foreach ($port in @(8765, 8767, 8768, 8769)) {
        try {
            $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conn) {
                foreach ($c in $conn) {
                    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        } catch {}
    }
    Start-Sleep -Seconds 2
}

function Remove-OldTasks {
    $oldNames = @('ArenaLocalBridge', 'ArenaMcpStream', 'ArenaMcpWs', 'ArenaTaskRunner', 'ArenaWebGateway', $TaskName)
    foreach ($name in $oldNames) {
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
            Write-Host "[OK] Removed task: $name"
        }
    }
}

function Create-UnifiedTask {
    param([string]$PyExe, [string]$Token)

    $startPs1 = Join-Path $BridgePath "start_$TaskName.ps1"
    # Use python.exe with -WindowStyle Hidden (not pythonw.exe)
    # pythonw.exe + *>> causes stream redirect issues
    $scriptBody = @()
    $scriptBody += '$ErrorActionPreference = "Continue"'
    $scriptBody += 'Set-Location "' + $BridgePath + '"'
    $scriptBody += '& "' + $PyExe + '" -u "' + (Join-Path $BridgePath 'unified_bridge.py') + '" serve --root "' + $env:USERPROFILE + '" --profile owner-shell --token "' + $Token + '" *>> "' + $LogFile + '"'
    Set-Content -Path $startPs1 -Value ($scriptBody -join "`r`n") -Encoding UTF8
    Write-Host "[OK] Created $startPs1" -ForegroundColor Green

    # Scheduled Task: hidden window, auto-restart, starts at logon
    $Action    = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"")
    $Trigger   = New-ScheduledTaskTrigger -AtLogOn
    $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
    $Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
    Write-Host '[OK] Scheduled task registered: ArenaUnifiedBridge' -ForegroundColor Green
}

function Start-UnifiedTask {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    Write-Host '[OK] Started via Task Scheduler' -ForegroundColor Green

    $startPs1 = Join-Path $BridgePath "start_$TaskName.ps1"
    if (Test-Path $startPs1) {
        Start-Process powershell.exe -ArgumentList ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"") -WindowStyle Hidden -ErrorAction SilentlyContinue
        Write-Host '[OK] Started immediately in hidden window' -ForegroundColor Green
    }
}

# ------------------- Main flow -------------------
if ($Uninstall) {
    Write-Host ''
    Write-Host '=== UNINSTALLING Arena Unified Bridge ===' -ForegroundColor Red
    Stop-OldTasks
    Remove-OldTasks
    $UserPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
    $BinPath = Join-Path $AgentPath 'bin'
    if ($UserPath -like "*$BinPath*") {
        $NewPath = ($UserPath -split ';' | Where-Object { $_ -ne $BinPath }) -join ';'
        [System.Environment]::SetEnvironmentVariable('Path', $NewPath, 'User')
        Write-Host '[OK] Removed bin from User PATH.' -ForegroundColor Green
    }
    Write-Host ''
    Write-Host '=== UNINSTALL COMPLETE ===' -ForegroundColor Green
    return
}

if ($Update) {
    Write-Host ''
    Write-Host '=== UPDATING Arena Unified Bridge ===' -ForegroundColor Cyan
    Stop-OldTasks
    Start-Sleep -Seconds 2
    Start-UnifiedTask
    Write-Host ''
    Write-Host '=== UPDATE COMPLETE ===' -ForegroundColor Green
    return
}

# Fresh install
Write-Host ''
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host '  Arena Local Agent - Unified Bridge v1.2.0' -ForegroundColor Cyan
Write-Host '  1 process, 1 port, 1 scheduled task' -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Cyan
Write-Host ''

New-Item -ItemType Directory -Force -Path $BridgePath, $AgentPath, "$AgentPath\scripts", "$AgentPath\bin", "$AgentPath\logs", "$AgentPath\queue\inbox", "$AgentPath\queue\running", "$AgentPath\queue\done", "$AgentPath\queue\failed" | Out-Null

# --- Core dependencies ---
$PyExe = Ensure-Python
Ensure-NodeJS

# --- Token ---
$existingToken = Get-Token
if ($existingToken -and $existingToken.Length -ge 20) {
    Write-Host "[OK] Using existing token" -ForegroundColor Green
} else {
    Generate-Token
    $existingToken = Get-Token
}

# --- Python packages ---
Write-Host 'Installing Python packages...' -ForegroundColor Cyan
try {
    Start-Process -FilePath $PyExe -ArgumentList '-m pip install --quiet --upgrade aiohttp httpx requests beautifulsoup4' -NoNewWindow -Wait
    Write-Host '[OK] Python packages ready.' -ForegroundColor Green
} catch {
    Write-Warning 'pip install failed. Run: pip install aiohttp httpx requests beautifulsoup4'
}

# --- agentctl wrapper ---
$AgentBin = Join-Path $AgentPath 'bin'
$AgentctlBat = Join-Path $AgentBin 'agentctl.bat'
$BatContent = "@echo off`r`n`"$PyExe`" `"%~dp0agentctl`" %*"
Set-Content -Path $AgentctlBat -Value $BatContent -Encoding ASCII
Write-Host '[OK] agentctl wrapper created' -ForegroundColor Green

# --- PATH ---
$UserPath = [System.Environment]::GetEnvironmentVariable('Path', 'User')
if ($UserPath -notlike "*$AgentBin*") {
    $Sep = if ($UserPath.Length -eq 0 -or $UserPath.EndsWith(';')) { '' } else { ';' }
    [System.Environment]::SetEnvironmentVariable('Path', $UserPath + $Sep + $AgentBin, 'User')
    Write-Host '[OK] Added bin to User PATH.' -ForegroundColor Green
}

# --- Optional: Git ---
Ensure-Git

# --- Optional: Tailscale ---
Ensure-Tailscale
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if ($ts) {
    $tsStatus = & tailscale status 2>&1 | Select-Object -First 1
    if ($tsStatus -match "offline|not running|Stopped") {
        Write-Host ''
        Write-Host 'Tailscale is installed but not logged in.' -ForegroundColor Yellow
        $tsLogin = Read-Host 'Log in to Tailscale now? [Y/n]'
        if ($tsLogin -eq '' -or $tsLogin -eq 'Y' -or $tsLogin -eq 'y') {
            & tailscale login 2>&1 | ForEach-Object { Write-Host $_ }
            Write-Host '[OK] Tailscale login initiated.' -ForegroundColor Green
        }
    } else {
        Write-Host '[OK] Tailscale is active.' -ForegroundColor Green
    }
}

# --- Optional: Browser automation ---
Write-Host ''
Write-Host '--- Optional: Browser Automation ---' -ForegroundColor Cyan
$chrome = Get-Command chrome -ErrorAction SilentlyContinue
$edge = Get-Command msedge -ErrorAction SilentlyContinue
if (-not $chrome -and -not $edge) {
    Write-Host 'No Chrome/Edge found for headless browser automation.' -ForegroundColor Yellow
    $brAnswer = Read-Host 'Install Microsoft Edge for headless automation? [Y/n]'
    if ($brAnswer -eq '' -or $brAnswer -eq 'Y' -or $brAnswer -eq 'y') {
        if (Get-Command winget -ErrorAction SilentlyContinue) {
            try {
                winget install --id Microsoft.Edge --accept-source-agreements --accept-package-agreements --silent 2>$null
                Write-Host '[OK] Edge installed for browser automation.' -ForegroundColor Green
            } catch {
                Write-Warning 'Edge install failed. Install from https://www.microsoft.com/edge'
            }
        } else {
            Write-Host 'Download Edge from https://www.microsoft.com/edge' -ForegroundColor Yellow
        }
    }
} else {
    Write-Host '[OK] Browser available for automation' -ForegroundColor Green
}

# --- Optional: Superpowers / Dev tools ---
Write-Host ''
Write-Host '--- Optional: Superpowers ---' -ForegroundColor Cyan
$answer = Read-Host 'Install dev tools? (VSCode, 7zip, Windows Terminal) [y/N]'
if ($answer -eq 'Y' -or $answer -eq 'y') {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        try {
            winget install --id Microsoft.VisualStudioCode --accept-source-agreements --accept-package-agreements --silent 2>$null
            winget install --id 7zip.7zip --accept-source-agreements --accept-package-agreements --silent 2>$null
            winget install --id Microsoft.WindowsTerminal --accept-source-agreements --accept-package-agreements --silent 2>$null
            Write-Host '[OK] Dev tools installed.' -ForegroundColor Green
        } catch {
            Write-Warning 'Some dev tools failed to install.'
        }
    } else {
        Write-Host 'winget not available. Install dev tools manually.' -ForegroundColor Yellow
    }
}

# --- Migrate and install ---
Write-Host ''
Write-Host '=== Setting up Unified Bridge ===' -ForegroundColor Yellow
Stop-OldTasks
Remove-OldTasks

Create-UnifiedTask -PyExe $PyExe -Token $existingToken
Start-UnifiedTask

Write-Host ''
Write-Host 'Waiting for bridge to start...' -ForegroundColor Yellow
Start-Sleep -Seconds 5

$healthCheck = $null
try {
    $healthCheck = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 10 -ErrorAction Stop
} catch {}

if ($healthCheck -and $healthCheck.ok) {
    Write-Host "[OK] Bridge is healthy! v$($healthCheck.version)" -ForegroundColor Green
} else {
    Write-Warning "Bridge health check failed. Check log: $LogFile"
}

# --- Summary ---
Write-Host ''
Write-Host '==================================================' -ForegroundColor Green
Write-Host '  ARENA LOCAL AGENT - INSTALLATION COMPLETE!' -ForegroundColor Green
Write-Host '==================================================' -ForegroundColor Green
Write-Host ''
Write-Host '  Dashboard:   http://127.0.0.1:8765/gui' -ForegroundColor White
Write-Host '  Health:      http://127.0.0.1:8765/health' -ForegroundColor White
Write-Host '  Log:         ' -ForegroundColor White -NoNewline; Write-Host $LogFile
Write-Host ''
Write-Host '  Auto-starts at logon, hidden window, auto-restart' -ForegroundColor White
Write-Host '  Stop:    schtasks /End /tn ArenaUnifiedBridge' -ForegroundColor White
Write-Host '  Start:   schtasks /Run /tn ArenaUnifiedBridge' -ForegroundColor White
Write-Host '  Status:  C:\Users\Ivan\arena-local-bridge\status.bat' -ForegroundColor White
Write-Host ''
Write-Host '  Cross-platform: also see install_linux.sh' -ForegroundColor Cyan
Write-Host '==================================================' -ForegroundColor Green
