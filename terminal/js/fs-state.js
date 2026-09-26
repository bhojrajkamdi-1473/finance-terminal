/* FINSIGHT data-state system (spec sections 4, 5).
   Transport state x backend status -> one UI kind. Single StatusBadge and
   Provenance renderer used by every screen. esc() on all backend text. */
(function () {
  "use strict";
  function esc(s) {
    return String(s === null || s === undefined ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function isEmptyData(data) {
    if (data === null || data === undefined) return true;
    if (Array.isArray(data)) return data.length === 0;
    if (typeof data === "object") return Object.keys(data).length === 0;
    return false;
  }
  /* Resolve a finished FS_API result to one UI kind (spec 4.4). */
  function resolve(result) {
    if (!result || result.state === "network-error") return { kind: "network-error" };
    var b = result.body || {}, st = b.status || "error";
    if (st === "unavailable") return { kind: "unavailable", body: b };
    if (st === "error") return { kind: "error", body: b };
    if (isEmptyData(b.data)) return { kind: "empty", body: b };
    return { kind: "value", body: b };
  }
  /* Feed-timeliness legend (spec 4.0): REAL-TIME · STALE · CALCULATED ·
     UNAVAILABLE, plus transport-level error. Live backend envelopes still
     emit status live|delayed, mapped here: live->REAL-TIME, delayed->STALE.
     timeliness:"CALCULATED" or a terminal-calc/terminal-kpi-engine source
     forces CALCULATED. MF NAV rule (spec 7.15): never REAL-TIME — the MF
     screen must pass forceStale:true. */
  function badge(status, asOf, extra) {
    extra = extra || {};
    var s = String(status || "").toLowerCase();
    var t = String(extra.timeliness || "").toLowerCase();
    var src = String(extra.source || "").toLowerCase();
    if (extra.forceStale) {
      var d0 = asOf ? " " + esc(String(asOf).slice(0, 10)) : "";
      return '<span class="pill pill-delayed">STALE' + d0 + "</span>";
    }
    if (t === "calculated" || s === "calculated" ||
        src.indexOf("terminal-calc") === 0 || src.indexOf("terminal-kpi") === 0) {
      return '<span class="pill pill-calc">CALCULATED</span>';
    }
    if (s === "live") return '<span class="pill pill-live">REAL-TIME</span>';
    if (s === "delayed") {
      var d = asOf ? " " + esc(String(asOf).slice(0, 10)) : "";
      return '<span class="pill pill-delayed">STALE' + d + "</span>";
    }
    if (s === "unavailable") return '<span class="pill pill-na">UNAVAILABLE</span>';
    return '<span class="pill pill-bad">ERROR</span>';
  }
  /* Provenance: [badge] [class-tag] provider-name · as_of. Provider name
     shown literally (spec 4.4 disclosure rule), never a generic "source". */
  function provenance(env, cls) {
    if (!env) return "";
    var bits = [badge(env.status, env.as_of, env)];
    if (cls && cls !== "Source Fact") bits.push('<span class="cx-q cx-q-calc">' + esc(cls.toUpperCase()) + "</span>");
    var src = env.source ? esc(env.source) : "";
    var asof = env.as_of ? esc(String(env.as_of).slice(0, 16).replace("T", " ")) : "";
    var tail = [src, asof].filter(Boolean).join(" · ");
    if (tail) bits.push('<span class="src">' + tail + "</span>");
    return '<div class="prov">' + bits.join(" ") + "</div>";
  }
  function skeleton(n) {
    var h = "";
    for (var i = 0; i < (n || 3); i++) h += '<div class="skel"></div>';
    return h;
  }
  function emptyState(title, msg) {
    return '<div class="empty"><b>' + esc(title) + "</b><br>" + esc(msg || "No records found.") + "</div>";
  }
  function unavailableState(msg, env) {
    return '<div class="empty"><b>DATA UNAVAILABLE</b><br>' + esc(msg || (env && env.message) || "No configured provider currently supplies this dataset.") + "</div>" +
      (env ? provenance(env) : "");
  }
  function errorState(msg, onRetry) {
    return '<div class="err"><b>Unable to retrieve dataset.</b><br>' + esc(msg || "") +
      (onRetry ? ' <button class="btn sm" data-fs-retry="1">Retry</button>' : "") + "</div>";
  }
  window.FS_STATE = {
    esc: esc, resolve: resolve, badge: badge, provenance: provenance,
    skeleton: skeleton, emptyState: emptyState,
    unavailableState: unavailableState, errorState: errorState
  };
})();
