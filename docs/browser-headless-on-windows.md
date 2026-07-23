# Browser automation on Windows: known issues & workarounds

**Status (v4.60.20):** Documented limitation. The bridge's CDP path
(`/v1/browser/browse`, `mobile/...`-adjacent browser tools) is
**partially functional** on Windows in some configurations. This
document explains why and what to do about it.

## TL;DR

If `/v1/browser/browse` returns `ok: false, error: "Browser exited
cleanly (rc=0) but produced no output..."` or `error: "...Edge is
running elevated..."`, the cause is **Chromium's security policy**,
not a bug in the bridge. Three workarounds are listed below.

## What's actually happening

When the bridge starts a browser (Edge or Chrome) in headless mode
and the bridge is running with administrator privileges
(`schtasks /query /tn "ArenaUnifiedBridge"` shows "Run As User"
`SYSTEM` or the install was done as admin), Chromium emits this
warning on stderr and then exits cleanly without doing anything:

```
[14152:18352:0723/182504.999:WARNING:chrome\browser\chrome_browser_main_win.cc:1655]
Edge is running elevated: 1
```

`rc=0`, `stdout` empty, `stderr` contains the warning. The browser
then terminates. This is **by design** — Chromium refuses to run
headless from an elevated process because headless mode is treated as
high-risk (it can render pages with no visible warning to the user).

Reproducible from any elevated shell on Windows:

```cmd
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
  --headless=new --no-sandbox --disable-gpu --dump-dom https://example.com
echo %errorlevel%
```

Returns 0 with no output.

## Workarounds (in order of practicality)

### 1. BrowserAct (cloud browser, easiest)

`browser-act` is already an optional dependency installed by
`install.bat`. It runs the browser on the BrowserAct cloud, so
elevation is not a problem. To use it instead of local Edge:

- Set the environment variable `ARENA_BROWSER_BACKEND=browseract` for
  the bridge process.
- Restart the bridge service.

This is the **recommended** path for users who need browser
automation and don't want to fight Windows elevation policy. It
requires a BrowserAct account.

### 2. Camoufox (Firefox-based, local, no elevation block)

Camoufox is a Firefox-based browser that does **not** enforce the
elevation block. `install.bat` already offers to install it (it's
bundled with the optional BrowserAct install). To switch the
bridge to Camoufox:

- Run `python -m camoufox fetch` once (this downloads the ~300 MB
  browser binary into the system cache).
- Set the environment variable `ARENA_BROWSER_BACKEND=camoufox`.

The bridge's `process_discovery.py` already lists `camoufox` as a
candidate browser (see `find_browser_exe` in v4.60.18). It just
needs the fetch step to be run once.

This path is **fully local** and doesn't need any account. It costs
~300 MB of disk space.

### 3. Run the bridge as a non-admin user

The most principled fix: change the bridge's Scheduled Task to
run as a regular (non-admin) user. Steps:

1. Open **Task Scheduler** (`taskschd.msc`).
2. Find the task `ArenaUnifiedBridge`.
3. Open it, go to **General** → **Security options** → **Change User
   or Group**.
4. Pick a regular user (not `SYSTEM`, not Administrators).
5. Re-run `install.bat` to refresh the task.

After this, the bridge runs without elevation, and Edge headless
will start working again. **Caveat:** the bridge needs to read/write
files in your user profile (`%USERPROFILE%\.arena` etc.). Make sure
the new user has access.

## Diagnostic helper (v4.60.20+)

As of v4.60.20, the bridge ships `arena/browser/diagnose_elevation.py`
which extracts the "running elevated" warning from stderr and
surfaces it as a structured `isError` with a clear next step. If you
see the error in `/v1/browser/browse`, it will say something like:

```json
{
  "isError": true,
  "content": [{
    "type": "text",
    "text": "Edge is running elevated: 1. Headless mode from an admin process is blocked by Chromium's security policy. Workarounds: (1) run the bridge as a non-admin service; (2) use BrowserAct's cloud browser; (3) install Camoufox (Firefox-based, no elevation block) ..."
  }]
}
```

This means the diagnostic is working. Apply workaround 1, 2, or 3
above.

## What we have NOT done (intentionally)

- **A flag that bypasses Chromium's elevation check.** No such flag
  exists in upstream Chromium. Any patch we made would be cosmetic
  and would not actually let the browser run.
- **Switching to a custom CDP server.** A custom CDP server is a
  multi-week project and outside the scope of v4.60.20.
- **A non-elevated worker process.** A future refactor could split
  the bridge into an admin coordinator and a non-elevated browser
  worker. This would let the bridge run as admin (for system
  automation) while the browser runs as a regular user. Not in
  v4.60.20; tracked for v4.61.x.

## Reporting an issue

If `/v1/browser/browse` fails with a different error than the three
workarounds above describe, please open an issue and include the
full stderr from the launch attempt. The diagnostic helper prints
the first 200 chars of stdout and stderr in the error envelope, so
this is usually enough to diagnose.

If you have a workaround that works for you and isn't listed here,
contributions to this document are welcome.
