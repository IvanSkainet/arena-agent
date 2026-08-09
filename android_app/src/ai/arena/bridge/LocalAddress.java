package ai.arena.bridge;

import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.Collections;

/**
 * The address another machine would use to reach this phone.
 *
 * <p>Enumerated from the interfaces directly. Asking the bridge would be
 * simpler, but /v1/access needs the token and this app cannot hold one;
 * the interface list is public information the app already has by virtue
 * of running on the device.
 *
 * <p>A tailnet address wins over a LAN one when both exist: the LAN
 * address stops working the moment the phone leaves the house, and
 * printing the one that will break first is worse than useless.
 */
public final class LocalAddress {

    private LocalAddress() {
    }

    public static String best() {
        String lan = null;
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) {
                    continue;
                }
                for (InetAddress addr : Collections.list(nif.getInetAddresses())) {
                    if (addr.isLoopbackAddress() || addr.getHostAddress() == null) {
                        continue;
                    }
                    String ip = addr.getHostAddress();
                    if (ip.indexOf(':') >= 0) {
                        continue;  // IPv6: not what a user types into a browser
                    }
                    if (isTailnet(ip)) {
                        return ip;
                    }
                    if (lan == null) {
                        lan = ip;
                    }
                }
            }
        } catch (Exception e) {
            return lan;
        }
        return lan;
    }

    /** 100.64.0.0/10 -- the CGNAT range Tailscale allocates from. */
    static boolean isTailnet(String ip) {
        String[] parts = ip.split("\\.");
        if (parts.length != 4) {
            return false;
        }
        try {
            int a = Integer.parseInt(parts[0]);
            int b = Integer.parseInt(parts[1]);
            return a == 100 && b >= 64 && b <= 127;
        } catch (NumberFormatException e) {
            return false;
        }
    }
}
