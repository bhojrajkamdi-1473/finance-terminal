/* Formatting helpers: numbers, currency, dates. Missing data -> em-dash. */
(function () {
  "use strict";
  function fmtNum(v, dp) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    return Number(v).toLocaleString("en-US", {
      minimumFractionDigits: dp === undefined ? 2 : dp,
      maximumFractionDigits: dp === undefined ? 2 : dp,
    });
  }
  function fmtInt(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    return Math.round(Number(v)).toLocaleString("en-US");
  }
  function fmtPct(v, dp) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    var s = Number(v).toFixed(dp === undefined ? 2 : dp) + "%";
    return (Number(v) > 0 ? "+" : "") + s;
  }
  function fmtMoney(v, ccy) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    var n = Number(v), a = Math.abs(n), out;
    if (a >= 1e12) out = (n / 1e12).toFixed(2) + "T";
    else if (a >= 1e9) out = (n / 1e9).toFixed(2) + "B";
    else if (a >= 1e6) out = (n / 1e6).toFixed(2) + "M";
    else if (a >= 1e3) out = (n / 1e3).toFixed(2) + "K";
    else out = n.toFixed(2);
    return (ccy ? ccy + " " : "") + out;
  }
  function fmtDate(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    if (isNaN(d)) return "—";
    return d.toISOString().slice(0, 10);
  }
  function fmtDateTime(ts) {
    if (!ts) return "—";
    var d = new Date(ts * 1000);
    if (isNaN(d)) return "—";
    return d.toISOString().replace("T", " ").slice(0, 16) + "Z";
  }
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function dirClass(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return "mut";
    return Number(v) > 0 ? "up" : Number(v) < 0 ? "dn" : "mut";
  }
  function statusPill(status) {
    var m = {
      live: ["pill-live", "LIVE"], delayed: ["pill-delayed", "DELAYED"],
      calculated: ["pill-calc", "CALC"], ai: ["pill-ai", "AI"],
      unavailable: ["pill-na", "UNAVAIL"], error: ["pill-na", "ERROR"],
    }[status] || ["pill-na", String(status || "—").toUpperCase()];
    return '<span class="pill ' + m[0] + '">' + m[1] + "</span>";
  }
  window.FT_FMT = { fmtNum, fmtInt, fmtPct, fmtMoney, fmtDate, fmtDateTime, esc, dirClass, statusPill };
})();
