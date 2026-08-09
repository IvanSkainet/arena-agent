package ai.arena.bridge;

/**
 * What this app can and cannot reach on Android.
 *
 * <p>The first version of this class handed out {@code File} objects
 * under {@code /data/data/com.termux/files} and asked whether they
 * existed. On the device every one of those answered "no" -- not because
 * Termux was missing (it is installed) but because Android's per-app
 * sandbox forbids one app from stat-ing another app's data directory.
 * The UI cheerfully reported "Termux installed: no" on a phone running
 * Termux, which is the same defect this project keeps writing gates
 * against: a check that cannot tell absence from "I am not allowed to
 * look" and reports the first.
 *
 * <p>Worse, the launch design that rested on it -- {@code ProcessBuilder}
 * invoking {@code /data/data/com.termux/files/usr/bin/python3} -- cannot
 * work at all. That binary is not executable by this UID.
 *
 * <p>The device also runs the Google Play build of Termux
 * ({@code versionName=googleplay.2026.06.21}), which ships without
 * {@code RUN_COMMAND}, so the documented IPC route is absent too.
 *
 * <p>What does cross the boundary is a TCP connection to loopback:
 * verified from a different UID on the device, {@code GET /v1/version}
 * on 127.0.0.1:8765 answered 200. So the app supervises the bridge over
 * its own HTTP API instead of pretending to own the process.
 */
public final class BridgePaths {

    public static final int PORT = 8765;

    /** Termux package id, for the launch intent. */
    public static final String TERMUX_PACKAGE = "com.termux";

    private BridgePaths() {
    }

    public static String versionUrl() {
        return "http://127.0.0.1:" + PORT + "/v1/version";
    }
}
