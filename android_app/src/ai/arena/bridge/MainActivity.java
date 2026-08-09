package ai.arena.bridge;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;


/**
 * One screen: is it running, and the two buttons that decide whether it
 * keeps running.
 *
 * <p>The battery-optimisation button is the point of the whole app. On
 * HyperOS a background process is reaped regardless of wake locks; the
 * exemption is the only switch that changes that, and only the user can
 * grant it. It is requested from a visible button with the reason next
 * to it, never silently on launch.
 *
 * <p>"Running" is reported by connecting to the port, not by asking the
 * service what it thinks. A service object that believes it is serving
 * is exactly the kind of evidence this project has learned not to trust.
 */
public class MainActivity extends Activity {

    private TextView status;
    private final Handler handler = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.parseColor("#0d1117"));
        root.setPadding(48, 64, 48, 48);

        TextView title = new TextView(this);
        title.setText("Arena Bridge");
        title.setTextColor(Color.parseColor("#58a6ff"));
        title.setTextSize(26);
        root.addView(title);

        status = new TextView(this);
        status.setTextColor(Color.parseColor("#c9d1d9"));
        status.setTextSize(15);
        status.setPadding(0, 32, 0, 32);
        root.addView(status);

        root.addView(button("Keep bridge alive", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent i = new Intent(MainActivity.this, BridgeService.class);
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    startForegroundService(i);
                } else {
                    startService(i);
                }
                refreshSoon();
            }
        }));

        root.addView(button("Release", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent i = new Intent(MainActivity.this, BridgeService.class);
                i.setAction(BridgeService.ACTION_STOP);
                startService(i);
                refreshSoon();
            }
        }));

        root.addView(button("Open Termux", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                Intent i = getPackageManager()
                        .getLaunchIntentForPackage(BridgePaths.TERMUX_PACKAGE);
                if (i != null) {
                    startActivity(i);
                }
            }
        }));

        root.addView(button("Allow running in background", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                requestBatteryExemption();
            }
        }));

        TextView why = new TextView(this);
        why.setText("Xiaomi's HyperOS stops background processes even when they hold "
                + "a wake lock. Without the battery exemption the bridge will die "
                + "minutes after the screen goes off.");
        why.setTextColor(Color.parseColor("#8b949e"));
        why.setTextSize(13);
        why.setPadding(0, 24, 0, 0);
        root.addView(why);

        ScrollView scroll = new ScrollView(this);
        scroll.addView(root);
        setContentView(scroll);
    }

    private Button button(String label, View.OnClickListener onClick) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setGravity(Gravity.CENTER);
        b.setOnClickListener(onClick);
        return b;
    }

    private void requestBatteryExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return;
        }
        if (isExempt()) {
            // Already granted: send the user to the settings page rather
            // than firing an intent that would be a no-op.
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
            return;
        }
        Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS);
        i.setData(Uri.parse("package:" + getPackageName()));
        try {
            startActivity(i);
        } catch (Exception e) {
            startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
        }
    }

    private boolean isExempt() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true;
        }
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
    }

    private void refreshSoon() {
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                refresh();
            }
        }, 1500);
    }

    private void refresh() {
        // Termux presence is asked of the package manager, not the
        // filesystem: this app is forbidden from stat-ing another app's
        // data directory, so a File check answers "no" on a phone where
        // Termux is installed and running.
        final boolean termux = termuxInstalled();
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String version = BridgeProbe.version();
                final boolean up = version != null
                        || BridgeProbe.portOpen(BridgePaths.PORT, 700);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        StringBuilder sb = new StringBuilder();
                        sb.append(up ? "Serving on 127.0.0.1:" + BridgePaths.PORT
                                     : "Not serving");
                        if (version != null) {
                            sb.append("\nBridge version: ").append(version);
                        }
                        sb.append("\n\nTermux installed: ").append(termux ? "yes" : "no");
                        sb.append("\nBattery exemption: ")
                          .append(isExempt() ? "granted" : "NOT granted");
                        if (!termux) {
                            sb.append("\n\nTermux supplies the python runtime. Install "
                                    + "Termux, then run the bootstrap script inside it.");
                        } else if (!up) {
                            sb.append("\n\nTermux is installed but nothing is answering "
                                    + "on the port. Open Termux and start the bridge; "
                                    + "this app cannot launch it, because Android does "
                                    + "not let one app run another app's binaries.");
                        }
                        status.setText(sb.toString());
                    }
                });
            }
        }, "status-probe").start();
    }

    private boolean termuxInstalled() {
        try {
            getPackageManager().getPackageInfo(BridgePaths.TERMUX_PACKAGE, 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }
}
