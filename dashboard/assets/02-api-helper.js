// ===== API HELPER =====
async function api(path, opts = {}) {
  try {
    const r = await fetch(BASE + path, {headers, ...opts});
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      let errMsg = "HTTP " + r.status;
      try { const j = JSON.parse(text); if (j.error) errMsg += ": " + j.error; } catch(_) {}
      overviewMetrics.errors++;
      return {ok: false, error: errMsg};
    }
    overviewMetrics.requests++;
    return await r.json();
  } catch(e) {
    overviewMetrics.errors++;
    return {ok: false, error: e.message || "Network error"};
  }
}

