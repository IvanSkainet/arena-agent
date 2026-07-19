// ===== API HELPER =====
// v4.50.2: caller-supplied headers now DEEP-merge with the auth
// headers instead of clobbering them. Previously the second arg
// spread was `{headers, ...opts}` -- if `opts.headers` was set
// (e.g. Content-Type: application/json for a POST), it fully
// replaced the module-level `headers` object that carries the
// Bearer token, producing a silent HTTP 401. Broke the GitHub-
// token save form the moment it landed in v4.50.0.
async function api(path, opts = {}) {
  try {
    const merged = Object.assign({}, headers, opts.headers || {});
    const finalOpts = Object.assign({}, opts, {headers: merged});
    const r = await fetch(BASE + path, finalOpts);
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


