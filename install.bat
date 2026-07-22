@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  Arena Unified Bridge - Windows Installer v2.1.2
REM  Full parity with install.sh. Window stays open on errors.
REM ============================================================

REM === ANTI-CLOSE: Re-launch with cmd /k so window NEVER closes ===
if "%~1"==":RUN" goto :main
cmd /k "%~0" :RUN
exit /b

:main
echo.
echo  ========================================
echo   Arena Unified Bridge - Installer
echo  ========================================
echo.

set "BRIDGE_DIR=%~dp0"
if "%BRIDGE_DIR:~-1%"=="\" set "BRIDGE_DIR=%BRIDGE_DIR:~0,-1%"
REM v4.60.9: install.bat used to break when BRIDGE_DIR contained '(' or ')'
REM (e.g. 'C:\Users\...\arena-agent (1)\arena-agent') because cmd.exe parses
REM the entire body of a parenthesised block at once, and a ')' inside a
REM %BRIDGE_DIR% expansion would close the block early. Every %BRIDGE_DIR%
REM / %TOKEN_FILE% / %REQ_FILE% / %PYTHON% is now referenced via delayed
REM expansion (!VAR!) so the value is inserted AFTER block parsing.
echo !BRIDGE_DIR! | findstr /r "[()]" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Install directory contains parentheses:
    echo        !BRIDGE_DIR!
    echo        The v4.60.9+ installer handles this correctly via delayed
    echo        expansion. If you see any "unexpected occurrence" errors,
    echo        report them - they should be gone.
    echo.
)
if defined ARENA_PORT (set "PORT=%ARENA_PORT%") else (set "PORT=8765")
set "PROFILE=owner-shell"
set "TOKEN_FILE=!BRIDGE_DIR!\token.txt"

REM ============================================================
REM Step 1: Find Python
REM ============================================================
echo [1/6] Finding Python...
set "PYTHON="
where python >nul 2>&1
if not errorlevel 1 set "PYTHON=python"
if not defined PYTHON where python3 >nul 2>&1
if not defined PYTHON if not errorlevel 1 set "PYTHON=python3"
if not defined PYTHON where py >nul 2>&1
if not defined PYTHON if not errorlevel 1 set "PYTHON=py"
if not defined PYTHON (
    echo.
    echo  [ERROR] Python not found!
    echo  Install Python 3.10+ and add to PATH.
    echo  Download: https://www.python.org/downloads/
    echo  Check "Add Python to PATH" during install.
    echo.
    goto :end
)
for /f "delims=" %%v in ('!PYTHON! --version 2^>^&1') do echo       %%v found

REM --- Read version via helper ---
set "VERSION=unknown"
if exist "!BRIDGE_DIR!\_arena_helper.py" (
    for /f "delims=" %%v in ('!PYTHON! "!BRIDGE_DIR!\_arena_helper.py" version 2^>nul') do set "VERSION=%%v"
)
echo       Bridge v!VERSION!

REM --- Soft version-check: query GitHub releases API via Python urllib ---
REM We use Python urllib directly (no curl pipe, no \" escapes inside if-blocks)
REM so the cmd parser does not break on quoted strings.
set "LATEST_VERSION="
for /f "delims=" %%v in ('!PYTHON! -c "import urllib.request,json; req=urllib.request.Request('https://api.github.com/repos/IvanSkainet/arena-agent/releases/latest'); print(json.load(urllib.request.urlopen(req,timeout=8)).get('tag_name','').lstrip('v'))" 2^>nul') do set "LATEST_VERSION=%%v"
if not defined LATEST_VERSION (
    echo       [INFO] Could not check GitHub for newer releases - offline or rate-limited.
) else if /I "!LATEST_VERSION!"=="!VERSION!" (
    echo       [OK] You are on the latest release.
) else (
    echo       [INFO] A different version is available on GitHub: v!LATEST_VERSION!
    echo              You are running: v!VERSION!
    echo              To upgrade manually: download from https://github.com/IvanSkainet/arena-agent/releases
    echo              Or, if this is a git clone: cd to bridge dir, then run "git pull", then "install.bat"
)

echo.
echo  ========================================
echo   TRANSPARENCY NOTICE - BACKGROUND SERVICE
echo  ========================================
echo   Arena Unified Bridge is a local automation server.
echo   This installer will register a visible background service or scheduled task:
echo.
echo     Service/task name: ArenaUnifiedBridge
echo     Local URL:         http://127.0.0.1:%PORT%
echo     You may see:       python.exe, unified_bridge.py, or legacy helper names
echo.
echo   This is expected and is NOT stealth software. It lets your AI tools keep
echo   talking to this machine after this terminal is closed.
echo.
echo   To inspect later:
echo     schtasks /query /tn "ArenaUnifiedBridge" /fo LIST /v
echo     sc query ArenaUnifiedBridge
echo.
echo   To remove later:
echo     uninstall.bat
echo.
if /I "%ARENA_ACCEPT_BACKGROUND%"=="1" goto :transparency_ok
if /I "%ARENA_ASSUME_YES%"=="1" goto :transparency_ok
set "ARENA_BG_CONFIRM="
set /p "ARENA_BG_CONFIRM=Continue and install/update the background service? [y/N]: "
if /I not "%ARENA_BG_CONFIRM%"=="Y" (
    echo.
    echo  Installation aborted by user. No service/task was installed by this run.
    echo  Set ARENA_ACCEPT_BACKGROUND=1 to skip this prompt in automation.
    goto :end
)
:transparency_ok

REM ============================================================
REM Step 2: Install Python dependencies (PEP 668 aware, verified)
REM ============================================================
echo.
echo [2/6] Installing Python dependencies...
set "REQ_FILE=!BRIDGE_DIR!\requirements.txt"
if not exist "!REQ_FILE!" set "REQ_FILE="

set "DEPS_OK="

REM 1) Try plain install.
if defined REQ_FILE (
    !PYTHON! -m pip install -r "!REQ_FILE!"
) else (
    !PYTHON! -m pip install aiohttp psutil websockets
)
if not errorlevel 1 set "DEPS_OK=plain"

REM 2) --user (writable per-user site).
if not defined DEPS_OK (
    if defined REQ_FILE (
        !PYTHON! -m pip install --user -r "!REQ_FILE!"
    ) else (
        !PYTHON! -m pip install --user aiohttp psutil websockets
    )
    if not errorlevel 1 set "DEPS_OK=user"
)

REM 3) PEP 668 override (mostly for Cygwin/MSYS Python on Windows, harmless otherwise).
if not defined DEPS_OK (
    if defined REQ_FILE (
        !PYTHON! -m pip install --user --break-system-packages -r "!REQ_FILE!"
    ) else (
        !PYTHON! -m pip install --user --break-system-packages aiohttp psutil websockets
    )
    if not errorlevel 1 set "DEPS_OK=pep668"
)

REM 4) Project-local venv fallback.
if not defined DEPS_OK (
    echo       [WARN] pip refused every strategy; falling back to a project venv
    !PYTHON! -m venv "!BRIDGE_DIR!\.venv"
    if errorlevel 1 (
        echo       [ERR] venv creation failed
        goto :end
    )
    set "PYTHON=!BRIDGE_DIR!\.venv\Scripts\python.exe"
    if defined REQ_FILE (
        !PYTHON! -m pip install -r "!REQ_FILE!"
    ) else (
        !PYTHON! -m pip install aiohttp psutil websockets
    )
    if errorlevel 1 (
        echo       [ERR] venv pip install failed
        goto :end
    )
    set "DEPS_OK=venv:!BRIDGE_DIR!\.venv"
)

REM Verify the import actually works before pretending everything is fine.
!PYTHON! -c "import aiohttp, sys; print('aiohttp', aiohttp.__version__)"
if errorlevel 1 (
    echo       [ERR] Python packages installed but 'import aiohttp' still fails
    echo       Try manually:
    echo         !PYTHON! -m pip install --user -r "!REQ_FILE!"
    echo       Or create a venv:
    echo         !PYTHON! -m venv "!BRIDGE_DIR!\.venv"
    echo         "!BRIDGE_DIR!\.venv\Scripts\python.exe" -m pip install -r "!REQ_FILE!"
    goto :end
)
echo       Done. (via: %DEPS_OK%)

REM ============================================================
REM Step 3: Create directories + token
REM ============================================================
echo.
echo [3/6] Creating directory structure...
for %%d in (memory missions hooks hooks\pre_skill.d hooks\post_skill.d logs queue queue\inbox queue\running queue\done queue\failed reports reports\shots backups mcp subagents projects skills scripts bin) do (
    if not exist "!BRIDGE_DIR!\%%d" mkdir "!BRIDGE_DIR!\%%d"
)
echo       Done.

if not exist "!TOKEN_FILE!" (
    !PYTHON! -c "import secrets;print(secrets.token_urlsafe(32),end='')" >"!TOKEN_FILE!"
    echo       New auth token generated.
) else (
    echo       Existing token preserved.
)

set "AUTH_TOKEN="
if exist "!TOKEN_FILE!" set /p "AUTH_TOKEN=" <"!TOKEN_FILE!"

REM ============================================================
REM Step 4: Optional Components
REM ============================================================
echo.
echo  ========================================
echo   Optional Components
echo  ========================================
echo.

REM --- Tailscale ---
where tailscale >nul 2>&1
if errorlevel 1 (
    echo [INFO] Tailscale not found. Tailscale Funnel is the recommended way
    echo       to expose the bridge to the internet - real HTTPS via Let's Encrypt,
    echo       no port-forward. Browser-based AI dashboards can call you directly.
    echo.
    echo       Installing Tailscale adds a system package - requires admin elevation.
    echo       After install, you will need to run:
    echo         1. tailscale login  - opens a browser URL, sign in with Google/GitHub/etc.
    echo         2. tailscale funnel --bg %PORT%
    echo            This exposes http://127.0.0.1:%PORT% to the internet via HTTPS.
    echo.
    set "TS_INSTALL_CONFIRM="
    set /p "TS_INSTALL_CONFIRM=Install Tailscale now via winget? [y/N]: "
    if /I "!TS_INSTALL_CONFIRM!"=="Y" (
        where winget >nul 2>&1
        if not errorlevel 1 (
            echo [INFO] Running: winget install --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
            winget install --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
            where tailscale >nul 2>&1
            if errorlevel 1 (
                echo [WARN] winget install may have failed. Install manually:
                echo        https://tailscale.com/download/windows
            ) else (
                echo [OK] Tailscale installed. Next steps:
                echo        1. Open a new terminal - to refresh PATH
                echo        2. Run: tailscale login
                echo        3. Run: tailscale funnel --bg %PORT%
            )
        ) else (
            echo [WARN] winget not available. Install Tailscale manually:
            echo        https://tailscale.com/download/windows
            echo        Then: tailscale login
            echo        Then: tailscale funnel --bg %PORT%
        )
    ) else (
        echo [INFO] Tailscale install skipped. To set up later:
        echo        winget install --id Tailscale.Tailscale
        echo        tailscale login
        echo        tailscale funnel --bg %PORT%
        echo        Alternative: cloudflared - see below - also exposes the bridge.
    )
    goto :tailscale_done
)
echo [OK] Tailscale is installed
set "TS_URL="
for /f "delims=" %%u in ('tailscale status --json 2^>nul ^| !PYTHON! -c "import json,sys;d=json.load(sys.stdin);dns=d.get('Self',{}).get('DNSName','')or d.get('DNSName','');print(dns.rstrip('.'))if dns else''" 2^>nul') do set "TS_URL=%%u"
if not defined TS_URL (
    echo [WARN] Tailscale installed but not logged in. Run: tailscale login
    goto :tailscale_done
)
echo [OK] Tailscale connected: %TS_URL%
:tailscale_done

REM --- cloudflared ---
set "CLOUDFLARED_BIN="
where cloudflared >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%p in ('where cloudflared 2^>nul') do if not defined CLOUDFLARED_BIN set "CLOUDFLARED_BIN=%%p"
)
if not defined CLOUDFLARED_BIN if exist "!BRIDGE_DIR!\cloudflared.exe" set "CLOUDFLARED_BIN=!BRIDGE_DIR!\cloudflared.exe"
if defined CLOUDFLARED_BIN (
    for /f "delims=" %%v in ('"%CLOUDFLARED_BIN%" --version 2^>nul') do if not defined CLOUDFLARED_VERSION set "CLOUDFLARED_VERSION=%%v"
    echo [OK] cloudflared present: !CLOUDFLARED_VERSION!
    echo [INFO] Checking cloudflared latest download availability...
    curl --max-time 20 -fsI "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" >nul 2>&1
    if errorlevel 1 echo [WARN] Could not verify cloudflared latest release - network/GitHub unavailable.
    goto :cloudflared_done
)
echo [INFO] cloudflared not found. It installs INSIDE the bridge directory.
echo       Path: !BRIDGE_DIR!\cloudflared.exe - 50 MB. Tailscale Funnel is the
echo       recommended option; cloudflared is an alternative for environments
echo       where Tailscale cannot run.
set "CF_CONFIRM="
set /p "CF_CONFIRM=Download cloudflared.exe - 50 MB - to bridge dir? [y/N]: "
if /I not "%CF_CONFIRM%"=="Y" (
    echo [INFO] cloudflared download skipped. Get it later from:
    echo        https://github.com/cloudflare/cloudflared/releases/latest
    goto :cloudflared_done
)
echo [INFO] Downloading cloudflared.exe for Cloudflare Quick Tunnels...
curl --max-time 120 -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -o "!BRIDGE_DIR!\cloudflared.exe" 2>nul
if exist "!BRIDGE_DIR!\cloudflared.exe" (
    set "CLOUDFLARED_BIN=!BRIDGE_DIR!\cloudflared.exe"
    for /f "delims=" %%v in ('"!BRIDGE_DIR!\cloudflared.exe" --version 2^>nul') do if not defined CLOUDFLARED_VERSION set "CLOUDFLARED_VERSION=%%v"
    echo [OK] cloudflared installed at !BRIDGE_DIR!\cloudflared.exe - !CLOUDFLARED_VERSION!
) else (
    echo [WARN] cloudflared download skipped/failed. Get it later: https://github.com/cloudflare/cloudflared/releases/latest
)
:cloudflared_done

REM --- bore (v4.47.0 - zero-account TCP relay through bore.pub) ---
REM Not bundled. Two install paths on Windows:
REM   1. If Rust's cargo is present, 'cargo install bore-cli' (~30s build).
REM   2. Otherwise fetch the release zip and unpack bore.exe into
REM      !BRIDGE_DIR!. System-first resolution in arena/admin/bore.py
REM      finds either source (PATH or !BRIDGE_DIR!\bore.exe).
set "BORE_BIN="
where bore >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%p in ('where bore 2^>nul') do if not defined BORE_BIN set "BORE_BIN=%%p"
)
if not defined BORE_BIN if exist "!BRIDGE_DIR!\bore.exe" set "BORE_BIN=!BRIDGE_DIR!\bore.exe"
if defined BORE_BIN (
    set "BORE_VERSION="
    for /f "delims=" %%v in ('"%BORE_BIN%" --version 2^>nul') do if not defined BORE_VERSION set "BORE_VERSION=%%v"
    echo [OK] bore present: !BORE_VERSION!
    goto :bore_done
)

REM Try cargo first when available (always latest, no version pinning).
where cargo >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Rust detected. Installing bore via 'cargo install bore-cli' - about 30 seconds.
    set "BORE_CARGO_CONFIRM="
    set /p "BORE_CARGO_CONFIRM=Install bore via cargo? [Y/n]: "
    if /I "!BORE_CARGO_CONFIRM!"=="N" goto :bore_download
    if /I "!BORE_CARGO_CONFIRM!"=="No" goto :bore_download
    cargo install bore-cli >nul 2>&1
    if not errorlevel 1 (
        echo [OK] bore installed via cargo - available on PATH via ~/.cargo/bin
        goto :bore_done
    )
    echo [WARN] cargo install bore-cli failed - falling back to release download.
)

:bore_download
echo [INFO] bore not found. Installs INSIDE the bridge directory.
echo       Path: !BRIDGE_DIR!\bore.exe - about 2 MB.
echo       bore is the zero-account TCP relay through bore.pub - no signup needed.
echo.
echo [NOTE] Windows Defender is known to flag bore.exe as a false positive
echo        (Trojan:Win32/Wacatac.B!ml). bore is a legitimate open-source
echo        Rust binary from https://github.com/ekzhang/bore (source-buildable,
echo        MIT-licensed, verified via published SHA256 after download).
echo        If Defender removes it after install, either:
echo          - add !BRIDGE_DIR!\bore.exe to Defender exclusions, or
echo          - skip bore and use tailscale/cloudflared/ngrok instead.
echo.
set "BORE_CONFIRM="
set /p "BORE_CONFIRM=Download bore.exe - about 2 MB - to bridge dir? [y/N]: "
if /I not "%BORE_CONFIRM%"=="Y" (
    echo [INFO] bore skipped. Get it later from:
    echo        https://github.com/ekzhang/bore/releases
    goto :bore_done
)

REM Resolve latest tag via GitHub API; fall back to a known-good pin.
set "BORE_TAG="
for /f "delims=" %%t in ('curl --max-time 20 -fsSL "https://api.github.com/repos/ekzhang/bore/releases/latest" 2^>nul ^| "%PYTHON_EXE%" -c "import json,sys; print(json.load(sys.stdin).get('tag_name',''))" 2^>nul') do if not defined BORE_TAG set "BORE_TAG=%%t"
if not defined BORE_TAG set "BORE_TAG=v0.6.0"

set "BORE_ZIP=%TEMP%\bore-%BORE_TAG%.zip"
set "BORE_URL=https://github.com/ekzhang/bore/releases/download/%BORE_TAG%/bore-%BORE_TAG%-x86_64-pc-windows-msvc.zip"

echo [INFO] Downloading bore %BORE_TAG% for Windows x86_64...
curl --max-time 120 -fsSL "!BORE_URL!" -o "!BORE_ZIP!" 2>nul
if not exist "!BORE_ZIP!" (
    echo [WARN] bore download failed - network/GitHub unavailable. Get it later: https://github.com/ekzhang/bore/releases
    goto :bore_done
)

REM Windows 10 1803+ has a built-in tar that unpacks zips.
tar -xf "!BORE_ZIP!" -C "!BRIDGE_DIR!" 2>nul
if exist "!BRIDGE_DIR!\bore.exe" (
    set "BORE_BIN=!BRIDGE_DIR!\bore.exe"
    for /f "delims=" %%v in ('"!BRIDGE_DIR!\bore.exe" --version 2^>nul') do if not defined BORE_VERSION set "BORE_VERSION=%%v"
    echo [OK] bore %BORE_TAG% installed at !BRIDGE_DIR!\bore.exe - !BORE_VERSION!
) else (
    echo [WARN] bore zip downloaded but extraction failed. Older Windows without built-in tar?
    echo        Unzip !BORE_ZIP! manually and place bore.exe in !BRIDGE_DIR!
)
del "!BORE_ZIP!" >nul 2>&1
:bore_done

REM --- SuperPowers ---
if exist "!BRIDGE_DIR!\skills\superpowers\skills" goto :sp_exists
echo [INFO] SuperPowers is a 14-skill agentic framework - TDD, debugging, planning.
echo       It clones into the bridge directory: !BRIDGE_DIR!\skills\superpowers
set "SP_CONFIRM="
set /p "SP_CONFIRM=Install SuperPowers? [y/N]: "
if /I not "%SP_CONFIRM%"=="Y" (
    echo [INFO] SuperPowers skipped. Install later with:
    echo        git clone https://github.com/obra/superpowers.git skills\superpowers
    goto :sp_done
)
echo [INFO] Installing SuperPowers from GitHub...
git clone --depth 1 https://github.com/obra/superpowers.git "!BRIDGE_DIR!\skills\superpowers" >nul 2>&1
if exist "!BRIDGE_DIR!\skills\superpowers\skills" (
    echo [OK] SuperPowers installed
) else (
    echo [WARN] SuperPowers clone failed. Install later:
    echo        git clone https://github.com/obra/superpowers.git skills\superpowers
)
goto :sp_done
:sp_exists
for /f %%c in ('dir /b "!BRIDGE_DIR!\skills\superpowers\skills" 2^>nul ^| find /c /v ""') do echo [OK] SuperPowers already installed - %%c skills
if exist "!BRIDGE_DIR!\skills\superpowers\.git" (
    for /f "delims=" %%r in ('git -C "!BRIDGE_DIR!\skills\superpowers" rev-parse --short HEAD 2^>nul') do echo [INFO] SuperPowers revision: %%r
    echo [INFO] Checking SuperPowers updates...
    git -C "!BRIDGE_DIR!\skills\superpowers" pull --ff-only --quiet >nul 2>&1
    if errorlevel 1 (
        echo [WARN] SuperPowers update check failed/skipped.
    ) else (
        echo [OK] SuperPowers is up to date or fast-forwarded.
    )
)
:sp_done

REM --- BrowserAct ---
where browser-act >nul 2>&1
if not errorlevel 1 (
    set "BA_VERSION="
    for /f "delims=" %%v in ('browser-act --version 2^>nul') do if not defined BA_VERSION set "BA_VERSION=%%v"
    echo [OK] BrowserAct already installed: !BA_VERSION!
    where uv >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Checking BrowserAct updates via uv...
        uv tool upgrade browser-act-cli >nul 2>&1
        if errorlevel 1 (
            echo [WARN] BrowserAct update check failed/skipped.
        ) else (
            echo [OK] BrowserAct is up to date or upgraded.
        )
    )
    goto :ba_done
)
where uv >nul 2>&1
if errorlevel 1 (
    echo [INFO] BrowserAct requires uv. Install: https://docs.astral.sh/uv/getting-started/installation/
    goto :ba_done
)
echo [INFO] BrowserAct installs GLOBALLY via uv tool - in your user PATH,
echo       outside the bridge directory. The bridge calls browser-act via PATH,
echo       so a global install is required for it to work.
set "BA_CONFIRM="
set /p "BA_CONFIRM=Install BrowserAct globally via uv? [y/N]: "
if /I not "%BA_CONFIRM%"=="Y" (
    echo [INFO] BrowserAct skipped. Install later with:
    echo        uv tool install browser-act-cli --python 3.12
    goto :ba_done
)
echo [INFO] Installing BrowserAct via uv tool - global, outside bridge dir...
uv tool install browser-act-cli --python 3.12 >nul 2>&1
where browser-act >nul 2>&1
if errorlevel 1 (
    echo [WARN] BrowserAct install may have failed. Try: uv tool install browser-act-cli --python 3.12
    goto :ba_done
)
for /f "delims=" %%v in ('browser-act --version 2^>nul') do if not defined BA_VERSION set "BA_VERSION=%%v"
echo [OK] BrowserAct installed: !BA_VERSION!
if not exist "!BRIDGE_DIR!\skills\browseract" mkdir "!BRIDGE_DIR!\skills\browseract"
if not exist "!BRIDGE_DIR!\skills\browseract\SKILL.md" curl --max-time 10 -fsSL "https://raw.githubusercontent.com/browser-act/skills/main/browser-act/SKILL.md" -o "!BRIDGE_DIR!\skills\browseract\SKILL.md" 2>nul
:ba_done

REM --- Camoufox ---
where browser-act >nul 2>&1
if errorlevel 1 goto :camoufox_done
echo [INFO] Checking Camoufox stealth browser...
!PYTHON! -c "import camoufox;print(getattr(camoufox,'__version__','installed'))" >"%TEMP%\arena_camoufox_version.txt" 2>nul
if not errorlevel 1 (
    set /p CAMOUFOX_VERSION=<"%TEMP%\arena_camoufox_version.txt"
    del "%TEMP%\arena_camoufox_version.txt" >nul 2>&1
    echo [OK] Camoufox package present: !CAMOUFOX_VERSION!
    echo [INFO] Camoufox downloads ~300MB to a SYSTEM cache directory
    echo       in LOCALAPPDATA\camoufox or USERPROFILE\.cache\camoufox,
    echo       NOT inside the bridge directory.
    set "CAM_CONFIRM="
    set /p "CAM_CONFIRM=Download/refresh Camoufox browser - 300MB to system cache? [y/N]: "
    if /I not "!CAM_CONFIRM!"=="Y" (
        echo [INFO] Camoufox fetch skipped. BrowserAct will use regular Chrome/Chromium.
        goto :camoufox_done
    )
    echo [INFO] Ensuring Camoufox browser files are present/current...
    !PYTHON! -m camoufox fetch >nul 2>&1
    if errorlevel 1 (
        echo [WARN] Camoufox fetch/update failed or skipped.
    ) else (
        echo [OK] Camoufox stealth browser ready.
    )
    goto :camoufox_done
)
echo [INFO] Camoufox package not present. BrowserAct stealth mode may not work.
echo       It should be auto-installed with browser-act-cli. Try:
echo         uv tool install browser-act-cli --python 3.12 --force-reinstall
goto :camoufox_done
:camoufox_done

echo.

REM ============================================================
REM Step 5: Install and start bridge service
REM ============================================================
echo [4/6] Installing as system service...

schtasks /end /tn "ArenaUnifiedBridge" >nul 2>&1
where nssm >nul 2>&1
if not errorlevel 1 (
    nssm stop ArenaUnifiedBridge >nul 2>&1
) else (
    sc query ArenaUnifiedBridge >nul 2>&1
    if not errorlevel 1 (
        sc stop ArenaUnifiedBridge >nul 2>&1
        sc delete ArenaUnifiedBridge >nul 2>&1
        echo       Removed stale Windows service ArenaUnifiedBridge.
    )
)
ping -n 2 127.0.0.1 >nul

for /f "tokens=5" %%P in ('netstat -ano 2^>nul ^| findstr ":%PORT% "') do taskkill /F /PID %%P >nul 2>nul
ping -n 2 127.0.0.1 >nul

echo @echo off> "!BRIDGE_DIR!\start_bridge.bat"
echo cd /d "!BRIDGE_DIR!">> "!BRIDGE_DIR!\start_bridge.bat"
echo set ARENA_AGENT_HOME=!BRIDGE_DIR!>> "!BRIDGE_DIR!\start_bridge.bat"
echo set ARENA_TOKEN_FILE=!TOKEN_FILE!>> "!BRIDGE_DIR!\start_bridge.bat"
echo !PYTHON! -u unified_bridge.py serve --root "%USERPROFILE%" --profile %PROFILE% --port %PORT%>> "!BRIDGE_DIR!\start_bridge.bat"

echo Set WshShell = CreateObject^("WScript.Shell"^)> "!BRIDGE_DIR!\start_hidden.vbs"
echo WshShell.Run """!BRIDGE_DIR!\start_bridge.bat""", 0, False>> "!BRIDGE_DIR!\start_hidden.vbs"

set "SERVICE_METHOD=none"
where nssm >nul 2>&1
if not errorlevel 1 goto :use_nssm

:use_schtasks
set "SERVICE_METHOD=schtasks"
echo       NSSM not found, using Scheduled Task with hidden window...
schtasks /delete /tn "ArenaUnifiedBridge" /f >nul 2>&1
schtasks /create /tn "ArenaUnifiedBridge" /tr "wscript.exe \"!BRIDGE_DIR!\start_hidden.vbs\"" /sc onstart /ru "%USERNAME%" /rl highest /f >nul 2>&1
schtasks /run /tn "ArenaUnifiedBridge" >nul 2>&1
echo       [OK] Scheduled task installed and started.
goto :service_installed

:use_nssm
set "SERVICE_METHOD=nssm"
echo       Using NSSM service manager...
nssm remove ArenaUnifiedBridge confirm >nul 2>&1
set "PYW=!PYTHON!"
for %%p in ("!PYTHON!") do (
    if exist "%%~dpPpythonw%%~xP" set "PYW=%%~dpPpythonw%%~xP"
)
nssm install ArenaUnifiedBridge "!PYW!" "-u !BRIDGE_DIR!\unified_bridge.py serve --root %USERPROFILE% --profile %PROFILE% --port %PORT%" >nul 2>&1
nssm set ArenaUnifiedBridge AppDirectory "!BRIDGE_DIR!" >nul 2>&1
nssm set ArenaUnifiedBridge DisplayName "Arena Unified Bridge v!VERSION!" >nul 2>&1
nssm set ArenaUnifiedBridge Start SERVICE_AUTO_START >nul 2>&1
nssm set ArenaUnifiedBridge AppStdout "!BRIDGE_DIR!\logs\bridge.log" >nul 2>&1
nssm set ArenaUnifiedBridge AppStderr "!BRIDGE_DIR!\logs\bridge_err.log" >nul 2>&1
nssm set ArenaUnifiedBridge AppRotateFiles 1 >nul 2>&1
nssm set ArenaUnifiedBridge AppRotateBytes 5242880 >nul 2>&1
nssm set ArenaUnifiedBridge AppRotateBackups 3 >nul 2>&1
nssm set ArenaUnifiedBridge AppEnvironmentExtra ARENA_AGENT_HOME=!BRIDGE_DIR! ARENA_TOKEN_FILE=!TOKEN_FILE! >nul 2>&1
nssm start ArenaUnifiedBridge >nul 2>&1
echo       [OK] NSSM service installed and started.

:service_installed

netsh advfirewall firewall show rule name="Arena Bridge" >nul 2>&1
if not errorlevel 1 goto :firewall_done
netsh advfirewall firewall add rule name="Arena Bridge" dir=in action=allow protocol=TCP localport=%PORT% >nul 2>&1
if not errorlevel 1 echo       [OK] Firewall rule added for port %PORT%
:firewall_done

REM ============================================================
REM Step 6: Wait for bridge and verify
REM ============================================================
echo.
echo [5/6] Waiting for bridge to start...
set "HEALTHY=0"
for /L %%i in (1,1,30) do (
    if "!HEALTHY!"=="0" (
        curl --max-time 3 -fsS "http://127.0.0.1:%PORT%/health" >"%TEMP%\arena_health.json" 2>nul
        if not errorlevel 1 (
            set "HEALTHY=1"
            set "HEALTH_VERSION=!VERSION!"
            for /f "delims=" %%v in ('!PYTHON! -c "import json;print(json.load(open(r'%TEMP%\arena_health.json')).get('version',''))" 2^>nul') do set "HEALTH_VERSION=%%v"
            del "%TEMP%\arena_health.json" >nul 2>&1
            echo       Bridge is healthy. v!HEALTH_VERSION!
        ) else (
            echo       Waiting... %%i/30
            ping -n 3 127.0.0.1 >nul
        )
    )
)
if "!HEALTHY!"=="1" goto :healthy_ok
echo.
echo  [WARN] Bridge not responding after 90 seconds.
echo.
echo  Check logs: !BRIDGE_DIR!\logs\bridge.log
echo  !BRIDGE_DIR!\logs\bridge_err.log
echo.
echo  Start manually:
echo    cd /d "!BRIDGE_DIR!"
echo    !PYTHON! -u unified_bridge.py serve --root "%USERPROFILE%" --port %PORT%
echo.
:healthy_ok

REM ============================================================
REM Summary
REM ============================================================
echo.
echo  ========================================
echo   INSTALLATION COMPLETE
echo  ========================================
echo.
echo   Directory:  !BRIDGE_DIR!
echo   Dashboard:  http://127.0.0.1:%PORT%/gui
echo   Health:     http://127.0.0.1:%PORT%/health
echo   Token file: !TOKEN_FILE!
echo.

if not defined AUTH_TOKEN goto :no_token
echo   Your token:
echo   %AUTH_TOKEN%
echo.
echo   Dashboard with login:
echo   http://127.0.0.1:%PORT%/gui
echo.
:no_token

echo   Your secure Tailscale URL:
if not defined TS_URL echo   not configured - install Tailscale: https://tailscale.com
if defined TS_URL echo   https://%TS_URL%
echo.
if defined TS_URL (
    tailscale funnel status >"%TEMP%\arena_funnel_status.txt" 2>nul
    findstr /i /c:"Funnel on" /c:"proxy http" "%TEMP%\arena_funnel_status.txt" >nul 2>&1
    if errorlevel 1 (
        curl --max-time 8 -fsS "https://%TS_URL%/health" >nul 2>&1
        if errorlevel 1 (
            echo   [INFO] Tailscale Funnel does not appear to be enabled yet.
            echo          To publish the bridge: tailscale funnel --bg %PORT%
        ) else (
            echo   [OK] Tailscale Funnel public health endpoint is reachable.
        )
    ) else (
        echo   [OK] Tailscale Funnel appears active for this machine.
    )
    del "%TEMP%\arena_funnel_status.txt" >nul 2>&1
    echo.
)

echo   Background service/task:
echo     Name: ArenaUnifiedBridge
echo     This is expected. It keeps the bridge available after this window closes.
echo     To remove: uninstall.bat
echo.
echo   Manage:
if "%SERVICE_METHOD%"=="nssm" goto :manage_nssm
echo     schtasks /run /tn "ArenaUnifiedBridge"
echo     schtasks /end /tn "ArenaUnifiedBridge"
echo     schtasks /query /tn "ArenaUnifiedBridge" /fo LIST /v
echo     Or: start_bridge.bat
goto :manage_done
:manage_nssm
echo     nssm status ArenaUnifiedBridge
echo     nssm restart ArenaUnifiedBridge
echo     nssm stop ArenaUnifiedBridge
:manage_done

echo.
echo   Optional:
echo   tailscale funnel --bg %PORT%
echo.
echo   Installed skills:
if exist "!BRIDGE_DIR!\skills\superpowers\skills" echo   SuperPowers   - skills\superpowers\
where browser-act >nul 2>&1
if not errorlevel 1 echo   BrowserAct    - installed
echo.
echo   Update:
echo   cd to bridge dir, then run: git pull, then: install.bat
echo.

:end
echo.
if /I "%ARENA_ACCEPT_BACKGROUND%"=="1" exit /b
if /I "%ARENA_ASSUME_YES%"=="1" exit /b
pause
