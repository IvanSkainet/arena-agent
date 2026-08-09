#!/data/data/com.termux/files/usr/bin/bash
#
# One command. Everything.
#
#   curl -fsSL https://raw.githubusercontent.com/IvanSkainet/arena-agent/master/scripts/bootstrap_android.sh | bash
#
# Why this exists
# ---------------
#
# The previous instructions were: install unzip, make a directory, find
# the zip you downloaded in a browser, unzip it with the right
# --strip-components, then run a second script. The operator's verdict
# was blunt and correct: *"not everyone will climb into Termux to get
# who-knows-what."* Seven manual steps is not an install, it is a
# developer workflow.
#
# This does the whole thing: packages, download, verify, unpack,
# dependencies, self-test, autostart, and it leaves the bridge running
# with its URL and token on screen.
#
# What it deliberately keeps
# --------------------------
#
#   * SHA-256 verification of the release archive against the digest
#     GitHub reports. An install that skips this is a remote-code
#     execution channel with extra steps.
#   * Hash-pinned dependencies (--require-hashes), optional extras in a
#     separate pip run so psutil -- which cannot build on Android at all
#     -- can fail without taking the install with it.
#   * Loopback bind by default. A phone roams between untrusted
#     networks. The access profile starts `cautious` and there is now a
#     button in the Dashboard to widen it.
#
set -euo pipefail

REPO="IvanSkainet/arena-agent"
BRIDGE_DIR="${ARENA_BRIDGE_DIR:-$HOME/arena-bridge}"
PORT="${ARENA_PORT:-8765}"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- checks
[ -n "${PREFIX:-}" ] && [ -d "$PREFIX" ] \
    || die "PREFIX is not set. Run this inside Termux."
case "$PREFIX" in
    *com.termux*) ;;
    *) die "PREFIX=$PREFIX does not look like Termux." ;;
esac
[ -n "${ANDROID_ROOT:-}" ] || die "ANDROID_ROOT unset -- this is not Android."

say "Termux detected."

# ------------------------------------------------------------- packages
say "Installing python…"
pkg install -y python >/dev/null 2>&1 \
    || die "pkg install failed. Run 'pkg update' first, then retry."

# --------------------------------------------------------------- fetch
# Python rather than curl+unzip: it is already required, it gives real
# error messages, and it removes two package dependencies from the
# critical path.
mkdir -p "$BRIDGE_DIR"
say "Downloading the latest release…"
python3 - "$REPO" "$BRIDGE_DIR" <<'PY' || die "download or verification failed"
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

repo, target = sys.argv[1], Path(sys.argv[2])


def fetch(url, accept="application/vnd.github+json"):
    request = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": "arena-bootstrap",
    })
    return urllib.request.urlopen(request, timeout=300)


release = json.load(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
tag = release["tag_name"]
asset = next((a for a in release["assets"]
              if a["name"] == f"arena-agent-{tag}.zip"), None)
if asset is None:
    asset = next((a for a in release["assets"]
                  if a["name"].endswith(".zip")), None)
if asset is None:
    print("no zip asset in the latest release", file=sys.stderr)
    raise SystemExit(1)

print(f"    release  : {tag}")
print(f"    asset    : {asset['name']} ({asset['size']} bytes)")

blob = fetch(asset["browser_download_url"], accept="application/octet-stream").read()
digest = hashlib.sha256(blob).hexdigest()
print(f"    sha256   : {digest}")

# GitHub reports the digest it stored. Comparing against it turns a
# silent corrupt/substituted download into a hard stop.
declared = (asset.get("digest") or "").replace("sha256:", "")
if declared and declared != digest:
    print(f"DIGEST MISMATCH: GitHub says {declared}", file=sys.stderr)
    raise SystemExit(1)
if declared:
    print("    verified : matches the digest GitHub reports")
else:
    print("    verified : GitHub reported no digest for this asset")

if len(blob) != asset["size"]:
    print(f"SIZE MISMATCH: got {len(blob)}, expected {asset['size']}",
          file=sys.stderr)
    raise SystemExit(1)

# Unpack, stripping the leading arena-bridge/ component. Refuse any
# member that would escape the target directory -- a zip is untrusted
# input even when it came from our own release.
target.mkdir(parents=True, exist_ok=True)
resolved_target = target.resolve()
with zipfile.ZipFile(io.BytesIO(blob)) as archive:
    for member in archive.infolist():
        name = member.filename
        parts = name.split("/", 1)
        if len(parts) != 2 or not parts[1]:
            continue
        destination = (target / parts[1]).resolve()
        if not str(destination).startswith(str(resolved_target)):
            print(f"refusing path traversal in archive: {name}", file=sys.stderr)
            raise SystemExit(1)
        if member.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(member))

print(f"    unpacked : {target}")
PY

cd "$BRIDGE_DIR"
[ -f unified_bridge.py ] || die "release did not contain unified_bridge.py"

# -------------------------------------------------------- dependencies
REQUIREMENTS="$BRIDGE_DIR/scripts/requirements-termux.txt"
[ -f "$REQUIREMENTS" ] || die "release is missing $REQUIREMENTS"

say "Installing pinned dependencies (hash-verified)…"
if ! pip install --quiet --require-hashes -r "$REQUIREMENTS"; then
    say "Wheels unavailable -- installing build tools and retrying."
    pkg install -y clang libffi openssl >/dev/null 2>&1 || true
    pip install --quiet --require-hashes -r "$REQUIREMENTS" \
        || die "dependency install failed. If pip reported a HASH MISMATCH,
do NOT work around it -- that is the check doing its job."
fi

OPTIONAL="$BRIDGE_DIR/scripts/requirements-termux-optional.txt"
if [ -f "$OPTIONAL" ] \
   && pip install --quiet --require-hashes -r "$OPTIONAL" >/dev/null 2>&1; then
    say "psutil: installed (richer metrics)"
else
    say "psutil: unavailable on Android, continuing (metrics degrade)"
fi

# --------------------------------------------------------------- token
TOKEN_FILE="$BRIDGE_DIR/token.txt"
if [ ! -f "$TOKEN_FILE" ]; then
    python3 -c "import secrets; print('qaz_' + secrets.token_urlsafe(32))" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
fi
TOKEN="$(cat "$TOKEN_FILE")"

# ------------------------------------------------------------ self-test
# "Green != works": prove it imports on THIS device before claiming
# success, rather than trusting that the steps above passed.
say "Verifying the bridge imports on this device…"
python3 - <<'PY' || die "the bridge does not import here; see the traceback above"
import sys
sys.path.insert(0, ".")
import unified_bridge  # noqa: F401
from arena import hostplatform as hp
info = hp.describe()
assert info["class"] == "android", f"host misdetected as {info['class']!r}"
assert info["role"] == "on-device", f"role is {info['role']!r}"
print(f"    host  : {info['class']} / {info['role']}")
PY

# ----------------------------------------------------------- autostart
# termux-boot runs anything in ~/.termux/boot on device boot, if the
# Termux:Boot app is installed. Write the hook either way: installing
# the app later then Just Works, and an unused script costs nothing.
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/arena-bridge.sh" <<BOOTEOF
#!/data/data/com.termux/files/usr/bin/sh
# Auto-start the Arena bridge at boot.
#
# Refuse to start a second copy. v4.169.18: after an in-place update the
# old process was still holding the port, this script exec'd anyway, and
# aiohttp died with "[errno 98] address already in use" -- into a log
# nobody reads, leaving a phone that looked started and served nothing.
# Exiting 0 on "already running" is correct: the bridge IS up.
if python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', $PORT))==0 else 1)" 2>/dev/null; then
    echo "arena-bridge: port $PORT is already serving; not starting a second copy"
    exit 0
fi
termux-wake-lock
cd "$BRIDGE_DIR" || exit 1
exec python3 unified_bridge.py serve --port $PORT \\
    --token-file "$TOKEN_FILE" --profile cautious --bind 127.0.0.1
BOOTEOF
chmod +x "$BOOT_DIR/arena-bridge.sh"

if pm path ai.arena.bridge >/dev/null 2>&1; then
    say "Autostart: enabled (the Arena Bridge app is installed)."
elif [ -d /data/data/com.termux.boot ] || pm path com.termux.boot >/dev/null 2>&1; then
    say "Autostart: enabled (Termux:Boot found)."
else
    warn "Autostart hook written, but nothing will run it at boot."
    warn "Install arena-bridge.apk from the release page -- it carries its"
    warn "own boot receiver and the battery exemption HyperOS needs."
fi

# ---------------------------------------------------------------- run
termux-wake-lock >/dev/null 2>&1 || true
say "Starting the bridge…"
nohup python3 unified_bridge.py serve --port "$PORT" \
    --token-file "$TOKEN_FILE" --profile cautious --bind 127.0.0.1 \
    > "$BRIDGE_DIR/bridge.log" 2>&1 &

# Wait for it to actually answer rather than printing "started" and
# hoping. Reporting success for a process that died two seconds later is
# the failure this whole project keeps guarding against.
for _ in $(seq 1 30); do
    sleep 1
    if python3 - "$PORT" "$TOKEN" <<'PY' >/dev/null 2>&1
import json, sys, urllib.request
port, token = sys.argv[1], sys.argv[2]
request = urllib.request.Request(
    f"http://127.0.0.1:{port}/v1/version",
    headers={"Authorization": f"Bearer {token}"})
json.load(urllib.request.urlopen(request, timeout=5))
PY
    then
        cat <<EOF

  ────────────────────────────────────────────────────────────
   Arena Bridge is running on this phone.

   Dashboard:  http://127.0.0.1:$PORT/gui?token=$TOKEN
   Token:      $TOKEN

   Open that link in your browser -- the full Dashboard works
   there, the same one the desktop has.

   Access profile starts restricted. To allow any command,
   use the "Enable full shell" button in Settings.

   Stop it:    pkill -f unified_bridge
   Logs:       tail -f $BRIDGE_DIR/bridge.log
  ────────────────────────────────────────────────────────────

EOF
        exit 0
    fi
done

die "the bridge did not answer within 30s. Last log lines:
$(tail -n 15 "$BRIDGE_DIR/bridge.log" 2>/dev/null)"
