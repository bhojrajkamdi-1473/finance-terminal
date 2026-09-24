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
    if (v === null || v === undefined) return "—";
    var s = String(v).trim();
    if (/^(none|null|undefined|nan|-|n\/a)$/i.test(s) || s === "") return "—";
    return esc(s);
  }
  function Num(v, fn) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "string" && /^(none|null|undefined|nan|-|n\/a)$/i.test(v.trim())) return "—";
    if (isNaN(Number(v))) return "—";
    return fn(Number(v));
  }
  function dir(v) { return window.FT_FMT.dirClass(v); }
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
  function prov(env) {
    if (!env) return "";
    var src = esc(window.FT_FMT.srcName(env.source));
    var st = esc(env.timeliness || env.status || "");
    return '<div class="cx-prov">Source <b>' + src + "</b> · " + st + " · as of <b>" + esc(day(env.as_of)) + "</b></div>";
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
    if (CTABS.indexOf(tab) < 0) tab = "Overview";
    clearCx();
    V().innerHTML =
      '<div class="cx-wrap"><div class="cx-head" id="cx-head">' + skel(2) + "</div>" +
      '<nav class="cx-tabs" role="tablist" aria-label="Company sections" id="cx-tabs">' +
      CTABS.map(function (t) {
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
    if (s) s.innerHTML = badge(env.timeliness || env.status) + " " + esc(F.srcName(env.source)) + " · " + esc(day(env.as_of));
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
    E("cx-strip").innerHTML = cells.map(function (c, ix) {
      var n = c[1];
      if (!n || n.v === null) return '<div class="cx-m"><div class="l">' + c[0] + '</div><div class="v">—</div><div class="s">unavailable</div></div>';
      var key = "m" + ix;
      STRIP_INFO[key] = n.info;
      var clickable = n.info ? " data-insp='" + key + "' role='button' tabindex='0' title='Open formula inspector' style='cursor:pointer'" : "";
      return '<div class="cx-m"' + clickable + '><div class="l">' + c[0] + qBadge(n.kind) + '</div><div class="v">' + n.v +
        '</div><div class="s">' + (n.kind === "CALCULATED" ? "calculated" + ((n.info && n.info.variant) ? " · " + esc(n.info.variant) : "") : "reported") + "</div></div>";
    }).join("") + '<div id="cx-insp"></div>';
    Array.prototype.forEach.call(E("cx-strip").querySelectorAll("[data-insp]"), function (el) {
      function open() { showInspector(STRIP_INFO[el.getAttribute("data-insp")]); }
      el.onclick = open;
      el.onkeydown = function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); open(); } };
    });
  }
  function showInspector(info) {
    var host = E("cx-insp");
    if (!host || !info) return;
    host.innerHTML = '<div class="cx-inspector" role="dialog" aria-label="Formula inspector"><b>' + esc(info.label || "Calculated metric") +
      " " + esc(String(info.value)) + esc(info.unit || "") + " — CALCULATED</b>" +
      '<div class="cx-kv"><span class="k">Formula</span><span class="w">' + esc(info.formula || "") + "</span></div>" +
      (info.inputs || []).map(function (i) {
        return '<div class="cx-kv"><span class="k">' + esc(i.label || "") + (i.period ? " (" + esc(i.period) + ")" : "") +
          '</span><span class="w">' + esc(i.value === null || i.value === undefined ? "—" : String(i.value)) + " · " + esc(i.source || "") + "</span></div>";
      }).join("") +
      (info.variant ? '<div class="cx-note">Variant: ' + esc(info.variant) + "</div>" : "") +
      '<div class="cx-note">Calculated ' + esc(info.calculated_at || "") + ' · <button class="cx-btn2" id="cx-insp-x">Close</button></div></div>';
    E("cx-insp-x").onclick = function () { host.innerHTML = ""; };
  }
  function loadHead(sym) {
    Promise.all([API.get("company", { symbol: sym }), API.get("quote", { symbol: sym })]).then(function (rs) {
      if (!E("cx-head")) return;
      var prof = rs[0].body || {}, qenv = rs[1].body || {};
      var q = qenv.data || {}, p = prof.data || {};
      var nm = q.name || p.name || sym;
      var exch = q.exchange || p.exchange || "";
      var country = /\.NS$|\.BO$/.test(sym) ? "India" : (/NASDAQ|NYSE|NMS/i.test(exch) ? "USA" : "");
      E("cx-head").innerHTML =
        '<div class="cx-idrow">' + F.logo(sym, nm, 40) +
        '<div><h1 class="cx-name">' + esc(nm) + "</h1>" +
        '<div class="cx-sub">' + esc(sym.replace(/\.(NS|BO)$/, "")) + (exch ? " · " + esc(exch) : "") + (country ? " · " + esc(country) : "") +
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
      E("cx-pf").onclick = function () {
        var qty = prompt("Quantity held for " + sym + "?", "10");
        if (qty === null) return;
        var px = prompt("Average buy price (" + (q.currency || "") + ")?", String(q.price || ""));
        if (px === null) return;
        API.post("portfolio", { symbol: sym, name: q.name || "", quantity: Number(qty), avg_price: Number(px) }).then(function (r) {
          toast(r.body.ok ? sym + " added to portfolio." : "Could not save holding.");
        });
      };
      API.get("ratios", { symbol: sym }).then(function (r) {
        if (!E("cx-strip")) return;
        var d = (r.body && r.body.data) || {};
        paintStrip(sym, d, q, null);
        /* Ratio sheet (REPORTED first, CALCULATED fill) upgrades the strip
           when it arrives; reported cells never flicker to calculated. */
        API.get("ratiosheet", { symbol: sym }).then(function (rs) {
          if (!E("cx-strip")) return;
          var sheet = (rs.body && rs.body.data) || null;
          if (sheet) paintStrip(sym, d, q, sheet);
        }).catch(function () { /* strip already painted */ });
      });
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
          return '<div class="cx-kv"><span class="k">' + esc(p.label) + " (" + esc(p.state || "?") + ")" + '</span><span class="w mut">' +
            esc(String(p.last_latency_ms === null || p.last_latency_ms === undefined ? (p.last_error ? String(p.last_error).slice(0, 60) : "—") : p.last_latency_ms + " ms")) + "</span></div>";
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
      var items = ((r.body && r.body.data) || {}).items || [];
      E("cx-ov-news").innerHTML = sec("Latest news",
        items.length ? items.slice(0, 5).map(newsRow).join("") + prov(r.body)
        : empty("Latest news", "No news items were returned for this security."));
    });
    API.get("ratiosheet", { symbol: sym }).then(function (r) {
      if (!E("cx-ov-ratio")) return;
      var sheet = (r.body && r.body.data) || null, disp = (sheet && sheet.display) || {};
      var keys = ["roe", "roa", "roce", "net_margin", "debt_equity", "current_ratio"];
      var cells = keys.map(function (k) {
        var n = disp[k];
        if (!n) return "<div><dt>" + k.toUpperCase().replace("_", "/") + "</dt><dd>—</dd></div>";
        var v = n.unit === "%" ? Number(n.value).toFixed(1) + "%" : Number(n.value).toFixed(2) + "x";
        var b = n.kind === "CALCULATED" ? " <span class='cx-q cx-q-calc'>CALC</span>" : " <span class='cx-q cx-q-rep'>REP</span>";
        return "<div><dt>" + esc(n.label) + b + "</dt><dd>" + v + "</dd></div>";
      }).join("");
      E("cx-ov-ratio").innerHTML = sec("Key ratios",
        '<dl class="cx-facts">' + cells + "</dl>" +
        '<div class="cx-note">REPORTED values come from the provider; CALC values from the terminal ratio engine. Detail in Valuation.</div>');
    }).catch(function () { if (E("cx-ov-ratio")) E("cx-ov-ratio").innerHTML = ""; });
  }
  function tOverview(sym, main) { perf(sym, main); }
  /* statement table shared by financials */
  function stmtTable(title, env) {
    if (!env || !env.data || !((env.data.reports || []).length)) {
      return sec(title.toUpperCase(), empty(title, "No statement data is supplied by a configured provider right now."));
    }
    var d = env.data, reps = d.reports.slice(0, 4);
    var keys = Object.keys(reps[0]).filter(function (k) { return k !== "fiscalDateEnding" && k !== "reportedCurrency" && k !== "date"; }).slice(0, 12);
    var h = '<div class="cx-scroll"><table class="cx-t"><thead><tr><th scope="col">Particulars</th>' +
      reps.map(function (r) { return '<th scope="col" class="num">' + esc(r.fiscalDateEnding || r.date || "?") + "</th>"; }).join("") +
      '<th scope="col" class="num">YoY</th></tr></thead><tbody>';
    keys.forEach(function (k, ix) {
      var vals = reps.map(function (r) { var n = Number(r[k]); return (r[k] === "None" || isNaN(n)) ? null : n; });
      var yoy = (vals[0] !== null && vals[1] !== null && vals[1] !== 0) ? (vals[0] - vals[1]) / Math.abs(vals[1]) * 100 : null;
      h += '<tr' + (ix % 2 ? ' class="zeb"' : "") + '><td>' + esc(k) + "</td>" +
        vals.map(function (v) { return '<td class="num">' + (v === null ? "—" : F.fmtMoney(v)) + "</td>"; }).join("") +
        '<td class="num ' + dir(yoy) + '">' + (yoy === null ? "—" : F.fmtPct(yoy)) + "</td></tr>";
    });
    return sec(title.toUpperCase(), h + "</tbody></table></div>" +
      '<div class="cx-prov">Currency <b>' + esc(d.currency || "?") + "</b> · YoY shown only when mathematically valid.</div>" + prov(env));
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
        '<div class="cx-facts">' + grid.map(function (g) {
          return "<div><dt>" + g[0] + "</dt><dd>" + (g[1] === null ? "—" : g[1]) + "</dd></div>";
        }).join("") + "</div>" + prov(env));
      var rec = env.reconciliation;
      if (rec && rec.comparisons && rec.comparisons.length) {
        h += '<section class="cx-sec"><h2>Cross-check</h2><details><summary class="cx-note">Primary vs other sources (' +
          rec.comparisons.length + " fields)</summary>" + '<div class="cx-scroll" style="margin-top:8px"><table class="cx-t"><thead><tr><th scope="col">Metric</th><th scope="col">Primary</th><th scope="col">Other source</th></tr></thead><tbody>' +
          rec.comparisons.map(function (c) {
            var other = (c.cross_check || []).map(function (o) { return esc(o.source) + ": " + Cv(o.value); }).join("; ") || "—";
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
                  "</span><span class='w'>" + esc(i.value === null || i.value === undefined ? "—" : String(i.value)) + " · " + esc(i.source || "") + "</span></div>";
              }).join("") + '<div class="cx-note">Calculated ' + esc(n.calculated_at || "") + "</div></div>";
          };
        });
      }).catch(function () { /* reported grid already shown */ });
    }).catch(function () { if (E("cx-val")) E("cx-val").innerHTML = sec("Valuation", err()); });
  }
  function estCell(v) {
    if (v === undefined || v === null) return "—";
    if (typeof v === "string" && /^(none|null|undefined|nan|-|n\/a)$/i.test(v.trim())) return "—";
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
              (sv === undefined || sv === null ? "—" : typeof sv === "number" ? F.fmtPct(sv) : estCell(sv)) + "</td></tr>";
          }).join("") + "</tbody></table></div>";
      }
      E("cx-earn").innerHTML = sec("Earnings", prov(r.body)) +
        sec("Annual", (d.annual || []).length ? tbl(d.annual) : empty("Annual", "No annual earnings rows.")) +
        sec("Quarterly", (d.quarterly || []).length ? tbl(d.quarterly) : empty("Quarterly", "No quarterly earnings rows."));
    }).catch(function () { if (E("cx-earn")) E("cx-earn").innerHTML = sec("Earnings", err()); });
  }
  function newsRow(n) {
    var when = String(n.published_at || "").slice(0, 16).replace("T", " ");
    var title = n.url ? '<a href="' + esc(n.url) + '" target="_blank" rel="noopener">' + esc(n.title || "Untitled") + "</a>" : esc(n.title || "Untitled");
    return '<article class="cx-newsrow"><span class="tm">' + esc(when || "—") + '</span><span class="hl">' + title +
      "</span><span class='src'>" + esc(n.source || "—") + "</span><span class='cat'>" + esc(n.category || "") + "</span></article>";
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
          return "<tr" + (ix % 2 ? ' class="zeb"' : "") + "><td>" + Cv(o.category) + "</td><td class='num'>" +
            (o.percentage === null || o.percentage === undefined ? "—" : Number(o.percentage).toFixed(2) + "%") +
            "</td><td>" + Cv(o.holding_date) + "</td></tr>";
        }).join("") + "</tbody></table></div>" +
        '<div class="cx-note">Total ' + (total ? total.toFixed(1) + "%" : "—") + " across reported classes · as of <b>" + esc((owns[0] || {}).holding_date || "—") + "</b></div>" + prov(r.body));
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
    API.get("analytics", { symbol: sym }).then(function (r) {
      if (!E("cx-tq")) return;
      var d = (r.body && r.body.data) || null;
      if (!d) {
        E("cx-tq").innerHTML = sec("Technicals", empty("Technicals", "Technical analytics need verified price history.") + prov(r.body));
        return;
      }
      var ph = d.phase || {}, rs = d.relative_strength || {}, vcp = d.vcp || {},
        bo = d.breakout || {}, tt = d.trend_template || {}, rr = d.risk_reward || {};
      function fact(l, v, tip) {
        return "<div title='" + esc(tip || "") + "'><dt>" + l + "</dt><dd>" + v + "</dd></div>";
      }
      var trend = sec("Trend",
        '<dl class="cx-facts">' +
        fact("Weinstein phase", Cv(ph.phase), "Position of price relative to its long moving average.") +
        fact("Trend template", (tt.passed === undefined ? "—" : tt.passed + " / " + tt.total), "Number of bullish trend conditions met.") +
        fact("SMA 50", Num((d.snapshot || {}).sma50, function (v) { return F.fmtNum(v); }), "Average close, last 50 sessions.") +
        fact("SMA 200", Num((d.snapshot || {}).sma200, function (v) { return F.fmtNum(v); }), "Average close, last 200 sessions.") +
        "</dl>");
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
        sec("Method", '<p class="cx-note">Calculated locally from verified backend history (' +
          esc(d.history_source || "?") + ") · " + esc(d.history_range || "") + " · descriptive only.</p>" + prov(r.body));
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
  window.FT_CX = { pCompany: pCompany };
})();
