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

# ---------------------------------------------------------------- files
# Checked BEFORE installing anything: the pinned requirements file
# lives inside the release, so a missing or partial unpack must fail
# here rather than after pip has already changed the environment.
if [ ! -d "$BRIDGE_DIR" ]; then
    die "Bridge directory not found: $BRIDGE_DIR
Unpack the release zip there first, e.g.:
    mkdir -p $BRIDGE_DIR && cd $BRIDGE_DIR
    unzip ~/storage/downloads/arena-agent.zip --strip-components=1"
fi
[ -f "$BRIDGE_DIR/unified_bridge.py" ] \
    || die "$BRIDGE_DIR does not contain unified_bridge.py"

cd "$BRIDGE_DIR"

# ------------------------------------------------------------- packages
say "Installing packages (python, git)…"
pkg install -y python git >/dev/null 2>&1 \
    || die "pkg install failed. Run 'pkg update' first, then retry."

python_version="$(python3 -V 2>&1)"
say "Python: $python_version"

# Dependencies are installed from a hash-pinned requirements file, not
# by name. Scorecard raised three Pinned-Dependencies alerts (#317,
# #318, #319) against the bare `pip install` calls that used to live
# here, and they were right: this artifact lands on a phone and is
# imported by a bridge that holds shell access on a device roaming
# between untrusted networks. A typosquat or a compromised release
# would arrive with execution rights.
#
# `--require-hashes` makes pip refuse anything whose digest is not in
# the file, transitive dependencies included.
REQUIREMENTS="$BRIDGE_DIR/scripts/requirements-termux.txt"
[ -f "$REQUIREMENTS" ] \
    || die "missing $REQUIREMENTS -- unpack the full release, not just the bridge"

say "Installing pinned dependencies (hash-verified)…"
if ! pip install --quiet --require-hashes -r "$REQUIREMENTS"; then
    say "Wheels unavailable -- installing build tools and retrying."
    # These come from Termux's own signed package repository, which is
    # the trust root for the whole userland; pinning them here would
    # duplicate pkg's job and rot on every Termux release.
    pkg install -y clang libffi openssl >/dev/null 2>&1 || true
    pip install --quiet --require-hashes -r "$REQUIREMENTS" \
        || die "dependency install failed. If pip reported a HASH MISMATCH,
do NOT work around it -- that is the check doing its job. Refresh the
pins on a trusted machine with:
    python scripts/refresh_termux_requirements.py"
fi
say "Dependencies installed and hash-verified."

# Optional extras go in a SEPARATE pip run, on purpose.
#
# v4.167.6: psutil was in the main requirements file, and `pip install
# -r` is all-or-nothing -- so psutil failing took aiohttp down with it
# and aborted the whole install. Measured on a POCO F7 Pro during the
# first real on-device run:
#
#     platform android is not supported
#     ERROR: Failed to build 'psutil' when getting requirements to build
#     wheel
#
# psutil's build backend refuses Android outright. There is no wheel and
# the sdist cannot compile, so this is permanent, not a packaging blip.
# Every psutil import in the bridge is lazy and guarded; "optional" has
# to mean the install survives without it, and it did not.
OPTIONAL="$BRIDGE_DIR/scripts/requirements-termux-optional.txt"
if [ -f "$OPTIONAL" ] \
   && pip install --quiet --require-hashes -r "$OPTIONAL" >/dev/null 2>&1; then
    say "psutil: installed (richer metrics)"
else
    say "psutil: unavailable on Android, continuing (metrics degrade, nothing breaks)"
fi

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
