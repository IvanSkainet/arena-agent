#!/data/data/com.termux/files/usr/bin/bash
#
# Install Skainet Bridge on the phone itself, inside Termux.
#
# The bridge has exactly one hard dependency (aiohttp) and is pure
# Python, so "installing on Android" is far less exotic than it sounds:
# measured on a POCO F7 Pro (Android 16, SDK 36, arm64-v8a, 11 GB RAM),
# the bridge idles at ~57 MB RSS with 6 threads and starts in 0.42 s.
#
# What this script does NOT do, deliberately:
#   * bind to 0.0.0.0 by default. A phone joins untrusted Wi-Fi; a
#     bridge listening on every interface with an owner-shell profile is
#     a remote shell handed to the coffee shop. Default is loopback and
#     the script prints how to widen it over Tailscale.
#   * install a root-only anything. This targets an unrooted device.
#   * ask for a password. The token is generated locally and printed
#     once.
#
# Usage (inside Termux):
#     bash install_termux.sh              # install + print run command
#     bash install_termux.sh --start      # install and start now
set -euo pipefail

BRIDGE_DIR="${ARENA_BRIDGE_DIR:-$HOME/arena-bridge}"
START_NOW=0
for arg in "$@"; do
    case "$arg" in
        --start) START_NOW=1 ;;
        -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- checks
# Refuse early and clearly rather than failing three steps later with a
# confusing package-manager error.
[ -n "${PREFIX:-}" ] && [ -d "$PREFIX" ] \
    || die "PREFIX is not set. This script must run inside Termux."
case "$PREFIX" in
    *com.termux*) ;;
    *) die "PREFIX=$PREFIX does not look like Termux." ;;
esac
[ -n "${ANDROID_ROOT:-}" ] \
    || die "ANDROID_ROOT is unset -- this does not look like Android."

say "Termux detected: PREFIX=$PREFIX"

# ------------------------------------------------------------- packages
say "Installing packages (python, git)…"
pkg install -y python git >/dev/null 2>&1 \
    || die "pkg install failed. Run 'pkg update' first, then retry."

python_version="$(python3 -V 2>&1)"
say "Python: $python_version"

# aiohttp ships arm64 wheels; if pip still tries to build, it needs a
# compiler, so say so instead of leaving a wall of gcc errors.
say "Installing aiohttp (the bridge's only hard dependency)…"
if ! pip install --quiet --upgrade aiohttp; then
    say "Wheel unavailable -- installing build tools and retrying."
    pkg install -y clang libffi openssl >/dev/null 2>&1 || true
    pip install --quiet --upgrade aiohttp \
        || die "aiohttp install failed. See the pip output above."
fi

# psutil is optional: every import of it in the bridge is lazy and
# guarded, and the bridge degrades honestly without it. Try, shrug off.
say "Installing psutil (optional -- richer metrics)…"
if pip install --quiet psutil >/dev/null 2>&1; then
    say "psutil: installed"
else
    say "psutil: unavailable, continuing (metrics degrade, nothing breaks)"
fi

# ---------------------------------------------------------------- files
if [ ! -d "$BRIDGE_DIR" ]; then
    die "Bridge directory not found: $BRIDGE_DIR
Unpack the release zip there first, e.g.:
    mkdir -p $BRIDGE_DIR && cd $BRIDGE_DIR
    unzip ~/storage/downloads/arena-agent.zip --strip-components=1"
fi
[ -f "$BRIDGE_DIR/unified_bridge.py" ] \
    || die "$BRIDGE_DIR does not contain unified_bridge.py"

cd "$BRIDGE_DIR"

# ---------------------------------------------------------------- token
TOKEN_FILE="$BRIDGE_DIR/token.txt"
if [ -f "$TOKEN_FILE" ]; then
    say "Reusing existing token: $TOKEN_FILE"
else
    say "Generating a token…"
    python3 -c "import secrets; print('qaz_' + secrets.token_urlsafe(32))" > "$TOKEN_FILE"
    chmod 600 "$TOKEN_FILE"
fi

# ------------------------------------------------------------ self-test
# "Green != works": prove the thing imports on THIS device before
# claiming success, rather than trusting that the install steps passed.
say "Verifying the bridge imports on this device…"
python3 - <<'PY' || die "the bridge does not import here; see the traceback above"
import sys
sys.path.insert(0, ".")
import unified_bridge  # noqa: F401
from arena import hostplatform as hp
info = hp.describe()
assert info["class"] == "android", f"host misdetected as {info['class']!r}"
assert info["role"] == "on-device", f"role is {info['role']!r}, expected on-device"
print(f"    host class : {info['class']}")
print(f"    role       : {info['role']}")
print(f"    termux     : {info['termux']}")
print(f"    prefix     : {info['termux_prefix']}")
PY

say "Import check passed."

# ------------------------------------------------------------------ run
BASE_CMD="python3 unified_bridge.py serve --port 8765 --token-file $TOKEN_FILE --profile cautious"
RUN_CMD="$BASE_CMD --bind 127.0.0.1"

cat <<EOF

  Installed in: $BRIDGE_DIR
  Token file  : $TOKEN_FILE

  Start it:
      cd $BRIDGE_DIR
      $RUN_CMD

  Reach it from another machine WITHOUT exposing it to the local
  network -- install Tailscale on the phone, then:

      $BASE_CMD --bind \$(ifconfig tailscale0 2>/dev/null | awk '/inet /{print \$2}')

  Do NOT use --bind 0.0.0.0 on public Wi-Fi. A phone roams between
  untrusted networks, and an owner-shell bridge on every interface is
  a shell handed to whoever else is on that network.

  Keep it alive when the screen locks:
      termux-wake-lock

EOF

if [ "$START_NOW" -eq 1 ]; then
    say "Starting the bridge…"
    exec $RUN_CMD
fi
