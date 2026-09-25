/* FT company experience — institutional redesign (cx).
   Overrides FT_PAGES.pCompany with a dense, editorial layout:
   compact header, metric strip, underline tabs, 75/25 main+rail grid,
   section-level loading, unified empty/error states, diagnostics rail.
   Data logic preserved; only presentation changes. No mock data. */
(function () {
  "use strict";
  var API, F;
  var CTABS = ["Overview", "Financials", "Valuation", "Estimates", "Earnings",
    "News", "Actions", "Ownership", "Charts", "Technicals", "Research"];
  /* Indexes get their own tab set and metric model — never P/E, EPS,
     ROE cards. Every renderer below branches on secType(). */
  var INDEX_TABS = ["Overview", "News", "Charts", "Technicals", "Research"];
  var STOCK_ONLY = { Financials: 1, Valuation: 1, Estimates: 1, Earnings: 1, Ownership: 1, Actions: 1 };
  function secType(sym, quote) { return window.FT_FMT.secType(sym, quote); }
  var timers = [];
  function later(ms, fn) { var id = setInterval(function () { fn(); }, ms); timers.push(id); }
  function clearCx() { timers.forEach(clearInterval); timers = []; }
  window.addEventListener("hashchange", clearCx);
  if (!window.__ftCxClickBound__) {
    window.__ftCxClickBound__ = true;
    document.addEventListener("click", retryHandler);
  }

  function E(id) { return document.getElementById(id); }
  function V() { return E("view"); }
  function esc(s) { return (window.FT_FMT ? window.FT_FMT.esc(String(s === null || s === undefined ? "" : s)) : String(s)); }
  /* Clean any backend token into an em-dash for display. */
  function Cv(v) {
    if (v === null || v === undefined) return "";
    var s = String(v).trim();
    if (/^(none|null|undefined|nan|-|n\/a)$/i.test(s) || s === "") return "";
    return esc(s);
  }
  function Num(v, fn) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "string" && /^(none|null|undefined|nan|-|n\/a)$/i.test(v.trim())) return "—";
    if (isNaN(Number(v))) return "—";
    return fn(Number(v));
  }
  function dir(v) { return window.FT_FMT.dirClass(v); }
  /* Market bucket mirrored from the server classifier (quote.market):
     India / US / Global shown as separate categories, never mixed. */
  function marketOf(sym, exch, ccy) {
    var s = String(sym || "").toUpperCase();
    var e = String(exch || "").toUpperCase();
    var c = String(ccy || "").toUpperCase();
    if (s.indexOf("=") >= 0 || /-USD$/.test(s)) return { id: "GLOBAL", label: "Global" };
    if (/\.NS$|\.BO$/.test(s) || /NSE|BSE|KOLKATA|MUMBAI/.test(e) || c === "INR" ||
        s === "^NSEI" || s === "^NSEBANK" || s === "^BSESN" || s.indexOf("^CNX") === 0) {
      return { id: "IN", label: "India" };
    }
    if (/NASDAQ|NYSE|AMEX|ARCA|BATS|IEX/.test(e) ||
        (c === "USD" && s.indexOf(".") < 0 && s.charAt(0) !== "^")) {
      return { id: "US", label: "US" };
    }
    return { id: "GLOBAL", label: "Global" };
  }
  function marketPill(mkt) {
    var cls = mkt.id === "IN" ? "cx-q-rep" : (mkt.id === "US" ? "cx-q-calc" : "cx-q-na");
    return "<span class='cx-q " + cls + "' title='Market bucket'>" + esc(mkt.label || "Global") + "</span>";
  }
  function badge(st) {
    var s = String(st || "").toUpperCase();
    var cls = "cx-b-na", lbl = s || "—";
    if (/LIVE/.test(s)) { cls = "cx-b-live"; lbl = "LIVE"; }
    else if (/REAL-TIME/.test(s)) { cls = "cx-b-live"; lbl = "REAL-TIME"; }
    else if (/DELAY|END-OF-DAY|HISTORICAL|SINGLE/.test(s)) { cls = "cx-b-del"; lbl = "DELAYED"; }
    else if (/CALC/.test(s)) { cls = "cx-b-calc"; lbl = "CALCULATED"; }
    return '<span class="cx-badge ' + cls + '">' + esc(lbl) + "</span>";
  }
  function day(iso) {
    if (!iso) return "—";
    try {
      var d = new Date(iso);
      if (isNaN(d)) return "—";
      return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata" });
    } catch (e) { return "—"; }
  }
  /* Single provenance line per section. Unknown parts are dropped;
     nothing renders when nothing is known. No "?", no placeholders. */
  function prov(env) {
    if (!env) return "";
    var F2 = window.FT_FMT, parts = [];
    var src = env.source ? F2.srcName(env.source) : "";
    if (src && src !== "?") parts.push("Data · " + src);
    else parts.push("Market data");
    var st = env.timeliness || env.status || "";
    if (/delay/i.test(st)) parts.push("delayed");
    var asof = String(env.as_of || "").slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}/.test(asof)) parts.push(asof);
    if (parts.length <= 1) return "";
    return '<div class="cx-prov">' + esc(parts.join(" · ")) + "</div>";
  }
  function empty(title, why) {
    return '<div class="cx-empty" role="status"><b>' + esc(title) + "</b><p>No verified data available.</p>" +
      (why ? '<p class="why">Why: ' + esc(why) + '</p>' : "") +
      '<p class="why">See Data sources in the side panel for provider detail.</p></div>';
  }
  function err() {
    return '<div class="cx-err" role="alert"><b>Unable to load this section.</b><br>' +
      'Other sections remain available. <button class="cx-btn2" data-cx-retry="1" style="margin-left:8px">Try again</button></div>';
  }
  function skel(n) {
    var h = "";
    for (var i = 0; i < (n || 3); i++) h += '<div class="cx-skel"></div>';
    return '<div aria-label="Loading">' + h + "</div>";
  }
  function toast(m) { if (window.FT_PAGES && window.FT_PAGES.toast) window.FT_PAGES.toast(m); }

  /* ---------------- entry ---------------- */
  function pCompany(sym, tab) {
    API = window.FT_API; F = window.FT_FMT;
    sym = String(sym || "").toUpperCase();
    var isIdx = secType(sym) === "INDEX";
    var tabs = isIdx ? INDEX_TABS : CTABS;
    if (tabs.indexOf(tab) < 0) tab = "Overview";
    clearCx();
    V().innerHTML =
      '<div class="cx-wrap"><div class="cx-head" id="cx-head">' + skel(2) + "</div>" +
      '<nav class="cx-tabs" role="tablist" aria-label="Company sections" id="cx-tabs">' +
      tabs.map(function (t) {
        return '<button role="tab" aria-selected="' + (t === tab) + '" data-t="' + t + '" class="' + (t === tab ? "on" : "") + '">' + t + "</button>";
      }).join("") + "</nav>" +
      '<div class="cx-grid"><div class="cx-main" id="cx-main">' + skel(5) + "</div>" +
      '<aside class="cx-rail" id="cx-rail" aria-label="Context"></aside></div></div>';
    Array.prototype.forEach.call(document.querySelectorAll("#cx-tabs button"), function (btn) {
      btn.onclick = function () { location.hash = "#/company/" + encodeURIComponent(sym) + "/" + btn.getAttribute("data-t"); };
    });
    loadHead(sym);
    loadRail(sym);
    renderTab(sym, tab);
    later(30000, function () {
      if (!E("cx-px")) return;
      API.get("quote", { symbol: sym }).then(function (r) {
        var q = r.body && r.body.data;
        if (q && E("cx-px")) paintPrice(q, r.body);
      });
    });
  }
  function retryHandler(ev) {
    if (ev.target && ev.target.getAttribute && ev.target.getAttribute("data-cx-retry")) {
      var h = (location.hash || "").split("/");
      renderTab((h[2] || "").toUpperCase(), decodeURIComponent(h[3] || "Overview"));
    }
  }
  function paintPrice(q, env) {
    E("cx-px").innerHTML = F.fmtNum(q.price) + " <small>" + esc(q.currency || "") + "</small>";
    var c = E("cx-chg");
    if (c) c.innerHTML = '<span class="' + dir(q.change_pct) + '">' + F.fmtPct(q.change_pct) + "</span> " +
      '<span class="mut">(' + F.fmtNum(q.change) + " " + esc(q.currency || "") + ")</span>";
    var s = E("cx-srcline");
    if (s) {
      var bits = [];
      var src = env.source ? F.srcName(env.source) : "";
      if (src && src !== "?") bits.push(src);
      var st = env.timeliness || env.status || "";
      if (/delay/i.test(st)) bits.push("delayed");
      var asof = String(env.as_of || "").slice(0, 10);
      if (/^\d{4}-\d{2}-\d{2}/.test(asof)) bits.push(asof);
      s.innerHTML = bits.length ? bits.map(esc).join(" · ") : "";
    }
  }
  /* Metric strip with REPORTED/CALCULATED badges + formula inspector.
     Every metric carries its provenance; CALCULATED cells open the
     inspector (formula, inputs, period, source, timestamp). */
  var STRIP_INFO = {};
  function qBadge(kind) {
    if (kind === "CALCULATED") return " <span class='cx-q cx-q-calc' title='Calculated by the terminal ratio engine'>CALC</span>";
    if (kind === "REPORTED") return " <span class='cx-q cx-q-rep' title='Reported by the data provider'>REP</span>";
    return "";
  }
  function qVal(node, fmt) {
    if (!node || node.value === null || node.value === undefined || isNaN(Number(node.value))) return null;
    return fmt(Number(node.value));
  }
  function paintStrip(sym, d, q, sheet) {
    function rep(raw, fmt) {
      if (raw === undefined || raw === null || /^(none|-|n\/a)$/i.test(String(raw)) || isNaN(Number(raw))) return null;
      return { v: fmt(Number(raw)), kind: "REPORTED", info: null };
    }
    function x1(v) { return v.toFixed(1) + "x"; }
    var disp = (sheet && sheet.display) || {};
    function pick(repNode, calcKey, fmt) {
      if (repNode) return repNode;
      var c = disp[calcKey];
      var v = qVal(c, fmt);
      if (v === null) return null;
      return { v: v, kind: "CALCULATED", info: c };
    }
    var roeRep = (d.ROE && d.ROE !== "None" && !isNaN(Number(d.ROE)))
      ? { v: Number(d.ROE).toFixed(1) + "%", kind: "REPORTED", info: null } : null;
    var cells = [
      ["Market Cap", rep(d.MarketCapitalization && d.MarketCapitalization !== "None" ? d.MarketCapitalization : null,
        function (v) { return F.fmtIN(v, q.currency); })],
      ["P/E", rep(d.PERatio && d.PERatio !== "None" ? d.PERatio : null, x1) ||
        (disp.pe_calc ? { v: qVal(disp.pe_calc, x1), kind: "CALCULATED", info: disp.pe_calc } : null)],
      ["EPS", rep(d.EPS && d.EPS !== "None" ? d.EPS : null, function (v) { return F.fmtNum(v); })],
      ["ROE", pick(roeRep, "roe", function (v) { return v.toFixed(1) + "%"; })],
      ["ROCE", disp.roce ? { v: qVal(disp.roce, function (v) { return v.toFixed(1) + "%"; }), kind: "CALCULATED", info: disp.roce } : null],
      ["Book Value", rep(d.BookValue && d.BookValue !== "None" ? d.BookValue : null, function (v) { return F.fmtNum(v); })],
      ["Div Yield", rep(d.DividendYield && d.DividendYield !== "None" ? d.DividendYield : null, function (v) { return v.toFixed(2) + "%"; })],
      ["Debt/Eq", disp.debt_equity ? { v: qVal(disp.debt_equity, x1), kind: "CALCULATED", info: disp.debt_equity } : null],
      ["52W High", (q.fifty_two_week_high === null || q.fifty_two_week_high === undefined) ? null : { v: F.fmtNum(q.fifty_two_week_high), kind: "REPORTED", info: null }],
      ["52W Low", (q.fifty_two_week_low === null || q.fifty_two_week_low === undefined) ? null : { v: F.fmtNum(q.fifty_two_week_low), kind: "REPORTED", info: null }],
    ];
    STRIP_INFO = {};
    var liveCells = cells.filter(function (c) { return c[1] && c[1].v !== null; });
    if (!liveCells.length) { E("cx-strip").innerHTML = ""; return; }
    E("cx-strip").innerHTML = liveCells.map(function (c, ix) {
      var n = c[1];
      var key = "m" + ix;
      STRIP_INFO[key] = n.info;
      var clickable = n.info ? " data-insp='" + key + "' role='button' tabindex='0' title='Open formula inspector: " +
        esc(n.info.formula || "") + "' style='cursor:pointer'" : "";
      var sub = n.kind === "CALCULATED" ? "calculated" + ((n.info && n.info.variant) ? " · " + esc(n.info.variant) : "") : "";
      return '<div class="cx-m"' + clickable + '><div class="l">' + c[0] + qBadge(n.kind) + '</div><div class="v">' + n.v +
        "</div>" + (sub ? "<div class='s'>" + sub + "</div>" : "") + "</div>";
    }).join("") + '<div id="cx-insp"></div>';
    Array.prototype.forEach.call(E("cx-strip").querySelectorAll("[data-insp]"), function (el) {
      function open() { showInspector(STRIP_INFO[el.getAttribute("data-insp")]); }
      el.onclick = open;
      el.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } };
    });
  }
  /* Index metric strip: level context only — never stock multiples.
     Missing index fields are omitted (no placeholder cells). */
  function paintIndexStrip(sym, q, env) {
    if (!E("cx-strip")) return;
    var hi = q.fifty_two_week_high, lo = q.fifty_two_week_low, px = q.price;
    var dist = (hi !== null && hi !== undefined && px !== null && px !== undefined && hi) ?
      ((px - hi) / hi * 100) : null;
    function cell(l, v, s) {
      if (v === null || v === undefined) return "";
      return '<div class="cx-m"><div class="l">' + l + '</div><div class="v">' + v +
        '</div><div class="s">' + esc(s || "") + "</div></div>";
    }
    var html =
      cell("Day high", (q.day_high === null || q.day_high === undefined) ? null : F.fmtNum(q.day_high), "index level") +
      cell("Day low", (q.day_low === null || q.day_low === undefined) ? null : F.fmtNum(q.day_low), "index level") +
      cell("52-week high", (hi === null || hi === undefined) ? null : F.fmtNum(hi), "index level") +
      cell("52-week low", (lo === null || lo === undefined) ? null : F.fmtNum(lo), "index level") +
      cell("Distance from high", dist === null ? null : F.fmtPct(dist), "calculated") +
      cell("Prev close", (q.previous_close === null || q.previous_close === undefined) ? null : F.fmtNum(q.previous_close), "index level");
    E("cx-strip").innerHTML = html + '<div id="cx-insp"></div>';
  }
  function showInspector(info) {
    var host = E("cx-insp");
    if (!host || !info) return;
    host.innerHTML = '<div class="cx-inspector" role="dialog" aria-label="Formula inspector"><b>' + esc(info.label || "Calculated metric") +
      " " + esc(String(info.value)) + esc(info.unit || "") + " — CALCULATED</b>" +
      '<div class="cx-kv"><span class="k">Formula</span><span class="w">' + esc(info.formula || "") + "</span></div>" +
      (info.inputs || []).map(function (i) {
        return '<div class="cx-kv"><span class="k">' + esc(i.label || "") + (i.period ? " (" + esc(i.period) + ")" : "") +
          '</span><span class="w">' + esc(i.value === null || i.value === undefined ? "" : String(i.value)) + " · " + esc(i.source || "") + "</span></div>";
      }).join("") +
      (info.variant ? '<div class="cx-note">Variant: ' + esc(info.variant) + "</div>" : "") +
      '<div class="cx-note">Calculated ' + esc(info.calculated_at || "") + ' · <button class="cx-btn2" id="cx-insp-x">Close</button></div></div>';
    E("cx-insp-x").onclick = function () { host.innerHTML = ""; };
  }
  /* Accessible inline modal for portfolio entry (replaces browser prompt). */
  function openHoldingModal(sym, q) {
    closeHoldingModal();
    var back = document.createElement("div");
    back.className = "modal-back";
    back.id = "cx-modal";
    back.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-label="Add holding">' +
      "<h3>Add holding — " + esc(sym) + "</h3>" +
      "<label class='lbl' for='cx-m-q'>Quantity</label>" +
      "<input id='cx-m-q' class='cx-in' style='width:100%' value='10' inputmode='decimal'>" +
      "<label class='lbl' for='cx-m-p' style='margin-top:8px;display:block'>Average buy price (" + esc(q.currency || "") + ")</label>" +
      "<input id='cx-m-p' class='cx-in' style='width:100%' value='" + esc(String(q.price || "")) + "' inputmode='decimal'>" +
      "<div class='row'><button class='cx-btn2' id='cx-m-x'>Cancel</button>" +
      "<button class='cx-btn' id='cx-m-ok'>Save holding</button></div></div>";
    document.body.appendChild(back);
    function done() { closeHoldingModal(); }
    E("cx-m-x").onclick = done;
    back.onclick = function (ev) { if (ev.target === back) done(); };
    back.onkeydown = function (ev) { if (ev.key === "Escape") done(); };
    E("cx-m-ok").onclick = function () {
      API.post("portfolio", {
        symbol: sym, name: q.name || "",
        quantity: Number(E("cx-m-q").value), avg_price: Number(E("cx-m-p").value),
      }).then(function (r) {
        toast(r.body.ok ? sym + " added to portfolio." : "Could not save holding.");
        done();
      });
    };
    E("cx-m-q").focus();
  }
  function closeHoldingModal() {
    var m = E("cx-modal");
    if (m) m.remove();
  }
  function loadHead(sym) {
    Promise.all([API.get("company", { symbol: sym }), API.get("quote", { symbol: sym })]).then(function (rs) {
      if (!E("cx-head")) return;
      var prof = rs[0].body || {}, qenv = rs[1].body || {};
      var q = qenv.data || {}, p = prof.data || {};
      var nm = q.name || p.name || sym;
      var exch = q.exchange || p.exchange || "";
      var mkt = qenv.market || marketOf(sym, exch, q.currency);
      var country = mkt.id === "IN" ? "India" : (mkt.id === "US" ? "USA" : "");
      E("cx-head").innerHTML =
        '<div class="cx-idrow">' + F.logo(sym, nm, 40) +
        '<div><h1 class="cx-name">' + esc(nm) + "</h1>" +
        '<div class="cx-sub">' + esc(sym.replace(/\.(NS|BO)$/, "")) + (exch ? " · " + esc(exch) : "") + (country ? " · " + esc(country) : "") +
        " " + marketPill(mkt) +
        (secType(sym) === "INDEX" ? " · Index" : "") +
        ((p.sector || p.industry) ? " · " + esc([p.sector, p.industry].filter(Boolean).join(" — ")) : "") + "</div></div></div>" +
        '<div class="cx-pxrow"><div><div class="cx-px" id="cx-px">' + F.fmtNum(q.price) + " <small>" + esc(q.currency || "") + "</small></div>" +
        '<div class="cx-chg" id="cx-chg"><span class="' + dir(q.change_pct) + '">' + F.fmtPct(q.change_pct) + "</span> " +
        '<span class="mut">(' + F.fmtNum(q.change) + " " + esc(q.currency || "") + ")</span></div>" +
        '<div class="cx-src" id="cx-srcline">' + badge(qenv.timeliness || qenv.status) + " " + esc(F.srcName(qenv.source)) + " · " + esc(day(qenv.as_of)) + "</div></div>" +
        '<div class="cx-actions"><button class="cx-btn2" id="cx-wl">+ Watchlist</button>' +
        '<button class="cx-btn2" id="cx-pf">+ Portfolio</button>' +
        '<button class="cx-btn2" id="cx-cmp">Compare</button></div></div>' +
        '<div class="cx-strip" id="cx-strip">' + skel(2) + "</div>";
      E("cx-wl").onclick = function () {
        API.post("watchlist", { symbol: sym, name: q.name || "" }).then(function (r) {
          toast(r.body.ok ? sym + " added to watchlist." : "Could not add to watchlist.");
        });
      };
      E("cx-cmp").onclick = function () { location.hash = "#/compare"; try { sessionStorage.setItem("ft-cmp", sym); } catch (e) { /* ignore */ } };
      E("cx-pf").onclick = function () { openHoldingModal(sym, q); };
      if (secType(sym) === "INDEX") { paintIndexStrip(sym, q, qenv); return; }
      /* Centralized KPI engine first (single source of truth for every
         surface); ratios/ratiosheet remain the fallback drill-down. */
      API.get("kpi", { symbol: sym }).then(function (rk) {
        if (!E("cx-strip")) return;
        var bundle = (rk.body && rk.body.data && rk.body.data.kpis) || null;
        if (bundle) {
          var d = {
            MarketCapitalization: bundle.market_cap && bundle.market_cap.value,
            PERatio: (bundle.pe && bundle.pe.value) || (bundle.pe_calc && bundle.pe_calc.value),
            EPS: bundle.eps && bundle.eps.value,
            ROE: bundle.roe && bundle.roe.value,
            BookValue: bundle.book_value && bundle.book_value.value,
            DividendYield: bundle.div_yield && bundle.div_yield.value,
          };
          var sheet = { display: {} };
          ["roe", "roce", "roa", "op_margin", "net_margin", "debt_equity", "fcf"].forEach(function (kk) {
            if (bundle[kk]) sheet.display[kk === "div_yield" ? "div_yield_calc" : kk] = bundle[kk];
          });
          if (bundle.pe_calc) sheet.display.pe_calc = bundle.pe_calc;
          paintStrip(sym, d, q, sheet);
          return;
        }
        return API.get("ratios", { symbol: sym }).then(function (r) {
          if (!E("cx-strip")) return;
          var d2 = (r.body && r.body.data) || {};
          paintStrip(sym, d2, q, null);
          API.get("ratiosheet", { symbol: sym }).then(function (rs) {
            if (!E("cx-strip")) return;
            var sh = (rs.body && rs.body.data) || null;
            if (sh) paintStrip(sym, d2, q, sh);
          }).catch(function () { /* strip already painted */ });
        });
      }).catch(function () { /* strip stays empty; section loaders continue */ });
    });
  }
  /* ---------------- right rail ---------------- */
  function loadRail(sym) {
    var rail = E("cx-rail");
    if (!rail) return;
    rail.innerHTML =
      '<div class="cx-railsec"><h3>Key events</h3><div id="cx-ev">' + skel(2) + "</div></div>" +
      '<div class="cx-railsec"><h3>Research links</h3><div id="cx-hub">' + skel(2) + "</div></div>" +
      '<div class="cx-railsec"><h3>Data sources</h3><div id="cx-ds">' + skel(2) + "</div>" +
      '<details style="margin-top:8px"><summary>Developer diagnostics</summary><div id="cx-dg" style="margin-top:6px">' + skel(2) + "</div></details></div>";
    API.get("actions", { symbol: sym }).then(function (r) {
      if (!E("cx-ev")) return;
      var d = (r.body && r.body.data) || {};
      var evs = (d.dividends || []).map(function (x) { return { date: x.date, t: "Dividend", v: F.fmtNum(x.amount, 4) + " " + (x.currency || "") }; })
        .concat((d.splits || []).map(function (x) { return { date: x.date, t: "Split", v: x.numerator + ":" + x.denominator }; }))
        .sort(function (a, b) { return String(b.date) > String(a.date) ? 1 : -1; }).slice(0, 3);
      E("cx-ev").innerHTML = evs.length ? evs.map(function (e) {
        return '<div class="cx-kv"><span class="k">' + esc(String(e.date).slice(0, 10)) + " · " + esc(e.t) + '</span><span class="w">' + esc(e.v) + "</span></div>";
      }).join("") : '<div class="cx-note">No recent events.</div>';
    });
    API.get("research-links", { symbol: sym }).then(function (r) {
      if (!E("cx-hub")) return;
      var b = r.body || {};
      var all = (b.official || []).concat(b.research || []).slice(0, 6);
      E("cx-hub").innerHTML = all.length ? all.map(function (x) {
        return x.url ? '<div class="cx-kv"><span class="k">' + esc(x.name) + '</span><span class="w"><a href="' + esc(x.url) + '" target="_blank" rel="noopener">Open</a></span></div>'
          : '<div class="cx-kv"><span class="k">' + esc(x.name) + '</span><span class="w mut">—</span></div>';
      }).join("") : '<div class="cx-note">No links.</div>';
    });
    API.get("quality", { symbol: sym }).then(function (r) {
      if (!E("cx-ds")) return;
      var b = r.body || {}, rows = b.providers || [], q = b.quote || {};
      var named = rows.filter(function (p) { return /connected|cooling|widget/.test(p.state || ""); })
        .map(function (p) { return esc(p.label); }).join(" · ");
      E("cx-ds").innerHTML = '<div class="cx-kv"><span class="k">Quote</span><span class="w">' +
        esc(F.srcName(q.quote_source)) + " · " + esc(q.quote_status || "") + "</span></div>" +
        (named ? '<div class="cx-note">Also reachable: ' + named + "</div>" : "") +
        '<div class="cx-note">Full detail under Developer diagnostics.</div>';
      var dg = E("cx-dg");
      if (dg) {
        dg.innerHTML = rows.map(function (p) {
          return '<div class="cx-kv"><span class="k">' + esc(p.label) + (p.state ? " (" + esc(p.state) + ")" : "") + '</span><span class="w mut">' +
            esc(String(p.last_latency_ms === null || p.last_latency_ms === undefined ? (p.last_error ? String(p.last_error).slice(0, 60) : "") : p.last_latency_ms + " ms")) + "</span></div>";
        }).join("") +
          (q.providers_queried ? '<div class="cx-note">Queried: ' + esc(q.providers_queried.join(", ")) + "</div>" : "") +
          (q.leg_errors ? '<div class="cx-note">' + esc(Object.keys(q.leg_errors).map(function (k) { return k + ": " + q.leg_errors[k]; }).join(" · ").slice(0, 300)) + "</div>" : "");
      }
    });
  }
  /* ---------------- tab router ---------------- */
  function renderTab(sym, tab) {
    var m = E("cx-main");
    if (!m) return;
    if (secType(sym) === "INDEX" && STOCK_ONLY[tab]) {
      m.innerHTML = sec("Not applicable to indexes",
        "<div class='cx-empty'><b>Index security</b><p>Financial statements, valuation multiples, " +
        "estimates, earnings and ownership apply to listed companies — not to index levels.</p>" +
        "<p class='why'>Use Overview for trend and breadth, Charts for history, Technicals for structure.</p></div>");
      return;
    }
    var R = {
      Overview: tOverview, Financials: tFinancials, Valuation: tValuation,
      Estimates: tEstimates, Earnings: tEarnings, News: tNews, Actions: tActions,
      Ownership: tHoldings, Charts: tCharts, Technicals: tTechnicals, Research: tResearchNew,
    };
    (R[tab] || tOverview)(sym, m);
  }
  function sec(title, inner, tag) {
    return '<section class="cx-sec" aria-label="' + esc(title) + '"><h2>' + esc(title) + (tag ? ' <span class="tag">' + tag + "</span>" : "") + "</h2>" + inner + "</section>";
  }
  function perf(sym, main) {
    /* Overview analyst dashboard. */
    main.innerHTML = '<div id="cx-ov-biz">' + skel(2) + '</div><div id="cx-ov-perf">' + skel(2) + '</div>' +
      '<div id="cx-ov-tech">' + skel(2) + '</div><div id="cx-ov-ratio">' + skel(2) + '</div><div id="cx-ov-news">' + skel(3) + "</div>";
    API.get("company", { symbol: sym }).then(function (r) {
      if (!E("cx-ov-biz")) return;
      var p = (r.body && r.body.data) || null;
      E("cx-ov-biz").innerHTML = sec("Business",
        p ? '<dl class="cx-facts"><div><dt>Sector</dt><dd>' + Cv(p.sector) + "</dd></div><div><dt>Industry</dt><dd>" + Cv(p.industry) +
        "</dd></div><div><dt>Exchange</dt><dd>" + Cv(p.exchange) + "</dd></div><div><dt>Currency</dt><dd>" + Cv(p.currency) +
        "</dd></div></dl>" + (p.description ? '<p class="cx-note">' + esc(String(p.description).slice(0, 500)) + "</p>" : "") + prov(r.body)
        : empty("Business", "Company profile is not supplied by a configured provider right now."));
    });
    API.get("history", { symbol: sym, range: "1Y", interval: "1d" }).then(function (r) {
      if (!E("cx-ov-perf")) return;
      var d = (r.body && r.body.data) || null, bars = (d && d.bars) || [];
      if (bars.length < 6) {
        E("cx-ov-perf").innerHTML = sec("Performance", empty("Performance", "Not enough verified history to compute returns."));
        return;
      }
      function ret(back) {
        var now = bars[bars.length - 1].c, old = bars[Math.max(0, bars.length - 1 - back)].c;
        if (now === null || old === null || !old) return null;
        return (now - old) / Math.abs(old) * 100;
      }
      var cells = [["1D", ret(1)], ["1W", ret(5)], ["1M", ret(21)], ["3M", ret(63)], ["6M", ret(126)], ["1Y", ret(252)]];
      E("cx-ov-perf").innerHTML = sec("Performance",
        '<div class="cx-facts">' + cells.map(function (c) {
          return "<div><dt>" + c[0] + "</dt><dd class='" + dir(c[1]) + "'>" + (c[1] === null ? "—" : F.fmtPct(c[1])) + "</dd></div>";
        }).join("") + "</div>" + prov(r.body));
    });
    API.get("technical", { symbol: sym }).then(function (r) {
      if (!E("cx-ov-tech")) return;
      var d = (r.body && r.body.data) || null;
      E("cx-ov-tech").innerHTML = sec("Technical snapshot",
        d ? '<div class="cx-facts"><div><dt>RSI 14</dt><dd>' + Num(d.rsi14, function (v) { return F.fmtNum(v); }) +
        "</dd></div><div><dt>SMA 50</dt><dd>" + Num(d.sma50, function (v) { return F.fmtNum(v); }) +
        "</dd></div><div><dt>SMA 200</dt><dd>" + Num(d.sma200, function (v) { return F.fmtNum(v); }) +
        "</dd></div><div><dt>Vol 20d</dt><dd>" + Num(d.volatility_20d_ann_pct, function (v) { return F.fmtNum(v) + "%"; }) +
        "</dd></div></div>" + prov(r.body)
        : empty("Technical snapshot", "Technical analytics need verified price history."));
    });
    API.get("news", { symbol: sym, limit: 5 }).then(function (r) {
      if (!E("cx-ov-news")) return;
      var items = (((r.body || {}).data) || {}).items || [];
      E("cx-ov-news").innerHTML = sec("Latest news",
        items.length ? items.slice(0, 5).map(newsRow).join("") + prov(r.body)
        : empty("Latest news", "No news items were returned for this security."));
    });
    /* Fundamental trend: reported revenue/PAT bars + deterministic read. */
    API.get("fundamentals", { symbol: sym, statement: "income", period: "annual" }).then(function (r) {
      var host = E("cx-main");
      if (!host) return;
      var reps = ((((r.body || {}).data) || {}).reports) || [];
      if (reps.length < 2) return;
      function series(keys) {
        return reps.slice(0, 4).reverse().map(function (rep) {
          for (var i = 0; i < keys.length; i++) {
            var n = Number(rep[keys[i]]);
            if (rep[keys[i]] !== "None" && !isNaN(n)) return n;
          }
          return null;
        });
      }
      var labels = reps.slice(0, 4).reverse().map(function (x) { return String(x.fiscalDateEnding || x.date || "").slice(0, 7); });
      var rev = series(["totalRevenue", "revenue", "revenues", "sales"]);
      var pat = series(["netIncome", "net_income", "netEarnings"]);
      var ok = function (s) { return s.some(function (v) { return v !== null; }); };
      if (!ok(rev) && !ok(pat)) return;
      var box = document.createElement("div");
      var I = window.FT_INTERP;
      var interp = "";
      var rr = rev.filter(function (v) { return v !== null; });
      if (rr.length >= 2 && rr[rr.length - 2]) {
        var yoy = (rr[rr.length - 1] - rr[rr.length - 2]) / Math.abs(rr[rr.length - 2]) * 100;
        interp = I.growth("Revenue", null, yoy, null, labels[labels.length - 1]);
      }
      box.innerHTML = sec("Fundamental trend",
        '<div class="an-grid"><div class="an-6"><div class="lbl">Revenue</div>' +
        (ok(rev) ? "<canvas class='chart' id='cx-ov-rev' style='height:150px' role='img' aria-label='Revenue trend'></canvas>" : "") +
        '</div><div class="an-6"><div class="lbl">Net profit</div>' +
        (ok(pat) ? "<canvas class='chart' id='cx-ov-pat' style='height:150px' role='img' aria-label='Net profit trend'></canvas>" : "") +
        "</div></div>" +
        (interp ? "<p class='interp'>" + esc(interp) + "</p>" : "") + prov(r.body));
      var news = E("cx-ov-news");
      news.parentNode.insertBefore(box, news);
      setTimeout(function () {
        if (ok(rev) && document.getElementById("cx-ov-rev"))
          window.FT_CHART.drawBars(document.getElementById("cx-ov-rev"), { labels: labels, series: [{ name: "Revenue", values: rev }] });
        if (ok(pat) && document.getElementById("cx-ov-pat"))
          window.FT_CHART.drawBars(document.getElementById("cx-ov-pat"), { labels: labels, series: [{ name: "PAT", values: pat }] });
      }, 60);
    }).catch(function () { /* overview works without statements */ });
    API.get("ratiosheet", { symbol: sym }).then(function (r) {
      if (!E("cx-ov-ratio")) return;
      var sheet = (r.body && r.body.data) || null, disp = (sheet && sheet.display) || {};
      var keys = ["roe", "roa", "roce", "net_margin", "debt_equity", "current_ratio"];
      var cells = keys.map(function (k) {
        var n = disp[k];
        if (!n || n.value === null || n.value === undefined) return ""; // omitted, never placeholder
        var v = n.unit === "%" ? Number(n.value).toFixed(1) + "%" : Number(n.value).toFixed(2) + "x";
        var b = n.kind === "CALCULATED" ? " <span class='cx-q cx-q-calc'>CALC</span>" : "";
        return "<div><dt>" + esc(n.label) + b + "</dt><dd>" + v + "</dd></div>";
      }).join("");
      if (!cells) { E("cx-ov-ratio").innerHTML = ""; return; }
      E("cx-ov-ratio").innerHTML = sec("Key ratios",
        '<dl class="cx-facts">' + cells + "</dl>" +
        '<div class="cx-note">REPORTED values come from the provider; CALC values from the terminal ratio engine. Detail in Valuation.</div>');
    }).catch(function () { if (E("cx-ov-ratio")) E("cx-ov-ratio").innerHTML = ""; });
  }
  function tOverview(sym, main) {
    if (secType(sym) === "INDEX") { perfIndex(sym, main); return; }
    perf(sym, main);
  }
  /* Index overview: breadth, heatmap, contributors, range, structure.
     No stock multiples, ever. */
  function perfIndex(sym, main) {
    var V = window.FT_VIZ, I = window.FT_INTERP;
    main.innerHTML = '<div id="cx-ix-perf">' + skel(3) + '</div><div id="cx-ix-range"></div>' +
      '<div id="cx-ix-breadth">' + skel(2) + '</div><div id="cx-ix-heat"></div>' +
      '<div id="cx-ix-mov"></div><div id="cx-ix-tech">' + skel(2) + "</div>" +
      '<div id="cx-ix-news">' + skel(3) + "</div>";
    API.get("history", { symbol: sym, range: "1Y", interval: "1d" }).then(function (r) {
      if (!E("cx-ix-perf")) return;
      var bars = (((r.body || {}).data) || {}).bars || [];
      var cl = bars.map(function (b) { return b.c; });
      function ret(back) {
        if (cl.length < back + 1) return null;
        var now = cl[cl.length - 1], old = cl[cl.length - 1 - back];
        if (now === null || old === null || !old) return null;
        return (now - old) / Math.abs(old) * 100;
      }
      var cells = [["1D", 1], ["1W", 5], ["1M", 21], ["3M", 63], ["6M", 126], ["1Y", 252]]
        .map(function (p) { return { label: p[1], value: ret(p[0]) === null ? null : F.fmtPct(ret(p[0])) }; })
        .filter(function (c) { return c.value !== null; });
      var note = I.trend("The index", cl, "the trailing year of verified closes");
      E("cx-ix-perf").innerHTML = sec("Performance",
        (cells.length ? '<dl class="cx-facts">' + cells.map(function (c) {
          return "<div><dt>" + c.label + "</dt><dd>" + c.value + "</dd></div>";
        }).join("") + "</dl>" : "") +
        (note ? "<p class='interp'>" + esc(note) + "</p>" : "") + prov(r.body));
    });
    API.get("quote", { symbol: sym }).then(function (r) {
      if (!E("cx-ix-range")) return;
      var qq = (r.body && r.body.data) || {};
      var hi = qq.fifty_two_week_high, lo = qq.fifty_two_week_low, px = qq.price;
      if (hi === null || hi === undefined || lo === null || lo === undefined || !hi || hi === lo) return;
      var pos = px !== null && px !== undefined ? Math.round((px - lo) / (hi - lo) * 100) : null;
      E("cx-ix-range").innerHTML = sec("52-week range",
        '<div class="bar-row"><span>Low ' + F.fmtNum(lo) + "</span>" +
        '<span class="tr"><span class="fl" style="display:block;width:' + (pos === null ? 0 : pos) +
        '%;background:var(--acc)"></span></span><b>High ' + F.fmtNum(hi) + "</b></div>" +
        (pos !== null ? "<p class='interp'>Trading " + pos + "% up the 52-week range.</p>" : "") + prov(r.body));
    });
    API.get("market-overview").then(function (r) {
      if (!E("cx-ix-breadth")) return;
      var items = ((r.body || {}).items) || [];
      var eq = items.filter(function (i) {
        return i.quote && i.quote.price !== null && i.quote.price !== undefined &&
          i.symbol.charAt(0) !== "^" && !/NIFTY_FIN/.test(i.symbol);
      });
      var adv = eq.filter(function (i) { return (i.quote.change_pct || 0) > 0; }).length;
      var dec = eq.filter(function (i) { return (i.quote.change_pct || 0) < 0; }).length;
      var unch = eq.length - adv - dec;
      var note = I.breadth(adv, dec, unch, "the tracked universe");
      E("cx-ix-breadth").innerHTML = sec("Market breadth",
        V.bars([
          { label: "Advancing", value: adv, display: String(adv) },
          { label: "Declining", value: dec, display: String(dec) },
          { label: "Unchanged", value: unch, display: String(unch) },
        ]) + (note ? "<p class='interp'>" + esc(note) + " Tracked universe — a participation proxy, not full market breadth.</p>" : ""));
      var heat = E("cx-ix-heat");
      if (heat) {
        var sectors = [["^CNXIT", "IT"], ["^CNXAUTO", "Auto"], ["^CNXFMCG", "FMCG"],
          ["^CNXPHARMA", "Pharma"], ["^NSEBANK", "Banking"]];
        var by = {};
        items.forEach(function (i) { by[i.symbol] = i; });
        heat.innerHTML = sec("Sector heatmap",
          V.heatmap(sectors.map(function (p) {
            var v = (by[p[0]] || {}).quote || {};
            return { label: p[1], value: v.change_pct, sub: "NSE sector index" };
          }), { fmt: function (v) { return F.fmtPct(v); } }) +
          "<p class='interp'>Equal-size tiles show performance only — no weight data is available.</p>");
      }
      var mv = E("cx-ix-mov");
      if (mv) {
        function rows(list, title) {
          if (!list.length) return "";
          return "<h3 style='margin:10px 0 4px;font-size:13px'>" + title + "</h3><ul class='ranklist'>" +
            list.slice(0, 5).map(function (i) {
              return "<li><span class='rk'>·</span><span><a href='#/company/" + esc(i.symbol) + "'>" +
                esc(i.quote.name || i.symbol) + "</a></span><b class='" + F.dirClass(i.quote.change_pct) + "'>" +
                F.fmtPct(i.quote.change_pct) + "</b></li>";
            }).join("") + "</ul>";
        }
        var g = eq.slice().sort(function (a, b) { return (b.quote.change_pct || 0) - (a.quote.change_pct || 0); });
        var l = eq.slice().sort(function (a, b) { return (a.quote.change_pct || 0) - (b.quote.change_pct || 0); });
        var html = rows(g.filter(function (i) { return (i.quote.change_pct || 0) > 0; }), "Top contributors (tracked)") +
          rows(l.filter(function (i) { return (i.quote.change_pct || 0) < 0; }), "Top detractors (tracked)");
        mv.innerHTML = html ? sec("Contributors", html +
          "<p class='interp'>Ranked from the tracked universe — a proxy, not official index attribution.</p>") : "";
      }
    });
    API.get("technical", { symbol: sym }).then(function (r) {
      if (!E("cx-ix-tech")) return;
      var dd = (r.body && r.body.data) || null;
      if (!dd) return;
      E("cx-ix-tech").innerHTML = sec("Technical structure",
        '<dl class="cx-facts">' +
        (dd.rsi14 !== null && dd.rsi14 !== undefined ? "<div><dt>RSI 14</dt><dd>" + F.fmtNum(dd.rsi14) + "</dd></div>" : "") +
        (dd.sma50 !== null && dd.sma50 !== undefined ? "<div><dt>SMA 50</dt><dd>" + F.fmtNum(dd.sma50) + "</dd></div>" : "") +
        (dd.sma200 !== null && dd.sma200 !== undefined ? "<div><dt>SMA 200</dt><dd>" + F.fmtNum(dd.sma200) + "</dd></div>" : "") +
        "</dl>" +
        (I.rsi(dd.rsi14) ? "<p class='interp'>" + esc(I.rsi(dd.rsi14)) + "</p>" : "") + prov(r.body));
    });
    API.get("news", { symbol: sym, limit: 5 }).then(function (r) {
      if (!E("cx-ix-news")) return;
      var items = (((r.body || {}).data) || {}).items || [];
      if (!items.length) return;
      E("cx-ix-news").innerHTML = sec("Latest news", items.slice(0, 5).map(newsRow).join("") + prov(r.body));
    });
  }
  /* statement table shared by financials */
  /* Priority rows first, full statement expandable, one consistent unit. */
  var STMT_PRIORITY = [
    ["revenue", ["totalrevenue", "revenue", "revenues", "sales"]],
    ["EBITDA", ["ebitda"]],
    ["EBIT", ["ebit", "operatingincome", "operatingprofit"]],
    ["PBT", ["incomebeforetax", "profitbeforetax", "pbt"]],
    ["PAT", ["netincome", "netearnings", "pat", "netprofit"]],
    ["EPS", ["dilutedEPS", "eps"]],
  ];
  function stmtKey(report, aliases) {
    var keys = Object.keys(report || {});
    for (var i = 0; i < aliases.length; i++) {
      for (var j = 0; j < keys.length; j++) {
        if (keys[j].toLowerCase().replace(/[^a-z]/g, "") === aliases[i]) return keys[j];
      }
    }
    return null;
  }
  function stmtTable(title, env) {
    if (!env || !env.data || !((env.data.reports || []).length)) {
      return sec(title, empty(title, "No statement data is supplied by a configured provider right now."));
    }
    var d = env.data, reps = d.reports.slice(0, 4), ccy = d.currency || "";
    var mag = 0;
    reps.forEach(function (r) {
      Object.keys(r).forEach(function (k) {
        var n = Number(r[k]);
        if (!isNaN(n) && Math.abs(n) > mag) mag = Math.abs(n);
      });
    });
    var unit = F.stmtUnit(ccy, mag);
    function rowCells(k) {
      var vals = reps.map(function (r) {
        if (k === null) return null;
        var v = r[k];
        var n = Number(v);
        return (v === "None" || isNaN(n)) ? null : n;
      });
      var yoy = (vals[0] !== null && vals[1] !== null && vals[1] !== 0) ? (vals[0] - vals[1]) / Math.abs(vals[1]) * 100 : null;
      return { vals: vals, yoy: yoy };
    }
    function prow(label, k, ix, bold) {
      var rc = rowCells(k);
      return '<tr' + (ix % 2 ? ' class="zeb"' : "") + '><td' + (bold ? "><b>" + esc(label) + "</b>" : ">" + esc(label)) + "</td>" +
        rc.vals.map(function (v) { return '<td class="num">' + (v === null ? "" : F.fmtStmt(v, ccy)) + "</td>"; }).join("") +
        '<td class="num ' + dir(rc.yoy) + '">' + (rc.yoy === null ? "" : F.fmtPct(rc.yoy)) + "</td></tr>";
    }
    var head = '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Particulars (' + esc(unit) + ')</th>' +
      reps.map(function (r) { return '<th scope="col" class="num">' + esc(r.fiscalDateEnding || r.date || "") + "</th>"; }).join("") +
        '<th scope="col" class="num">YoY</th></tr></thead><tbody>';
    var used = {}, pri = "";
    STMT_PRIORITY.forEach(function (p, ix) {
      var k = stmtKey(reps[0], p[1].map(function (a) { return a.toLowerCase(); }));
      if (k) { used[k] = 1; pri += prow(p[0], k, ix, true); }
    });
    var rest = Object.keys(reps[0]).filter(function (k) {
      return !used[k] && ["fiscalDateEnding", "reportedCurrency", "date"].indexOf(k) < 0;
    }).slice(0, 20);
    var restHtml = rest.map(function (k, ix) { return prow(k, k, ix, false); }).join("");
    var h = head + pri + "</tbody></table></div>";
    if (restHtml) {
      h += "<details style='margin-top:8px'><summary class='cx-note'>All line items (" + rest.length + ")</summary>" +
        '<div class="cx-scroll" style="margin-top:6px"><table class="cx-t"><thead><tr><th scope="col">Particulars (' + esc(unit) + ')</th>' +
      reps.map(function (r) { return '<th scope="col" class="num">' + esc(r.fiscalDateEnding || r.date || "") + "</th>"; }).join("") +
        '<th scope="col" class="num">YoY</th></tr></thead><tbody>' + restHtml + "</tbody></table></div></details>";
    }
    /* growth chart for income statements */
    var chartId = "stmt-chart-" + Math.floor(Math.random() * 1e9);
    if (title === "Income statement") {
      h += "<div style='margin-top:10px'><canvas class='chart' id='" + chartId + "' style='height:200px' role='img' aria-label='Revenue, EBITDA and PAT chart'></canvas>" +
        "<div class='cx-prov'>Actual reported periods only — never interpolated.</div></div>";
    }
    var out = sec(title, h +
      '<div class="cx-prov">' + (ccy ? "Currency <b>" + esc(ccy) + "</b> · " : "") + 'figures in <b>' + esc(unit) + "</b> · YoY shown only when mathematically valid.</div>" + prov(env));
    if (title === "Income statement") {
      setTimeout(function () {
        var cv = document.getElementById(chartId);
        if (!cv || !window.FT_CHART) return;
        function series(aliases) {
          var k = stmtKey(reps[reps.length - 1], aliases) || stmtKey(reps[0], aliases);
          if (!k) return null;
          return reps.slice().reverse().map(function (r) {
            var n = Number(r[k]);
            return (r[k] === "None" || isNaN(n)) ? null : n;
          });
        }
        var labels = reps.slice().reverse().map(function (r) { return String(r.fiscalDateEnding || r.date || "").slice(0, 7); });
        var sers = [
          { name: "Revenue", values: series(["totalrevenue", "revenue", "revenues", "sales"]) },
          { name: "EBITDA", values: series(["ebitda"]) },
          { name: "PAT", values: series(["netincome", "netearnings", "pat", "netprofit"]) },
        ].filter(function (s) { return s.values && s.values.some(function (v) { return v !== null; }); });
        if (sers.length) {
          window.FT_CHART.drawBars(cv, { labels: labels, series: sers });
          var I = window.FT_INTERP, rev = sers[0].values.filter(function (v) { return v !== null; });
          var interp = "";
          if (rev.length >= 3 && rev[0] > 0 && rev[rev.length - 1] > 0) {
            var cagr = (Math.pow(rev[rev.length - 1] / rev[0], 1 / (rev.length - 1)) - 1) * 100;
            interp = I.growth("Revenue", cagr, null, labels[0] + "–" + labels[labels.length - 1], null);
          } else if (rev.length >= 2 && rev[rev.length - 2]) {
            interp = I.growth("Revenue", null, (rev[rev.length - 1] - rev[rev.length - 2]) / Math.abs(rev[rev.length - 2]) * 100, null, labels[labels.length - 1]);
          }
          if (interp) {
            var p = document.createElement("p");
            p.className = "interp";
            p.textContent = interp;
            cv.parentNode.appendChild(p);
          }
        }
      }, 50);
    }
    return out;
  }
  function tFinancials(sym, main) {
    main.innerHTML = sec("Financial statements",
      '<div class="cx-toolbar"><div class="grp" role="group" aria-label="Statement">' +
      ["income", "balance", "cashflow"].map(function (s, i) {
        return '<button class="cx-btn2' + (i === 0 ? " on" : "") + '" data-st="' + s + '">' + (s === "income" ? "Income" : s === "balance" ? "Balance sheet" : "Cash flow") + "</button>";
      }).join("") + '</div><div class="grp" role="group" aria-label="Period">' +
      ["annual", "quarterly"].map(function (p, i) {
        return '<button class="cx-btn2' + (i === 0 ? " on" : "") + '" data-pd="' + p + '">' + (p === "annual" ? "Annual" : "Quarterly") + "</button>";
      }).join("") + '</div><span class="cx-legend">Reported only — never synthesised.</span></div><div id="cx-fin">' + skel(5) + "</div>");
    var st = "income", pd = "annual";
    function go() {
      E("cx-fin").innerHTML = skel(5);
      API.get("fundamentals", { symbol: sym, statement: st, period: pd }).then(function (r) {
        if (E("cx-fin")) E("cx-fin").innerHTML = stmtTable(st === "income" ? "Income statement" : st === "balance" ? "Balance sheet" : "Cash flow", r.body).replace(/^<section[^>]*><h2>.*?<\/h2>/, "").replace(/<\/section>$/, "");
      });
    }
    Array.prototype.forEach.call(main.querySelectorAll("[data-st]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(main.querySelectorAll("[data-st]"), function (x) { x.classList.remove("on"); });
        b.classList.add("on"); st = b.getAttribute("data-st"); go();
      };
    });
    Array.prototype.forEach.call(main.querySelectorAll("[data-pd]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(main.querySelectorAll("[data-pd]"), function (x) { x.classList.remove("on"); });
        b.classList.add("on"); pd = b.getAttribute("data-pd"); go();
      };
    });
    go();
  }
  function tValuation(sym, main) {
    main.innerHTML = '<div id="cx-val">' + skel(5) + "</div>";
    Promise.all([API.get("ratios", { symbol: sym }), API.get("quote", { symbol: sym })]).then(function (rs) {
      if (!E("cx-val")) return;
      var env = rs[0].body || {}, r = env.data || null, q = (rs[1].body && rs[1].body.data) || {};
      if (!r) {
        E("cx-val").innerHTML = sec("Valuation", empty("Valuation", "Valuation multiples are not supplied by a configured provider right now.") + prov(env));
        return;
      }
      function cell(v, suffix) {
        return (v === undefined || v === null || /^(none|-|n\/a)$/i.test(String(v))) ? "—" : esc(String(v)) + (suffix || "");
      }
      function numx(v) { return (v === null || v === undefined || isNaN(Number(v))) ? null : Number(v).toFixed(1) + "x"; }
      var grid = [["Market cap", r.MarketCapitalization && r.MarketCapitalization !== "None" ? F.fmtIN(Number(r.MarketCapitalization), q.currency) : null],
        ["P/E", numx(r.PERatio)], ["Forward P/E", r.ForwardPE && r.ForwardPE !== "None" ? cell(r.ForwardPE) : null],
        ["P/B", numx(r.PriceToBookRatio)], ["EV/EBITDA", numx(r.EVToEBITDA)],
        ["EPS", r.EPS && r.EPS !== "None" && !isNaN(Number(r.EPS)) ? F.fmtNum(Number(r.EPS)) : null],
        ["Book value", r.BookValue && r.BookValue !== "None" && !isNaN(Number(r.BookValue)) ? F.fmtNum(Number(r.BookValue)) : null],
        ["Dividend yield", r.DividendYield && r.DividendYield !== "None" ? r.DividendYield + "%" : null]];
      var h = sec("Valuation",
        '<div class="cx-facts">' + grid.filter(function (g) { return g[1] !== null; }).map(function (g) {
          return "<div><dt>" + g[0] + "</dt><dd>" + g[1] + "</dd></div>";
        }).join("") + "</div>" + prov(env) +
        '<p class="cx-note">Peer comparison lives in the Compare workspace (no automatic peer universe, no rankings). ' +
        "<button class='cx-btn2' id='cx-peer'>Compare " + esc(sym) + " side-by-side →</button></p>");
      E("cx-val").innerHTML = h;
      var peerBtn = E("cx-peer");
      if (peerBtn) peerBtn.onclick = function () {
        try { sessionStorage.setItem("ft-cmp", sym); } catch (e) { /* ignore */ }
        location.hash = "#/compare";
      };
      var rec = env.reconciliation;
      if (rec && rec.comparisons && rec.comparisons.length) {
        h += '<section class="cx-sec"><h2>Cross-check</h2><details><summary class="cx-note">Primary vs other sources (' +
          rec.comparisons.length + " fields)</summary>" + '<div class="cx-scroll" style="margin-top:8px"><table class="cx-t"><thead><tr><th scope="col">Metric</th><th scope="col">Primary</th><th scope="col">Other source</th></tr></thead><tbody>' +
          rec.comparisons.map(function (c) {
            var other = (c.cross_check || []).map(function (o) { var v = Cv(o.value); return v ? esc(o.source) + ": " + v : ""; }).filter(Boolean).join("; ");
            return "<tr><td>" + esc(c.field) + "</td><td class='num'>" + Cv(c.primary && c.primary.value) + "</td><td>" + other + "</td></tr>";
          }).join("") + "</tbody></table></div></details></section>";
      }
      E("cx-val").innerHTML = h;
      /* Canonical calculated ratios (single engine, formula inspectors). */
      API.get("ratiosheet", { symbol: sym }).then(function (rs2) {
        if (!E("cx-val")) return;
        var sheet = (rs2.body && rs2.body.data) || null;
        if (!sheet || !sheet.display) return;
        var order = ["roe", "roa", "roce", "gross_margin", "op_margin", "net_margin",
          "current_ratio", "quick_ratio", "debt_equity", "net_debt_ebitda",
          "interest_coverage", "asset_turnover", "revenue_cagr", "pat_cagr",
          "fcf_margin", "cfo_pat", "payout_ratio"];
        var rows = order.filter(function (k) { return sheet.display[k]; }).map(function (k) {
          return sheet.display[k];
        });
        if (!rows.length) return;
        function disp(n) {
          if (n.unit === "%") return Number(n.value).toFixed(1) + "%";
          if (n.unit === "x") return Number(n.value).toFixed(2) + "x";
          return esc(String(n.value));
        }
        var el = document.createElement("div");
        el.innerHTML = sec("Calculated ratios",
          '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Ratio</th><th scope="col" class="num">Value</th><th scope="col">Quality</th><th scope="col">Detail</th></tr></thead><tbody>' +
          rows.map(function (n, ix) {
            return "<tr><td>" + esc(n.label) + (n.variant ? " <span class='cx-note'>(" + esc(n.variant) + ")</span>" : "") +
              "</td><td class='num'>" + disp(n) + "</td><td><span class='cx-q cx-q-calc'>CALC</span></td>" +
              "<td><button class='cx-btn2' data-calc='" + ix + "'>Formula</button></td></tr>";
          }).join("") + "</tbody></table></div>" +
          '<div id="cx-calc-insp"></div><div class="cx-prov">Single canonical engine · click Formula for inputs, period, source, timestamp.</div>');
        E("cx-val").appendChild(el);
        Array.prototype.forEach.call(el.querySelectorAll("[data-calc]"), function (b) {
          b.onclick = function () {
            var n = rows[Number(b.getAttribute("data-calc"))];
            E("cx-calc-insp").innerHTML = '<div class="cx-inspector"><b>' + esc(n.label) + " " + disp(n) +
              "</b><div class='cx-kv'><span class='k'>Formula</span><span class='w'>" + esc(n.formula || "") + "</span></div>" +
              (n.inputs || []).map(function (i) {
                return "<div class='cx-kv'><span class='k'>" + esc(i.label || "") + (i.period ? " (" + esc(i.period) + ")" : "") +
                  "</span><span class='w'>" + esc(i.value === null || i.value === undefined ? "" : String(i.value)) + " · " + esc(i.source || "") + "</span></div>";
              }).join("") + '<div class="cx-note">Calculated ' + esc(n.calculated_at || "") + "</div></div>";
          };
        });
      }).catch(function () { /* reported grid already shown */ });
    }).catch(function () { if (E("cx-val")) E("cx-val").innerHTML = sec("Valuation", err()); });
  }
  function estCell(v) {
    if (v === undefined || v === null) return "";
    if (typeof v === "string" && /^(none|null|undefined|nan|-|n\/a)$/i.test(v.trim())) return "";
    return esc(String(v));
  }
  function tEstimates(sym, main) {
    main.innerHTML = '<div id="cx-est">' + skel(4) + "</div>";
    API.get("estimates", { symbol: sym }).then(function (r) {
      if (!E("cx-est")) return;
      var d = (r.body && r.body.data) || null;
      if (!d || (!(d.annual || []).length && !(d.quarterly || []).length && !d.analyst_ratings)) {
        E("cx-est").innerHTML = sec("Estimates", empty("Estimates", "No verified estimates are supplied by a configured provider right now.") + prov(r.body));
        return;
      }
      function tbl(list) {
        return '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Period</th><th scope="col" class="num">EPS est</th><th scope="col" class="num">Revenue est</th><th scope="col" class="num">Analysts</th></tr></thead><tbody>' +
          list.map(function (x) {
            return "<tr><td>" + estCell(x.fiscalDateEnding || x.horizon) + "</td><td class='num'>" +
              estCell(x.epsAvgEstimate !== undefined ? x.epsAvgEstimate : x.eps) + "</td><td class='num'>" +
              estCell(x.revenueAvgEstimate !== undefined ? x.revenueAvgEstimate : x.revenue) + "</td><td class='num'>" +
              estCell(x.numAnalysts) + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      }
      var h = sec("Estimates", '<p class="cx-note">Reported forecasts only — actuals and estimates are never mixed.</p>' + prov(r.body));
      var ar = d.analyst_ratings;
      if (ar && (ar.distribution || []).length) {
        h += sec("Analyst ratings", '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Rating</th><th scope="col" class="num">Analysts</th></tr></thead><tbody>' +
          ar.distribution.map(function (x) {
            return "<tr><td>" + estCell(x.rating) + "</td><td class='num'>" + estCell(x.analysts) + "</td></tr>";
          }).join("") + "</tbody></table></div>");
      }
      h += sec("Annual forecasts", (d.annual || []).length ? tbl(d.annual) : empty("Annual forecasts", "No annual estimate rows reported."));
      h += sec("Quarterly forecasts", (d.quarterly || []).length ? tbl(d.quarterly) : empty("Quarterly forecasts", "No quarterly estimate rows reported."));
      E("cx-est").innerHTML = h;
    }).catch(function () { if (E("cx-est")) E("cx-est").innerHTML = sec("Estimates", err()); });
  }
  function tEarnings(sym, main) {
    main.innerHTML = '<div id="cx-earn">' + skel(4) + "</div>";
    API.get("earnings", { symbol: sym }).then(function (r) {
      if (!E("cx-earn")) return;
      var d = (r.body && r.body.data) || null;
      if (!d || (!(d.annual || []).length && !(d.quarterly || []).length)) {
        E("cx-earn").innerHTML = sec("Earnings", empty("Earnings", "No earnings rows are supplied by a configured provider right now.") + prov(r.body));
        return;
      }
      function tbl(list) {
        return '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Period</th><th scope="col" class="num">Reported EPS</th><th scope="col" class="num">Est. EPS</th><th scope="col" class="num">Surprise</th></tr></thead><tbody>' +
          list.map(function (x) {
            var sv = x.surprise !== undefined ? x.surprise : x.surprisePercentage;
            var cls = (typeof sv === "number") ? dir(sv) : "";
            return "<tr><td>" + estCell(x.fiscalDateEnding || x.reportedDate) + "</td><td class='num'>" + estCell(x.reportedEPS) +
              "</td><td class='num'>" + estCell(x.estimatedEPS) + "</td><td class='num " + cls + "'>" +
              (sv === undefined || sv === null || sv === "" ? "" : typeof sv === "number" ? F.fmtPct(sv) : estCell(sv)) + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      }
      E("cx-earn").innerHTML = sec("Earnings", prov(r.body)) +
        sec("Annual", (d.annual || []).length ? tbl(d.annual) : empty("Annual", "No annual earnings rows.")) +
        sec("Quarterly", (d.quarterly || []).length ? tbl(d.quarterly) : empty("Quarterly", "No quarterly earnings rows."));
    }).catch(function () { if (E("cx-earn")) E("cx-earn").innerHTML = sec("Earnings", err()); });
  }
  function newsRow(n) {
    var title = esc(n.title || "Untitled");
    var sum = n.summary ? esc(String(n.summary).replace(/\s+/g, " ").slice(0, 180)) : "";
    var link = n.url ? "<a href='" + esc(n.url) + "' target='_blank' rel='noopener'>Read article →</a>" : "";
    return '<article class="news-item"><b>' + title + "</b>" +
      (sum ? "<p class='sum'>" + sum + "…</p>" : "") +
      "<div class='meta'><span class='srcbadge'>" + esc(n.source || "—") + "</span> · " +
      esc(F.fmtTimeHM(n.published_at)) +
      (n.category ? " · " + esc(n.category) : "") +
      (link ? " · " + link : "") + "</div></article>";
  }
  function tNews(sym, main) {
    main.innerHTML = '<div id="cx-news">' + skel(4) + "</div>";
    API.get("news", { symbol: sym, limit: 20 }).then(function (r) {
      if (!E("cx-news")) return;
      var items = ((r.body && r.body.data) || {}).items || [];
      if (!items.length) {
        E("cx-news").innerHTML = sec("News", empty("News", "No news items were returned for this security.") + prov(r.body));
        return;
      }
      var cats = ["All", "Company", "Results", "Markets", "Corporate", "Regulatory"];
      items.forEach(function (it) {
        var t = ((it.title || "") + " " + (it.summary || "")).toLowerCase();
        it.category = /result|earning|profit|revenue|quarter|guidance/.test(t) ? "Results" :
          /dividend|split|bonus|merger|acquis|buyback|board meet/.test(t) ? "Corporate" :
          /sebi|regulat|approv|filing|compliance|penalty/.test(t) ? "Regulatory" :
          /market|sensex|nifty|index|sector|economy|inflation/.test(t) ? "Markets" : "Company";
      });
      E("cx-news").innerHTML = sec("News",
        '<div class="cx-fchips" role="group" aria-label="News filter">' + cats.map(function (c, i) {
          return '<button data-c="' + c + '"' + (i === 0 ? ' class="on"' : "") + ">" + c + "</button>";
        }).join("") + '</div><div id="cx-newslist"></div>' + prov(r.body));
      function paint(sel) {
        var list = sel === "All" ? items : items.filter(function (it) { return it.category === sel; });
        E("cx-newslist").innerHTML = list.length ? list.map(newsRow).join("") : '<div class="cx-note">No ' + esc(sel) + " items in this batch.</div>";
        Array.prototype.forEach.call(E("cx-news").querySelectorAll("[data-c]"), function (b) {
          b.classList.toggle("on", b.getAttribute("data-c") === sel);
          b.onclick = function () { paint(b.getAttribute("data-c")); };
        });
      }
      paint("All");
    }).catch(function () { if (E("cx-news")) E("cx-news").innerHTML = sec("News", err()); });
  }
  function tActions(sym, main) {
    main.innerHTML = '<div id="cx-act">' + skel(3) + "</div>";
    API.get("actions", { symbol: sym }).then(function (r) {
      if (!E("cx-act")) return;
      var d = (r.body && r.body.data) || null;
      if (!d || (!((d.dividends || []).length) && !((d.splits || []).length))) {
        E("cx-act").innerHTML = sec("Corporate actions", empty("Corporate actions", "No corporate actions were reported by configured sources.") + prov(r.body));
        return;
      }
      var evs = (d.dividends || []).map(function (x) {
        return { date: x.date, t: "Dividend", v: F.fmtNum(x.amount, 4) + " " + (x.currency || ""), s: x.source };
      }).concat((d.splits || []).map(function (x) {
        return { date: x.date, t: "Split", v: x.numerator + ":" + x.denominator, s: x.source };
      })).sort(function (a, b) { return String(b.date) > String(a.date) ? 1 : -1; });
      E("cx-act").innerHTML = sec("Corporate actions",
        evs.slice(0, 40).map(function (e) {
          return '<div class="cx-ev"><span class="dt">' + esc(String(e.date).slice(0, 10)) + '</span><span class="tp">' + esc(e.t) +
            "</span><span>" + esc(e.v) + "</span><span class='src'>" + esc(F.srcName(e.s)) + "</span></div>";
        }).join("") + prov(r.body));
    }).catch(function () { if (E("cx-act")) E("cx-act").innerHTML = sec("Corporate actions", err()); });
  }
  function tHoldings(sym, main) {
    main.innerHTML = '<div id="cx-own">' + skel(3) + "</div>";
    API.get("holdings", { symbol: sym }).then(function (r) {
      if (!E("cx-own")) return;
      var hd = (r.body && r.body.data) || null, owns = (hd && hd.ownership) || [];
      if (!owns.length) {
        E("cx-own").innerHTML = sec("Ownership", empty("Ownership", "No ownership split is supplied by a configured provider right now.") + prov(r.body));
        return;
      }
      var total = owns.reduce(function (s, o) { return s + (Number(o.percentage) || 0); }, 0);
      E("cx-own").innerHTML = sec("Ownership",
        '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Holder class</th><th scope="col" class="num">Holding</th><th scope="col">As of</th></tr></thead><tbody>' +
        owns.map(function (o, ix) {
          var pct = (o.percentage === null || o.percentage === undefined) ? "" : Number(o.percentage).toFixed(2) + "%";
          return "<tr" + (ix % 2 ? ' class="zeb"' : "") + "><td>" + Cv(o.category) + "</td><td class='num'>" + pct +
            "</td><td>" + Cv(o.holding_date) + "</td></tr>";
        }).join("") + "</tbody></table></div>" +
        (total ? '<div class="cx-note">Total ' + total.toFixed(1) + "% across reported classes" +
          (owns[0] && owns[0].holding_date ? " · as of <b>" + esc(owns[0].holding_date) + "</b>" : "") + "</div>" : "") + prov(r.body));
    }).catch(function () { if (E("cx-own")) E("cx-own").innerHTML = sec("Ownership", err()); });
  }
  function tCharts(sym, main) {
    main.innerHTML = sec("Price",
      '<div class="cx-toolbar"><div class="grp" role="group" aria-label="Range" id="cx-rg">' +
      ["1M", "3M", "6M", "1Y", "3Y", "5Y"].map(function (x, i) {
        return '<button class="cx-btn2' + (x === "1Y" ? " on" : "") + '" data-r="' + x + '">' + x + "</button>";
      }).join("") + '</div><div class="grp" role="group" aria-label="Overlays" id="cx-sma">' +
      [[20, 1], [50, 1], [200, 0]].map(function (p) {
        return "<label class='cx-legend'><input type='checkbox' data-sma='" + p[0] + "'" + (p[1] ? " checked" : "") + "> SMA" + p[0] + "</label>";
      }).join("") + "</div></div>" +
      '<div class="chart-box"><canvas class="chart" id="cx-c" role="img" aria-label="Price history chart"></canvas><div class="chart-tip"></div></div>' +
      '<div class="cx-prov" id="cx-cmeta"></div><div id="cx-cerr"></div>');
    function smas() {
      var out = [];
      Array.prototype.forEach.call(main.querySelectorAll("[data-sma]"), function (c) { if (c.checked) out.push(Number(c.getAttribute("data-sma"))); });
      return out.length ? out : [20];
    }
    function draw(range) {
      E("cx-cerr").innerHTML = "";
      API.get("history", { symbol: sym, range: range, interval: "1d" }).then(function (r) {
        if (!E("cx-c")) return;
        var d = (r.body && r.body.data) || null;
        if (!d || !(d.bars || []).length) {
          E("cx-cerr").innerHTML = empty("Chart", "No verified history for this range.");
          return;
        }
        window.FT_CHART.drawPriceChart(E("cx-c"), d.bars, { sma: smas() });
        E("cx-cmeta").innerHTML = "Source <b>" + esc(F.srcName(r.body.source)) + "</b> · " + esc(d.bars.length) +
          " bars · as of <b>" + esc(day(r.body.as_of)) + "</b>";
      }).catch(function () { if (E("cx-cerr")) E("cx-cerr").innerHTML = err(); });
    }
    var cur = "1Y";
    draw(cur);
    Array.prototype.forEach.call(main.querySelectorAll("[data-r]"), function (b) {
      b.onclick = function () {
        Array.prototype.forEach.call(main.querySelectorAll("[data-r]"), function (x) { x.classList.remove("on"); });
        b.classList.add("on"); cur = b.getAttribute("data-r"); draw(cur);
      };
    });
    Array.prototype.forEach.call(main.querySelectorAll("[data-sma]"), function (c) { c.onchange = function () { draw(cur); }; });
  }
  function tTechnicals(sym, main) {
    main.innerHTML = '<div id="cx-tq">' + skel(5) + "</div>";
    Promise.all([
      API.get("analytics", { symbol: sym }),
      API.get("quote", { symbol: sym }),
    ]).then(function (rs) {
      var r = rs[0];
      var lastPx = (((rs[1] || {}).body || {}).data || {}).price;
      if (!E("cx-tq")) return;
      var d = (r.body && r.body.data) || null;
      if (!d) {
        E("cx-tq").innerHTML = sec("Technicals", empty("Technicals", "Technical analytics need verified price history.") + prov(r.body));
        return;
      }
      var ph = d.phase || {}, rs = d.relative_strength || {}, vcp = d.vcp || {},
        bo = d.breakout || {}, tt = d.trend_template || {}, rr = d.risk_reward || {};
      function fact(l, v, tip) {
        if (v === null || v === undefined || v === "—" || v === "") return ""; // omitted, never placeholder
        return "<div title='" + esc(tip || "") + "'><dt>" + l + "</dt><dd>" + v + "</dd></div>";
      }
      var snap = d.snapshot || {};
      /* Deterministic interpretation — only from calculated values. */
      var interp = [];
      var s50 = snap.sma50, s200 = snap.sma200, last = lastPx;
      if (last !== null && last !== undefined && !isNaN(Number(last)) &&
          s50 !== null && s50 !== undefined && s200 !== null && s200 !== undefined) {
        interp.push(last > s50 && last > s200 ? "Price is above both the 50-day and 200-day averages."
          : last < s50 && last < s200 ? "Price is below both the 50-day and 200-day averages."
          : "Price sits between the 50-day and 200-day averages.");
      }
      if (snap.rsi14 !== null && snap.rsi14 !== undefined) {
        interp.push("RSI " + F.fmtNum(snap.rsi14) +
          (snap.rsi14 > 70 ? " — overheated zone." : snap.rsi14 < 30 ? " — oversold zone." : " — neutral zone."));
      }
      if (rs.rs_pp !== null && rs.rs_pp !== undefined) {
        interp.push("Relative strength " + F.fmtPct(rs.rs_pp) + " vs " + (d.benchmark || "benchmark") + ".");
      }
      var trend = sec("Trend",
        '<dl class="cx-facts">' +
        fact("Weinstein phase", Cv(ph.phase), "Position of price relative to its long moving average.") +
        fact("Trend template", (tt.passed === undefined ? "—" : tt.passed + " / " + tt.total), "Number of bullish trend conditions met.") +
        fact("SMA 50", Num(snap.sma50, function (v) { return F.fmtNum(v); }), "Average close, last 50 sessions.") +
        fact("SMA 200", Num(snap.sma200, function (v) { return F.fmtNum(v); }), "Average close, last 200 sessions.") +
        "</dl>" + (interp.length ? "<p class='interp'>" + esc(interp.join(" ")) + "</p>" : ""));
      var rel = sec("Relative strength",
        '<dl class="cx-facts">' +
        fact("Vs " + esc(d.benchmark || "benchmark"), rs.rs_pp === null || rs.rs_pp === undefined ? "—" : F.fmtPct(rs.rs_pp), "Outperformance in percentage points over the lookback.") +
        fact("Verdict", Cv(rs.verdict), "Analyst-style reading of relative strength.") +
        fact("Volatility 20d", Num((d.snapshot || {}).volatility_20d_ann_pct, function (v) { return F.fmtNum(v) + "%"; }), "Annualised volatility of daily returns.") +
        "</dl>");
      var patt = sec("Pattern",
        '<dl class="cx-facts">' +
        fact("VCP", vcp.detected === null || vcp.detected === undefined ? "—" : vcp.detected ? "Detected" : "Not detected", "Volatility-contraction screen.") +
        fact("Breakout", Cv(bo.status), "Price position versus the recent reference level.") +
        fact("Volume confirmation", bo.volume_confirmed === undefined ? "—" : bo.volume_confirmed ? "Yes" : "No", "Whether volume supported the move.") +
        "</dl>");
      var risk = (rr.status === "OK")
        ? sec("Risk / reward",
          '<dl class="cx-facts">' +
          fact("Reference entry", Num(rr.reference_entry, function (v) { return F.fmtNum(v); }), "Technical reference level.") +
          fact("Technical stop", Num(rr.technical_stop, function (v) { return F.fmtNum(v); }), "Level where the setup fails.") +
          fact("Reference target", Num(rr.reference_target, function (v) { return F.fmtNum(v); }), "Measured reference objective.") +
          fact("Risk / reward", Num(rr.risk_reward_ratio, function (v) { return F.fmtNum(v); }), "Reward units per unit of risk.") +
          '</dl><p class="cx-note">Technical reference levels — not investment advice.</p>')
        : sec("Risk / reward", empty("Risk / reward", "Needs price, ATR and a real resistance level."));
      E("cx-tq").innerHTML = trend + rel + patt + risk +
        sec("Method", '<p class="cx-note">Calculated locally from verified backend history' +
          (d.history_source ? " (" + esc(d.history_source) + ")" : "") +
          (d.history_range ? " · " + esc(d.history_range) : "") + " · descriptive only.</p>" + prov(r.body));
    }).catch(function () { if (E("cx-tq")) E("cx-tq").innerHTML = sec("Technicals", err()); });
  }
  /* ---------------- research tab (new) ---------------- */
  function tResearchNew(sym, main) {
    main.innerHTML = '<div id="cx-research"></div>' +
      '<section class="cx-sec"><h2>Your notes</h2><div id="cx-notes">' + skel(2) + "</div></section>";
    function mount() {
      var host = E("cx-research");
      if (!host) return;
      if (window.FT_AI && window.FT_AI.mountPanel) { window.FT_AI.mountPanel(host, sym); return; }
      host.innerHTML = sec("AI Research", empty("AI Research", "Research module is still loading — retry in a moment."));
      setTimeout(mount, 800);
    }
    mount();
    API.get("research", { symbol: sym }).then(function (r) {
      if (!E("cx-notes")) return;
      var notes = (r.body && r.body.notes) || [];
      E("cx-notes").innerHTML =
        '<div class="cx-toolbar"><input id="cx-nt" class="cx-in" aria-label="Note title" placeholder="Title" style="flex:1;min-width:140px">' +
        "<button class='cx-btn' id='cx-ns'>Save note</button></div>" +
        '<textarea id="cx-nb" class="cx-in" aria-label="Note body" style="width:100%;min-height:64px" placeholder="Observation in your own words — stored locally"></textarea>' +
        '<div id="cx-nl" style="margin-top:8px">' + (notes.length ? notes.map(function (n) {
          return '<div class="cx-kv"><span class="k"><b>' + esc(n.title || "(untitled)") + "</b> · " + esc(n.section) +
            '<br><span class="mut">' + esc(String(n.body || "").slice(0, 160)) + "</span></span>" +
            '<span class="w"><button class="cx-btn2" data-delnote="' + n.id + '">Delete</button></span></div>';
        }).join("") : '<div class="cx-note">No notes yet.</div>') + "</div>";
      E("cx-ns").onclick = function () {
        API.post("research", { symbol: sym, section: "observations", title: E("cx-nt").value, body: E("cx-nb").value }).then(function (x) {
          if (!x.body.ok) { toast("Save failed."); return; }
          toast("Note saved."); tResearchNew(sym, main);
        });
      };
      Array.prototype.forEach.call(main.querySelectorAll("[data-delnote]"), function (x) {
        x.onclick = function () { API.del("research", { id: x.getAttribute("data-delnote") }).then(function () { tResearchNew(sym, main); }); };
      });
    });
  }
  /* publish override */
  if (window.FT_PAGES) window.FT_PAGES.pCompany = pCompany;
  window.FT_CX = { pCompany: pCompany, addHolding: openHoldingModal };
})();
