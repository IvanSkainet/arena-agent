$ErrorActionPreference = "Continue"
Set-Location "$env:USERPROFILE\arena-local-bridge"

# Read token from file — auto-generate if missing
$tokenFile = "$env:USERPROFILE\arena-local-bridge\token.txt"
$token = $null

if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -First 1 -ErrorAction SilentlyContinue).Trim()
}

if (-not $token -or $token.Length -lt 16) {
    # Auto-generate token if missing or too short
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
    if ($token) {
        Set-Content -Path $tokenFile -Value $token -Encoding UTF8
    }
}

# Find Python
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
