/* Fetch wrapper: timeout via AbortController, JSON errors mapped to Error. */
(function () {
  "use strict";

  async function getJSON(url, opts) {
    opts = opts || {};
    const ctrl = new AbortController();
    const timeout = opts.timeout || 25000;
    const timer = setTimeout(() => ctrl.abort(), timeout);
    if (opts.signal) {
      if (opts.signal.aborted) ctrl.abort();
      else opts.signal.addEventListener("abort", () => ctrl.abort(), { once: true });
    }
    try {
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) {
        const err = new Error("HTTP " + resp.status);
        err.status = resp.status;
        throw err;
      }
      return await resp.json();
    } finally {
      clearTimeout(timer);
    }
  }

  window.Api = {
    fetchSnapshot(views, opts) {
      const v = encodeURIComponent(views || "summary");
      return getJSON("/api/spx/snapshot?views=" + v, opts);
    },
    fetchGreeks(expiry, strike, cp, opts) {
      const query = "expiry=" + encodeURIComponent(expiry) +
        "&strike=" + encodeURIComponent(strike) + "&cp=" + encodeURIComponent(cp);
      return getJSON("/api/spx/greeks?" + query, opts);
    },
  };
})();
