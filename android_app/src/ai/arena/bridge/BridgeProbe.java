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
        String body = fetch(BridgePaths.versionUrl());
        return body == null ? null : extract(body, "version");
    }

    /**
     * Everything /v1/version says, read in a single request.
     *
     * <p>The status screen needs three fields. Asking three times means
     * three round trips and, worse, three different instants: the bind
     * and the tunnel state could come from either side of a tunnel going
     * down, and the screen would show a combination that was never true.
     */
    public static Status status() {
        return Status.of(fetch(BridgePaths.versionUrl()));
    }

    /** One reading of /v1/version. Any field may be null: unknown. */
    public static final class Status {
        public final String version;
        public final Boolean loopbackOnly;
        public final Boolean exposedPublicly;

        Status(String version, Boolean loopbackOnly, Boolean exposedPublicly) {
            this.version = version;
            this.loopbackOnly = loopbackOnly;
            this.exposedPublicly = exposedPublicly;
        }

        static Status of(String body) {
            if (body == null) {
                return new Status(null, null, null);
            }
            return new Status(
                    extract(body, "version"),
                    tristate(body, "loopback_only"),
                    tristate(body, "exposed_publicly"));
        }
    }

    /**
     * A JSON boolean as true/false/null.
     *
     * <p>Null for a missing field, and null for a literal JSON null:
     * a bridge that says "I have not checked" must not be read as "no".
     */
    static Boolean tristate(String json, String key) {
        String value = extractRaw(json, key);
        if (value == null || "null".equals(value)) {
            return null;
        }
        if ("true".equals(value)) {
            return Boolean.TRUE;
        }
        if ("false".equals(value)) {
            return Boolean.FALSE;
        }
        return null;
    }

    /** GET a URL, returning the body or null. Never throws. */
    static String fetch(String url) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(url).openConnection();
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
                return out.toString("UTF-8");
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
     * True when the bridge is bound to loopback and therefore reachable
     * by nothing outside the phone.
     *
     * <p>Published on the unauthenticated /v1/version because this app
     * cannot hold the bridge token: it lives inside Termux's private
     * tree, which the sandbox forbids reading. Returns null when the
     * bridge is too old to report it -- not false, because "I could not
     * tell" and "it is open" are different answers and conflating them
     * is how a status screen starts lying.
     */
    public static Boolean loopbackOnly() {
        String body = fetch(BridgePaths.versionUrl());
        if (body == null) {
            return null;
        }
        return tristate(body, "loopback_only");
    }

    /**
     * Whether the bridge is currently reachable from the public internet
     * through a tunnel, or null when the bridge cannot say.
     *
     * <p>Separate from {@link #loopbackOnly()} on purpose. A bridge bound
     * to 127.0.0.1 with a live Funnel is loopback-bound *and* exposed to
     * the internet; reporting only the bind told the operator "no direct
     * access" while the world could reach the thing. Null means the
     * bridge is older than this field, or has not observed a tunnel
     * recently enough to answer -- neither of which is a "no".
     */
    public static Boolean exposedPublicly() {
        String body = fetch(BridgePaths.versionUrl());
        if (body == null) {
            return null;
        }
        return tristate(body, "exposed_publicly");
    }

    /** Read a bare (unquoted) JSON value: true, false, a number. */
    static String extractRaw(String json, String key) {
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
        int i = colon + 1;
        while (i < json.length() && Character.isWhitespace(json.charAt(i))) {
            i++;
        }
        int start = i;
        while (i < json.length() && "truefalsenul0123456789.-".indexOf(json.charAt(i)) >= 0) {
            i++;
        }
        return i > start ? json.substring(start, i) : null;
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
