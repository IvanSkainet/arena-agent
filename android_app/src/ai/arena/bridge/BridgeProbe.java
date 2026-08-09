package ai.arena.bridge;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URL;

/**
 * Answers "is the bridge serving?" by talking to it.
 *
 * <p>Deliberately not by asking a Service object, reading a pidfile, or
 * checking whether a process exists: v4.169.5 shipped a bridge that told
 * a halted agent it was running because the status came from the wrong
 * place. A socket that accepts and a body that parses are evidence.
 * Anything else is a claim.
 */
public final class BridgeProbe {

    private BridgeProbe() {
    }

    /** True when something accepts a TCP connection on the port. */
    public static boolean portOpen(int port, int timeoutMs) {
        Socket s = new Socket();
        try {
            s.connect(new InetSocketAddress("127.0.0.1", port), timeoutMs);
            return true;
        } catch (Exception e) {
            return false;
        } finally {
            try {
                s.close();
            } catch (Exception ignored) {
                // a failed socket that will not close is not news
            }
        }
    }

    /**
     * The reported version, or null.
     *
     * <p>{@code /v1/version} is the one public endpoint, so this works
     * without holding the bridge token -- the app never needs to read
     * Termux's {@code token.txt}, which it could not do anyway.
     */
    public static String version() {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(BridgePaths.versionUrl()).openConnection();
            conn.setConnectTimeout(1200);
            conn.setReadTimeout(1200);
            conn.setRequestMethod("GET");
            if (conn.getResponseCode() != 200) {
                return null;
            }
            try (InputStream in = conn.getInputStream()) {
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                byte[] buf = new byte[2048];
                int n;
                while ((n = in.read(buf)) > 0 && out.size() < 8192) {
                    out.write(buf, 0, n);
                }
                return extract(out.toString("UTF-8"), "version");
            }
        } catch (Exception e) {
            return null;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /**
     * Pull one string field out of a flat JSON object.
     *
     * <p>A hand-rolled reader rather than org.json so the parse cannot
     * throw on an unexpected shape: this runs on the status screen, and
     * a status screen that crashes is worse than one that says "unknown".
     */
    static String extract(String json, String key) {
        if (json == null) {
            return null;
        }
        String needle = "\"" + key + "\"";
        int at = json.indexOf(needle);
        if (at < 0) {
            return null;
        }
        int colon = json.indexOf(':', at + needle.length());
        if (colon < 0) {
            return null;
        }
        int open = json.indexOf('"', colon);
        if (open < 0) {
            return null;
        }
        int close = json.indexOf('"', open + 1);
        if (close < 0) {
            return null;
        }
        return json.substring(open + 1, close);
    }
}
