// Hand the browser extension over from the bridge itself.
//
// The operator: "I can't install the extension yet, the needed files
// aren't there. Installing through Termux is really inconvenient."
//
// Both halves were real. The files were missing because auto-update
// copies a hand-maintained list of directories and nobody added
// chat_extension_firefox -- or chat_extension, which means the
// extension had never been auto-updated at all. And even present, on a
// phone they live inside Termux's private tree where no browser can
// reach them.
//
// So: a button. No file manager, no shell, no knowing where the install
// root is.

async function extensionRefresh() {
  const badge = document.getElementById("extBadge");
  const hint = document.getElementById("extHint");
  if (!badge) return;
  try {
    const r = await api("/v1/extension/status");
    const chromium = (r.chromium && r.chromium.files) || 0;
    const firefox = (r.firefox && r.firefox.files) || 0;
    if (chromium > 0) {
      badge.className = "badge ok";
      badge.textContent = chromium + " files";
    } else {
      badge.className = "badge warn";
      badge.textContent = "not installed";
    }
    if (hint) {
      hint.textContent = firefox > 0
        ? "Chromium and Firefox builds are both available on this machine."
        : "Firefox build is not on disk; the download will generate a "
          + "Firefox-compatible manifest on the fly.";
    }
  } catch (e) {
    badge.className = "badge gray";
    badge.textContent = "unavailable";
  }
}

function extensionDownload(kind) {
  const steps = document.getElementById("extSteps");
  const firefox = kind === "firefox";
  // Build the query properly rather than string-splicing: the first
  // draft produced ".../download&token=..." when no browser param was
  // present, which is a 401 dressed up as a broken download.
  const params = new URLSearchParams();
  if (firefox) params.set("browser", "firefox");
  // The bridge accepts ?token= (deprecated but supported) precisely for
  // cases like this, where a plain navigation must carry auth. fetch +
  // blob would let us use a header, but blob downloads land somewhere
  // unfindable in Firefox for Android -- the platform this exists for.
  params.set("token", window.ARENA_TOKEN || "");
  window.location.href = "/v1/extension/download?" + params.toString();

  if (steps) {
    steps.textContent = firefox
      ? "Firefox (desktop):\n"
        + "  1. Unzip the file\n"
        + "  2. Open about:debugging#/runtime/this-firefox\n"
        + "  3. Load Temporary Add-on -> pick manifest.json\n\n"
        + "Firefox for Android cannot side-load extensions from a file.\n"
        + "On the phone, use this Dashboard instead - it needs no extension."
      : "Chrome / Edge:\n"
        + "  1. Unzip the file\n"
        + "  2. Open chrome://extensions\n"
        + "  3. Turn on Developer mode\n"
        + "  4. Load unpacked -> pick the unzipped folder";
  }
}

if (window.arenaWhenReady) {
  window.arenaWhenReady(extensionRefresh);
} else {
  document.addEventListener("DOMContentLoaded", extensionRefresh);
}
