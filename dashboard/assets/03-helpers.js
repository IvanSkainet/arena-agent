// ===== HELPERS =====
function esc(s) { const d = document.createElement("div"); d.textContent = String(s); return d.innerHTML; }
function relTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + "s ago";
    if (diff < 3600) return Math.floor(diff/60) + "m ago";
    if (diff < 86400) return Math.floor(diff/3600) + "h ago";
    return Math.floor(diff/86400) + "d ago";
  } catch(e) { return ts; }
}
function formatUptime(seconds) {
  if (!seconds && seconds !== 0) return "--";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return d + "d " + h + "h";
  if (h > 0) return h + "h " + m + "m";
  return m + "m";
}
function formatBytes(b) {
  if (b < 1024) return b + " B";
  if (b < 1048576) return (b/1024).toFixed(1) + " KB";
  if (b < 1073741824) return (b/1048576).toFixed(1) + " MB";
  return (b/1073741824).toFixed(2) + " GB";
}
function setBar(id, pct, colorClass) {
  const bar = document.getElementById(id);
  const text = document.getElementById(id.replace("Bar","Text"));
  if (!bar) return;
  const p = Math.min(100, Math.max(0, pct));
  bar.style.width = p + "%";
  bar.className = "fill " + colorClass;
  if (p > 75 && colorClass !== "red") bar.className = "fill red";
  else if (p > 50 && colorClass === "green") bar.className = "fill yellow";
  if (text) text.textContent = p.toFixed(1) + "%";
}
function copyToClipboard(text) {
  try {
    navigator.clipboard.writeText(text).then(() => showCopyFeedback()).catch(() => {
      const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px"; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta); showCopyFeedback();
    });
  } catch(e) {}
}
function showCopyFeedback() {
  // brief visual feedback - handled per button
}

