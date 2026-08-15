#!/usr/bin/env bash
#
# Build and sign the Arena Bridge Android app.
#
#   bash scripts/build_android_apk.sh            # -> android_app/build/arena-bridge.apk
#
# Why no Gradle: Gradle would pull a wrapper, a daemon and a dependency
# tree to compile five source files that use nothing outside the Android
# framework. aapt2 + javac + d8 + apksigner is the whole toolchain, it is
# already in build-tools, and every step here is legible.
#
# Requirements (both are downloaded by hand once, not vendored):
#   JAVA_HOME     -> a JDK 17. The Android command-line tools are built
#                    for class file version 61; JDK 11 fails with
#                    UnsupportedClassVersionError before printing help.
#   ANDROID_HOME  -> an SDK with platforms;android-34 and
#                    build-tools;34.0.0.
#
# The fallback debug keystore is generated on first run and is NOT a release
# key. It exists so ordinary CI/local APKs can be installed at all. The release
# candidate workflow supplies a persistent keystore outside BUILD; shipped APKs
# must never use the disposable fallback identity.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$HERE/android_app"
BUILD="$APP/build"
SDK_VER="34"
BT_VER="34.0.0"

die() { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

[ -n "${ANDROID_HOME:-}" ] || die "ANDROID_HOME is not set"
[ -n "${JAVA_HOME:-}" ]    || die "JAVA_HOME is not set (needs a JDK 17)"

BT="$ANDROID_HOME/build-tools/$BT_VER"
PLATFORM="$ANDROID_HOME/platforms/android-$SDK_VER/android.jar"
[ -d "$BT" ]       || die "missing build-tools $BT_VER at $BT"
[ -f "$PLATFORM" ] || die "missing platform android-$SDK_VER at $PLATFORM"

export PATH="$JAVA_HOME/bin:$BT:$PATH"

# A JDK that is too old fails deep inside aapt2 with a class-version
# error that reads like a corrupt SDK. Check it here instead.
JAVA_MAJOR="$(java -version 2>&1 | head -1 | sed -E 's/.*"([0-9]+).*/\1/')"
[ "${JAVA_MAJOR:-0}" -ge 17 ] || die "JDK 17+ required, found $JAVA_MAJOR"

say "cleaning"
rm -rf "$BUILD"
mkdir -p "$BUILD/compiled" "$BUILD/classes"

say "compiling resources"
aapt2 compile --dir "$APP/res" -o "$BUILD/compiled/res.zip"

say "linking manifest + resources"
aapt2 link -o "$BUILD/base.apk" \
    -I "$PLATFORM" \
    --manifest "$APP/AndroidManifest.xml" \
    --java "$BUILD/gen" \
    --min-sdk-version 26 --target-sdk-version "$SDK_VER" \
    "$BUILD/compiled/res.zip"

say "compiling java"
# shellcheck disable=SC2046  # deliberate word splitting over the file list
javac -source 8 -target 8 -nowarn \
    -bootclasspath "$PLATFORM" -classpath "$PLATFORM" \
    -d "$BUILD/classes" \
    $(find "$APP/src" "$BUILD/gen" -name '*.java')

say "dexing"
# shellcheck disable=SC2046  # deliberate word splitting over the file list
d8 --release --min-api 26 --output "$BUILD" --lib "$PLATFORM" \
    $(find "$BUILD/classes" -name '*.class')

say "packaging"
cp "$BUILD/base.apk" "$BUILD/unsigned.apk"
( cd "$BUILD" && zip -q unsigned.apk classes.dex )

# CI smoke builds may use the generated disposable debug key below. Release
# candidates MUST provide a persistent keystore outside BUILD; cleaning BUILD
# at the top of this script would otherwise rotate Android's signing identity
# on every release and make in-place app upgrades impossible.
KS="${ARENA_ANDROID_KEYSTORE:-$BUILD/arena.jks}"
KEY_ALIAS="${ARENA_ANDROID_KEY_ALIAS:-arena}"
export ARENA_ANDROID_STORE_PASSWORD="${ARENA_ANDROID_STORE_PASSWORD:-arenabridge}"
export ARENA_ANDROID_KEY_PASSWORD="${ARENA_ANDROID_KEY_PASSWORD:-$ARENA_ANDROID_STORE_PASSWORD}"
if [ ! -f "$KS" ]; then
    if [ -n "${ARENA_ANDROID_KEYSTORE:-}" ]; then
        die "configured release keystore is missing: $KS"
    fi
    say "generating a local debug keystore (not a release key)"
    keytool -genkeypair -keystore "$KS" -alias "$KEY_ALIAS" \
        -storepass "$ARENA_ANDROID_STORE_PASSWORD" \
        -keypass "$ARENA_ANDROID_KEY_PASSWORD" \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -dname "CN=Arena Bridge, O=arena.ai" >/dev/null 2>&1
fi

say "aligning and signing"
zipalign -f 4 "$BUILD/unsigned.apk" "$BUILD/aligned.apk"
apksigner sign --ks "$KS" \
    --ks-pass env:ARENA_ANDROID_STORE_PASSWORD \
    --key-pass env:ARENA_ANDROID_KEY_PASSWORD \
    --ks-key-alias "$KEY_ALIAS" \
    --out "$BUILD/arena-bridge.apk" "$BUILD/aligned.apk"

# Verify rather than assume: an APK that fails signature verification
# installs nowhere, and finding that out on the phone wastes a round trip.
apksigner verify "$BUILD/arena-bridge.apk" || die "signature verification failed"

say "OK: $BUILD/arena-bridge.apk"
ls -la "$BUILD/arena-bridge.apk"
sha256sum "$BUILD/arena-bridge.apk"
