# Arena Local Agent ??? Windows Installer v14.0-stable (Final Complete Release)
# ?????????????????????????? 5 ?????????? ?? Task Scheduler ?? ?????????????????? ??????????????????/?????????????? ?????????????? ????????????,
# ?????????????????????????????????? Node.js, ???????????????????? ??????????, ?????????????????? agentctl ?? ?????????????????? PATH ?? ?????????????? bat-??????????????.
# ???? 100% ?????????????????? ?? ???????????? v0.4.0 ???? Windows.
# ???????????? ?????????????????? ???????????? ?????????????????????????? (clean slate), ?????????????????????????? ???????????? ?????????? ????????????????, ???????????????????? ?????????? ??????????.
# ?????????????????????????? ?????? ?????????????????????? Python-?????????????????????? (requests, beautifulsoup4, httpx) ?????? ???????????? ???????????????? ?? HTTP-????????????????.
# ?????????????????? ?????????????????? ?? PowerShell 5.1.
# ????????????:    powershell -ExecutionPolicy Bypass -File install_windows_service.ps1
# ????????????????:  powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Uninstall
# ????????????????????: powershell -ExecutionPolicy Bypass -File install_windows_service.ps1 -Update

param([switch]$Uninstall, [switch]$Update)

$ErrorActionPreference = "Stop"

$BridgePath = Join-Path $env:USERPROFILE "arena-local-bridge"
$AgentPath  = Join-Path $env:USERPROFILE "arena-agent"
$TokenPath  = Join-Path $BridgePath "token.txt"

# 100% WINDOWS COMPATIBLE ARGUMENTS:
$Tasks = @(
  @{ Name="ArenaLocalBridge"; Script="$BridgePath\local_bridge.py";
     Args="serve --root `"$env:USERPROFILE`" --profile owner-shell";
     UsesToken=$true; Port=8765 }
  @{ Name="ArenaMcpStream"; Script="$AgentPath\scripts\mcp_stream_server.py";
     Args="--host 127.0.0.1 --port 8767"; UsesToken=$false; Port=8767 }
  @{ Name="ArenaMcpWs"; Script="$AgentPath\scripts\mcp_ws_server.py";
     Args="--host 127.0.0.1 --port 8768"; UsesToken=$false; Port=8768 }
  @{ Name="ArenaTaskRunner"; Script="$AgentPath\bin\agentctl";
     Args="task-watch --interval 5 --max 1"; UsesToken=$false; Port=$null }
  @{ Name="ArenaWebGateway"; Script="$AgentPath\bin\web_gateway.py";
     Args="--host 127.0.0.1 --port 8769"; UsesToken=$false; Port=8769 }
)

# ------------------- Helpers -------------------
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
        Write-Warning "Automatic Node.js installation failed. Please install manually from https://nodejs.org/ and re-run."
        return $null
    }
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    $node = Get-Command node -ErrorAction SilentlyContinue
    return if ($node) { $node.Source } else { $null }
}

function Ensure-Python {
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    
    # Check default paths
    $localPython = "$env:LOCALAPPDATA\Programs\Python"
    if (Test-Path $localPython) {
        $exes = Get-ChildItem -Path $localPython -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue
        if ($exes) { return $exes[0].FullName }
    }
    
    Write-Error "Python installation not found. Please install Python from https://www.python.org/ and tick 'Add python.exe to PATH'."
}

# FORCE Token generation on every run (v13.0)
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

function Stop-AllTasks {
    foreach ($t in $Tasks) {
        $task = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq "Running") {
            Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue | Out-Null
        }
        # Force-kill any processes occupying the ports to prevent address-in-use errors!
        if ($t.Port) {
            try {
                $nets = Get-NetTCPConnection -LocalPort $t.Port -State Listen -ErrorAction SilentlyContinue
                foreach ($net in $nets) {
                    if ($net.OwningProcess -gt 0) {
                        Stop-Process -Id $net.OwningProcess -Force -ErrorAction SilentlyContinue
                        Write-Host "  - Terminated active process $($net.OwningProcess) holding port $($t.Port)"
                    }
                }
            } catch {}
        }
    }
}

function Remove-AllTasks {
    foreach ($t in $Tasks) {
        $task = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($task) {
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
            Write-Host "[OK] removed $($t.Name)"
        }
    }
}

function Create-Tasks {
    $PyExe = Ensure-Python
    foreach ($t in $Tasks) {
        $startPs1 = Join-Path $BridgePath ("start_" + $t.Name + ".ps1")
        $body = @()
        
        $body += '$ErrorActionPreference = "Continue"'
        $body += 'Set-Location "' + $BridgePath + '"'
        
        $ArgsLine = $t.Args
        if ($t.UsesToken) {
            $data = [System.IO.File]::ReadAllBytes($TokenPath)
            $TokenString = [System.Text.Encoding]::UTF8.GetString($data).Trim()
            $ArgsLine += " --token `"$TokenString`""
        }
        
        $logFile = Join-Path $AgentPath "logs\$($t.Name).log"
        # Run with "-u" unbuffered flag for direct and unbuffered log output
        $body += '& "' + $PyExe + '" -u "' + $t.Script + '" ' + $ArgsLine + ' *>> "' + $logFile + '"'
        Set-Content -Path $startPs1 -Value ($body -join "`r`n") -Encoding UTF8

        $Action    = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"")
        $Trigger   = New-ScheduledTaskTrigger -AtLogOn
        $Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        $Settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        Register-ScheduledTask -TaskName $t.Name -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Force | Out-Null
        Write-Host "[OK] registered $($t.Name) (port $($t.Port))"
    }
}

function Start-AllTasks {
    foreach ($t in $Tasks) {
        # 1. Start via Task Scheduler
        $task = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($task) {
            try {
                Start-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue | Out-Null
            } catch {}
        }
        
        # 2. ALSO start the process directly right now in the background, but WITHOUT -NoNewWindow so it doesn't hide parent terminal!
        $startPs1 = Join-Path $BridgePath ("start_" + $t.Name + ".ps1")
        if (Test-Path $startPs1) {
            try {
                Start-Process powershell.exe -ArgumentList ("-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"" + $startPs1 + "`"") -NoNewWindow: $false -ErrorAction SilentlyContinue
                Write-Host "[OK] started $($t.Name) immediately." -ForegroundColor Green
            } catch {
                Write-Warning "Could not start $($t.Name) immediately."
            }
        }
    }
}

# ------------------- Main flow -------------------
if ($Uninstall) {
    Stop-AllTasks
    Remove-AllTasks
    # Remove bin from User PATH if present
    $UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $BinPath = Join-Path $AgentPath "bin"
    if ($UserPath -like "*$BinPath*") {
        # Clean up path safely
        $NewPath = ($UserPath -split ";" | Where-Object { $_ -ne $BinPath }) -join ";"
        [System.Environment]::SetEnvironmentVariable("Path", $NewPath, "User")
        Write-Host "[OK] Removed $BinPath from User PATH." -ForegroundColor Green
    }
    Write-Host "`n=== UNINSTALL COMPLETE ===" -ForegroundColor Green
    return
}

# Ensure dirs
New-Item -ItemType Directory -Force -Path $BridgePath, $AgentPath, "$AgentPath\scripts", "$AgentPath\bin", "$AgentPath\logs" | Out-Null

# Python
$PyExe = Ensure-Python
Write-Host "[OK] using Python: $PyExe"

# Node.js (for MCP plugins)
$null = Ensure-NodeJS

# Token
Generate-Token

# DEPENDENCIES INSTALLATION:
Write-Host "Installing/Updating required Python packages (httpx, requests, beautifulsoup4) via pip..." -ForegroundColor Cyan
try {
    Start-Process -FilePath $PyExe -ArgumentList "-m pip install --quiet --upgrade httpx requests beautifulsoup4" -NoNewWindow -Wait
    Write-Host "[OK] Python packages ready." -ForegroundColor Green
} catch {
    Write-Warning "Could not install python dependencies automatically. Please run manually: pip install httpx requests beautifulsoup4"
}

# Create agentctl.bat wrapper
$AgentBin = Join-Path $AgentPath "bin"
$AgentctlBat = Join-Path $AgentBin "agentctl.bat"
$BatContent = "@echo off`r`n`"$PyExe`" `"%~dp0agentctl`" %*"
Set-Content -Path $AgentctlBat -Value $BatContent -Encoding ASCII
Write-Host "[OK] created Windows executable wrapper: $AgentctlBat" -ForegroundColor Green

# Add bin path to User persistent PATH
$UserPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$AgentBin*") {
    $Separator = if ($UserPath.Length -eq 0 -or $UserPath.EndsWith(";")) { "" } else { ";" }
    [System.Environment]::SetEnvironmentVariable("Path", $UserPath + $Separator + $AgentBin, "User")
    Write-Host "[OK] Added $AgentBin to User persistent PATH. (Please restart any open terminal windows to apply)" -ForegroundColor Green
}

# Stop and completely unregister old tasks before creating and starting the new ones.
Write-Host "`n=== CLEAN SLATE: Stopping and removing old tasks... ===" -ForegroundColor Yellow
Stop-AllTasks
Remove-AllTasks

# Re-create and restart everything fresh
Create-Tasks
Start-AllTasks

# ------------------- Interactive Prompts helper (v8.0) -------------------
function Ask-UserChoice {
    param(
        [string]$Question,
        [bool]$DefaultValue
    )
    $suffix = if ($DefaultValue) { " [Y/n]" } else { " [y/N]" }
    Write-Host -NoNewline "$Question$($suffix): " -ForegroundColor Yellow
    $ans = Read-Host
    if ([string]::IsNullOrWhiteSpace($ans)) {
        return $DefaultValue
    }
    if ($ans.Trim().ToLower() -eq "y" -or $ans.Trim().ToLower() -eq "yes") {
        return $true
    }
    if ($ans.Trim().ToLower() -eq "n" -or $ans.Trim().ToLower() -eq "no") {
        return $false
    }
    return $DefaultValue
}

# ------------------- Optional: Git (Standalone Silent Installer) -------------------
$InstallGit = $false
$GitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $GitCmd) {
    if (Ask-UserChoice "Git not found on your system. Attempt automatic installation?" $true) {
        $InstallGit = $true
    }
}

if ($InstallGit) {
    Write-Host "`n=== Downloading Git standalone installer... ===" -ForegroundColor Yellow
    $gitUrl = "https://github.com/git-for-windows/git/releases/download/v2.45.0.windows.1/Git-2.45.0-64-bit.exe"
    $gitMsi = Join-Path $env:TEMP "git-setup.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $gitUrl -OutFile $gitMsi -UseBasicParsing
        Write-Host "Running Git installer silently..." -ForegroundColor Cyan
        Start-Process -FilePath $gitMsi -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP-" -Wait -NoNewWindow
        Remove-Item $gitMsi -Force
        Write-Host "[OK] Git successfully installed!" -ForegroundColor Green
    } catch {
        Write-Warning "Automatic Git installation failed. Please install manually from https://git-scm.com/download/win"
    }
}

# ------------------- Optional: UV & BrowserAct -------------------
$SetupBrowserAct = $false
if (Ask-UserChoice "Install/Update BrowserAct (including stealth Camoufox binaries)?" $false) {
    $SetupBrowserAct = $true
}

if ($SetupBrowserAct) {
    $UvCmd = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $UvCmd) {
        Write-Host "`n=== UV Package Manager not found. Installing silently... ===" -ForegroundColor Yellow
        try {
            Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1" | Invoke-Expression
            $env:Path = "C:\\Users\\$env:USERNAME\\.local\\bin;" + $env:Path
            Write-Host "[OK] UV successfully installed!" -ForegroundColor Green
        } catch {
            Write-Warning "Automatic UV installation failed."
        }
    }

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Host "`nInstalling/Updating browser-act-cli via uv..." -ForegroundColor Cyan
        try {
            Start-Process uv -ArgumentList "tool install browser-act-cli --python 3.12" -Wait -NoNewWindow
            Write-Host "Initializing BrowserAct browser binaries (fetching Camoufox)..." -ForegroundColor Cyan
            Start-Process uv -ArgumentList "tool run camoufox fetch" -Wait -NoNewWindow
            Write-Host "[OK] BrowserAct is fully installed and pre-initialized!" -ForegroundColor Green
        } catch {
            Write-Warning "Could not install browser-act automatically."
        }
    }
}

# ------------------- Optional: Superpowers -------------------
$SetupSuperpowers = $false
if (Ask-UserChoice "Download/Update Superpowers (agentic developer skills)?" $false) {
    $SetupSuperpowers = $true
}

if ($SetupSuperpowers) {
    Write-Host "`n=== Downloading and updating Superpowers framework... ===" -ForegroundColor Yellow
    $PyExe = Ensure-Python
    Start-Process -FilePath $PyExe -ArgumentList "-u `"$AgentPath\\bin\\agentctl`" sp sync" -Wait -NoNewWindow
}

# ------------------- Optional: Tailscale Login (v13.0) -------------------
$LoginTailscale = $false
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    if (Ask-UserChoice "Run 'tailscale login' to authenticate or renew your Tailscale session?" $false) {
        $LoginTailscale = $true
    }
}

if ($LoginTailscale) {
    Write-Host "`n=== Launching Tailscale login... ===" -ForegroundColor Yellow
    Start-Process tailscale -ArgumentList "login" -Wait -NoNewWindow
}

# Read Token Value and Find Tailscale URL on-the-fly (v6.2)
$TokenVal = (Get-Content -Path $TokenPath -Raw).Trim()
$FunnelUrl = "Not enabled"
if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    $statusArray = tailscale serve status 2>$null
    if ($statusArray) {
        $statusString = $statusArray -join "`r`n"
        if ($statusString -match "(https://[^\\s]+)") {
            $FunnelUrl = $Matches[1]
        }
    }
}

Write-Host ""
Write-Host "=== INSTALLATION COMPLETE ===" -ForegroundColor Green
Write-Host "Tasks registered and started. They will auto-start at every logon."
Write-Host ""
Write-Host "[TOKEN] YOUR ACCESS TOKEN:  $TokenVal" -ForegroundColor Cyan
Write-Host "[URL] YOUR TAILSCALE URL: $FunnelUrl" -ForegroundColor Cyan
Write-Host ""
Write-Host "To expose to internet (if not enabled):  tailscale funnel --bg 8765"
Write-Host "To open local dashboard:                 http://127.0.0.1:8765/gui"
Write-Host "To update later:                         run update.bat in $AgentPath"
Write-Host "=============================="

