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
      // timeliness vocabulary: the actual data status of a quote
      "REAL-TIME": ["pill-live", "REAL-TIME"],
      DELAYED: ["pill-delayed", "DELAYED"],
      "END-OF-DAY": ["pill-delayed", "END-OF-DAY"],
      HISTORICAL: ["pill-delayed", "HISTORICAL"],
      CALCULATED: ["pill-calc", "CALCULATED"],
      UNAVAILABLE: ["pill-na", "UNAVAILABLE"],
      ERROR: ["pill-na", "ERROR"],
      "RATE LIMITED": ["pill-na", "RATE LIMITED"],
      "RATE_LIMITED": ["pill-na", "RATE LIMITED"],
      rate_limited: ["pill-na", "RATE LIMITED"],
      AVAILABLE: ["pill-live", "AVAILABLE"],
      STALE: ["pill-na", "STALE"],
      CACHED: ["pill-calc", "CACHED"],
      CROSS_CHECK_OK: ["pill-live", "CROSS-CHECKED"],
      SINGLE_SOURCE: ["pill-delayed", "SINGLE SOURCE"],
      PROVIDER_DISCREPANCY: ["pill-bad", "DISCREPANCY"],
      DISCREPANCY: ["pill-bad", "DISCREPANCY"],
      NOT_COMPARABLE: ["pill-na", "NOT COMPARABLE"],
      PLAN_LIMITATION: ["pill-na", "PLAN LIMITED"],
      PLAN_LIMITED: ["pill-na", "PLAN LIMITED"],
      AUTH_REQUIRED: ["pill-na", "AUTH REQUIRED"],
      KEY_GATED: ["pill-na", "KEY GATED"],
      KEY_REQUIRED: ["pill-na", "KEY REQUIRED"],
      NOT_CONFIGURED: ["pill-na", "NOT CONFIGURED"],
      UPSTREAM_LIMITATION: ["pill-na", "UPSTREAM LIMITED"],
      AUTHORIZATION_REQUIRED: ["pill-na", "AUTH REQUIRED"],
    }[status] || ["pill-na", String(status || "—").toUpperCase()];
    return '<span class="pill ' + m[0] + '">' + m[1] + "</span>";
  }
  var SRC_NAMES = {
    yahoo: "Yahoo Finance", "yahoo-events": "Yahoo Finance",
    "yahoo-rss": "Yahoo Finance", twelvedata: "Twelve Data",
    alphavantage: "Alpha Vantage", estimates: "Estimates feed",
    fundamentals: "Fundamentals feed", "indian-api": "Indian Stock Market API",
  };
  function srcName(s) { return SRC_NAMES[s] || s || "?"; }
  function fmtIST(ts) {
    // ts: epoch seconds OR ISO string. Returns "18:25:04 IST".
    var d = null;
    if (typeof ts === "number") d = new Date(ts * 1000);
    else if (typeof ts === "string") {
      if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) return ts; // bare date, not a time
      d = new Date(ts);
    }
    if (!d || isNaN(d)) return "unavailable";
    try {
      return d.toLocaleTimeString("en-GB", {
        hour: "2-digit", minute: "2-digit", second: "2-digit",
        hour12: false, timeZone: "Asia/Kolkata",
      }) + " IST";
    } catch (e) { return d.toISOString().replace("T", " ").slice(0, 19) + "Z"; }
  }
  function fmtIN(v, ccy) {
    /* Indian scale: lakh-crore aware. 1 Cr = 1e7, 1 L Cr = 1e12. */
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    var n = Number(v), a = Math.abs(n), out;
    if (ccy !== "INR") return fmtMoney(v, ccy);
    if (a >= 1e12) out = (n / 1e12).toFixed(2) + " L Cr";
    else if (a >= 1e7) out = (n / 1e7).toFixed(2) + " Cr";
    else if (a >= 1e5) out = (n / 1e5).toFixed(2) + " L";
    else if (a >= 1e3) out = (n / 1e3).toFixed(2) + "K";
    else out = n.toFixed(2);
    return (ccy ? ccy + " " : "") + out;
  }
  function secId(name, symbol, meta) {
    /* Security identity: human name dominant, ticker + venue secondary. */
    var base = symbol ? String(symbol).replace(/\.(NS|BO)$/, "") : "";
    return '<div class="sec"><div class="s-nm">' + esc(name || symbol || "—") + "</div>" +
      '<div class="s-tk"><b>' + esc(symbol || "—") + "</b>" +
      (meta ? " · " + esc(meta) : "") + "</div></div>";
  }
  function typeBadge(t) {
    var label = "Equity";
    if (/index/i.test(t || "")) label = "Index";
    else if (/etf/i.test(t || "")) label = "ETF";
    else if (/fund|mutual/i.test(t || "")) label = "Fund";
    else if (/crypto/i.test(t || "")) label = "Crypto";
    else if (/forex|currency/i.test(t || "")) label = "FX";
    return '<span class="sect-tag">' + esc(label) + "</span>";
  }
  function prov(source, asOf, status) {
    /* Quiet provenance microcopy: value first, source tertiary. */
    return '<div class="prov">Source <b>' + esc(srcName(source)) + "</b> · " +
      esc(status || "?") + " · as of " + esc(asOf || "unavailable") + "</div>";
  }
  /* Security typing: STOCK vs INDEX vs ETF. Indexes get index-level
     presentation (level, breadth, trend) — never P/E, EPS, ROE cards. */
  var INDEX_SYMS = ["^NSEI", "^NSEBANK", "^BSESN", "^CNXIT", "^CNXAUTO",
    "NIFTY_FIN_SERVICE.NS", "^CNXFMCG", "^CNXPHARMA",
    "^GSPC", "^IXIC", "^RUT", "^FTSE", "^STOXX50E", "^N225", "^HSI"];
  function secType(symbol, quote) {
    var s = String(symbol || "").toUpperCase();
    var q = quote || {};
    var t = String(q.instrument_type || q.type || "");
    if (/etf/i.test(t) || / ETF$/.test(String(q.name || ""))) return "ETF";
    if (s.charAt(0) === "^" || INDEX_SYMS.indexOf(s) >= 0 || /index/i.test(t)) return "INDEX";
    return "STOCK";
  }
  function fmtStmt(v, ccy) {
    /* Statement figures: Indian scale for INR (Cr / L Cr), M/B for rest.
       Unit is shown once above the table — never mixed per cell. */
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    var n = Number(v), a = Math.abs(n);
    if (ccy === "INR") {
      if (a >= 1e12) return (n / 1e12).toFixed(2);
      if (a >= 1e7) return (n / 1e7).toFixed(2);
      if (a >= 1e5) return (n / 1e5).toFixed(2);
      return n.toFixed(2);
    }
    if (a >= 1e9) return (n / 1e9).toFixed(2);
    if (a >= 1e6) return (n / 1e6).toFixed(2);
    return n.toFixed(2);
  }
  function stmtUnit(ccy, magnitude) {
    if (ccy === "INR") {
      if ((magnitude || 0) >= 1e12) return "₹ lakh crore";
      return "₹ crore";
    }
    if ((magnitude || 0) >= 1e9) return "$ billion";
    return "$ million";
  }
  function fmtPrice(v, ccy) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    return (ccy ? ccy + " " : "") + Number(v).toLocaleString("en-IN", {
      minimumFractionDigits: 2, maximumFractionDigits: 2,
    });
  }
  function fmtMult(v) {
    if (v === null || v === undefined || isNaN(Number(v))) return "—";
    return Number(v).toFixed(1) + "x";
  }
  function fmtTimeHM(ts) {
    /* "24 Sep · 4:35 PM" for news rows. Accepts epoch or date strings. */
    var d = null;
    if (typeof ts === "number") d = new Date(ts * 1000);
    else if (typeof ts === "string" && ts) d = new Date(ts);
    if (!d || isNaN(d)) return "—";
    try {
      return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" }) +
        " · " + d.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" }).toUpperCase();
    } catch (e) { return d.toISOString().slice(0, 16).replace("T", " "); }
  }
  /* Company identity registry: canonical display metadata.
     Official logo assets ONLY with verified source (domain + asset URL
     confirmed against the company's own media). No verified asset =>
     monogram fallback. Never hotlink random logo APIs or image search. */
  var LOGOS = {
    /* No verified official assets bundled yet; monograms used throughout.
       To add: { domain: "tatasteel.com", asset: "https://.../logo.svg",
       source: "company media kit", type: "svg" } after verification. */
  };
  function initials(name, symbol) {
    var s = (name || symbol || "?").replace(/limited|ltd\.?|corporation|corp\.?|inc\.?|company|bank/gi, "");
    var words = s.trim().split(/[\s&]+/).filter(Boolean);
    var init = words.length > 1
      ? (words[0][0] + words[1][0])
      : String(s.trim().slice(0, 2));
    return (init || "?").toUpperCase();
  }
  function logoHue(symbol) {
    var h = 0, s = String(symbol || "?");
    for (var i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return h;
  }
  function logo(symbol, name, size) {
    var sz = size || 34, sym = String(symbol || "");
    var reg = LOGOS[sym];
    if (reg && reg.asset) {
      return '<img class="logo" width="' + sz + '" height="' + sz + '" src="' + esc(reg.asset) +
        '" alt="' + esc(name || sym) + ' logo" loading="lazy" referrerpolicy="no-referrer" ' +
        'onerror="this.outerHTML=window.FT_FMT.logoFallback(' + esc(JSON.stringify(sym)) + ',' +
        esc(JSON.stringify(name || "")) + "," + sz + ');">';
    }
    return logoFallback(sym, name || "", sz);
  }
  function logoFallback(symbol, name, size) {
    var sz = size || 34;
    return '<span class="logo logo-mono" style="width:' + sz + "px;height:" + sz + "px;" +
      "background:hsl(" + logoHue(symbol) + ",38%,92%);color:hsl(" + logoHue(symbol) +
      ",45%,32%);font-size:" + Math.round(sz * 0.36) + 'px" aria-hidden="true">' +
      esc(initials(name, symbol)) + "</span>";
  }
  window.FT_FMT = {
    fmtNum, fmtInt, fmtPct, fmtMoney, fmtIN, fmtDate, fmtDateTime, esc,
    dirClass, statusPill, srcName, fmtIST, secId, typeBadge, prov,
    logo, logoFallback, LOGOS, secType, INDEX_SYMS,
    fmtStmt, stmtUnit, fmtPrice, fmtMult, fmtTimeHM,
  };
})();
