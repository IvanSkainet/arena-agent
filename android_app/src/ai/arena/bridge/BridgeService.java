package ai.arena.bridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

/**
 * Holds foreground status and a wake lock on behalf of the bridge, so
 * Android -- and HyperOS in particular -- stops treating it as a
 * background process to reap.
 *
 * <p>What the Termux setup could not do, and this can:
 *
 * <ul>
 *   <li>a persistent notification, which is the contract that tells the
 *       platform "the user knows this is running";
 *   <li>a partial wake lock owned by a service rather than a shell;
 *   <li>a battery-optimisation exemption the user grants from a button.
 * </ul>
 *
 * <p>It does <em>not</em> spawn the python process. The first design did,
 * via ProcessBuilder on Termux's interpreter, and that is impossible:
 * Android's per-app sandbox means this UID cannot execute -- or even
 * stat -- anything under /data/data/com.termux. Verified on the device;
 * every existence check answered "no" while Termux was plainly
 * installed, and the UI dutifully reported "Termux installed: no".
 *
 * <p>The Google Play build of Termux on the device also ships without
 * RUN_COMMAND, so the documented IPC route is unavailable too.
 *
 * <p>What survives the sandbox is a loopback socket, confirmed from a
 * different UID. So the division of labour is: Termux runs python, this
 * service supplies the two things Termux cannot give it -- foreground
 * status and a wake lock the platform respects -- and reports what the
 * port actually says rather than what it hopes.
 */
public class BridgeService extends Service {

    public static final String CHANNEL_ID = "arena_bridge";
    public static final String ACTION_STOP = "ai.arena.bridge.STOP";
    private static final int NOTIFICATION_ID = 1;

    private volatile boolean watching;
    private PowerManager.WakeLock wakeLock;
    private volatile String state = "starting";

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopBridge();
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }

        createChannel();
        startForeground(NOTIFICATION_ID, buildNotification("starting the bridge\u2026"));

        acquireWakeLock();
        startWatch();
        return START_STICKY;
    }

    /**
     * Poll the port and keep the notification honest.
     *
     * <p>The notification is the only thing the user sees when the phone
     * is in their pocket, so it must never claim "serving" on the
     * strength of having been started once.
     */
    private void startWatch() {
        if (watching) {
            return;
        }
        watching = true;
        new Thread(new Runnable() {
            @Override
            public void run() {
                String last = null;
                while (watching) {
                    String version = BridgeProbe.version();
                    boolean up = version != null
                            || BridgeProbe.portOpen(BridgePaths.PORT, 700);
                    state = up ? "running" : "down";
                    String text = up
                            ? ("serving on 127.0.0.1:" + BridgePaths.PORT
                               + (version != null ? "  (v" + version + ")" : ""))
                            : "bridge is not answering on port " + BridgePaths.PORT;
                    if (!text.equals(last)) {
                        notifyState(text);
                        last = text;
                    }
                    try {
                        Thread.sleep(15000);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                }
            }
        }, "bridge-watch").start();
    }

    private void acquireWakeLock() {
        PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (pm == null) {
            return;
        }
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "arena:bridge");
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire();
    }

    private void stopBridge() {
        watching = false;
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        wakeLock = null;
        state = "stopped";
    }

    @Override
    public void onDestroy() {
        stopBridge();
        super.onDestroy();
    }

    private void createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Arena Bridge", NotificationManager.IMPORTANCE_LOW);
        channel.setDescription("Shows that the local bridge is serving.");
        channel.setShowBadge(false);
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification(String text) {
        Intent open = new Intent(this, MainActivity.class);
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent tap = PendingIntent.getActivity(this, 0, open, flags);

        Notification.Builder b = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        return b.setContentTitle("Arena Bridge")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.stat_sys_download_done)
                .setContentIntent(tap)
                .setOngoing(true)
                .build();
    }

    private void notifyState(String text) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.notify(NOTIFICATION_ID, buildNotification(text));
        }
    }
}
