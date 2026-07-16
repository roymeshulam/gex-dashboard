/* Formatting helpers. All GEX values arrive from the API in $ millions. */
(function () {
  "use strict";

  function fmtM(m) {
    if (m === null || m === undefined || isNaN(m)) return "—";
    const sign = m < 0 ? "-" : "";
    const a = Math.abs(m);
    if (a >= 1000) return sign + "$" + (a / 1000).toFixed(2) + "B";
    if (a >= 10) return sign + "$" + a.toFixed(0) + "M";
    return sign + "$" + a.toFixed(1) + "M";
  }

  function fmtBn(bn) {
    if (bn === null || bn === undefined || isNaN(bn)) return "—";
    const sign = bn < 0 ? "-" : "";
    const a = Math.abs(bn);
    if (a >= 1000) return sign + "$" + (a / 1000).toFixed(2) + "T";
    return sign + "$" + a.toFixed(2) + "B";
  }

  function fmtCount(n) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return String(n);
  }

  function fmtPrice(n) {
    if (n === null || n === undefined || isNaN(n)) return "—";
    return "$" + Number(n).toFixed(2);
  }

  function fmtPct(p, dp) {
    if (p === null || p === undefined || isNaN(p)) return "—";
    return (p > 0 ? "+" : "") + p.toFixed(dp === undefined ? 2 : dp) + "%";
  }

  function fmtStrike(s) {
    if (s === null || s === undefined) return "—";
    return Number.isInteger(s) ? String(s) : s.toFixed(2).replace(/\.?0+$/, "");
  }

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function fmtExpiry(iso) {
    if (!iso || iso === "ALL") return "All expirations";
    const p = iso.split("-");
    return MONTHS[parseInt(p[1], 10) - 1] + " " + parseInt(p[2], 10);
  }

  function fmtExpiryDte(iso, today) {
    if (!iso || iso === "ALL") return "All expirations";
    const p = iso.split("-").map(Number);
    const now = today || new Date();
    const todayUtc = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    const expiryUtc = Date.UTC(p[0], p[1] - 1, p[2]);
    const dte = Math.round((expiryUtc - todayUtc) / 86400000);
    return fmtExpiry(iso) + " (" + dte + " DTE)";
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    const et = d.toLocaleTimeString("en-US", {
      hour: "2-digit", minute: "2-digit", hour12: false,
      timeZone: "America/New_York",
    });
    const local = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return et + " ET (" + local + " local)";
  }

  window.Fmt = {
    fmtM, fmtBn, fmtCount, fmtPrice, fmtPct, fmtStrike, fmtExpiry, fmtExpiryDte, fmtTime,
  };
})();
